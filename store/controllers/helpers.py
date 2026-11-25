import os
import re
import math
import logging
from decimal import Decimal
from PIL import Image

from django.core.cache import cache
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from ..models import UserProfile
from ..cache_service import cache_get, cache_set

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger('store.admin_audit')


def _parse_int_id(raw_val):
    """Parse positive integer ID safely from user/query input without raising ValueError."""
    try:
        val = int(str(raw_val).strip())
        return val if val > 0 else None
    except (TypeError, ValueError):
        return None


def _get_safe_redirect(request, default='store:home', candidate=None):
    """التحقق من رابط التوجيه والتأكد من أمانه لمنع ثغرات Open Redirect"""
    next_url = candidate or request.POST.get('next') or request.GET.get('next') or request.META.get('HTTP_REFERER')
    if next_url and url_has_allowed_host_and_scheme(url=next_url, allowed_hosts={request.get_host()}):
        return next_url
    return reverse(default)


def _is_htmx_partial(request):
    """التحقق مما إذا كان الطلب استبدالاً جزئياً عبر HTMX وليس تنقلاً كاملاً معززاً بـ hx-boost"""
    return bool(
        request.headers.get('HX-Request')
        and not request.headers.get('HX-Boosted')
        and not request.GET.get('full_page')
    )


def _yer_to_sar(amount_yer, yer_per_sar):
    """تحويل المبلغ من الريال اليمني إلى الريال السعودي مقرباً للأعلى بدون كسور"""
    if not yer_per_sar:
        return 0
    return int(math.ceil(Decimal(str(amount_yer)) / Decimal(str(yer_per_sar))))


def _normalize_phone(phone_str):
    """تطبيع رقم الهاتف المحمول بإزالة الرموز ومفاتيح الدولة المتكررة للمقارنة الدقيقة"""
    digits = re.sub(r'\D', '', str(phone_str or ''))
    if digits.startswith('00967') and len(digits) >= 14:
        digits = digits[5:]
    elif digits.startswith('967') and len(digits) >= 12:
        digits = digits[3:]
    elif digits.startswith('0') and len(digits) == 10 and digits[1] == '7':
        digits = digits[1:]
    return digits


def _find_profile_by_phone(phone_str):
    """البحث عن ملف عميل برقم الهاتف مع احترام الصيغ الدولية والمحلية دون تطابق زائف"""
    raw = str(phone_str or '').strip()
    if not raw:
        return None
    exact = UserProfile.objects.select_related('user').filter(phone=raw).first()
    if exact:
        return exact
    norm = _normalize_phone(raw)
    if len(norm) < 8:
        return None
    candidates = UserProfile.objects.select_related('user').filter(phone__endswith=norm[-8:])
    for prof in candidates:
        if _normalize_phone(prof.phone) == norm:
            return prof
    return None


def _get_client_ip(request):
    """استخراج عنوان IP الحقيقي للعميل بأمان دون السماح بتزوير ترويسات X-Forwarded-For لتجاوز الحماية"""
    if os.getenv('TRUST_CF_CONNECTING_IP', 'False').lower() in ('true', '1'):
        cf_ip = request.META.get('HTTP_CF_CONNECTING_IP', '').strip()
        if cf_ip:
            return cf_ip
    xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if xff:
        parts = [ip.strip() for ip in xff.split(',') if ip.strip()]
        if parts:
            return parts[-1]
    return request.META.get('REMOTE_ADDR', '').strip() or 'unknown'


def _bump_rate_limit(key, timeout=600):
    """زيادة عداد الحماية ذرياً في الكاش دون إعادة تصفير المهلة مع كل محاولة"""
    if cache_get(key) is None:
        try:
            if cache.add(key, 1, timeout=timeout):
                return 1
        except Exception:
            pass
    try:
        return cache.incr(key)
    except ValueError:
        cache_set(key, 1, timeout=timeout)
        return 1
    except Exception:
        curr = int(cache_get(key, 0) or 0) + 1
        cache_set(key, curr, timeout=timeout)
        return curr


def _admin_change_url(model_name, obj_id):
    """توليد رابط صفحة التعديل في لوحة التحكم ديناميكياً لدعم المسار السري المخصص"""
    try:
        return reverse(f'admin:store_{model_name}_change', args=[obj_id])
    except Exception:
        prefix = os.getenv('DJANGO_ADMIN_URL', 'admin').strip().strip('/') or 'admin'
        return f"/{prefix}/store/{model_name}/{obj_id}/change/"


def validate_receipt_file(uploaded_file):
    """التحقق الأمني الشامل من ملف إشعار التحويل البنكي (الحجم، الامتداد، وتوقيع المحتوى الثنائي)"""
    if uploaded_file.size > 10 * 1024 * 1024:
        return False, 'حجم ملف إشعار التحويل كبير جداً. الحد الأقصى المسموح به هو 10 ميجابايت.'

    ext = os.path.splitext(uploaded_file.name)[1].lower()
    allowed_exts = ['.jpg', '.jpeg', '.png', '.webp', '.pdf', '.heic', '.heif']
    if ext not in allowed_exts:
        return False, 'صيغة ملف الإشعار غير مقبولة. يرجى رفع صورة أو مستند PDF صالح.'

    try:
        initial_pos = uploaded_file.tell() if hasattr(uploaded_file, 'tell') else 0
        header = uploaded_file.read(1024)
        if hasattr(uploaded_file, 'seek'):
            uploaded_file.seek(initial_pos)

        if ext == '.pdf':
            if not header.startswith(b'%PDF-'):
                return False, 'ملف الـ PDF تالف أو غير صالح كإشعار تحويل.'
        elif ext in ['.heic', '.heif']:
            if b'ftyp' not in header[:32]:
                return False, 'ملف صورة HEIC غير صالح أو تالف.'
        else:
            img = Image.open(uploaded_file)
            img.verify()
            if hasattr(uploaded_file, 'seek'):
                uploaded_file.seek(initial_pos)
    except Exception:
        return False, 'تعذر قراءة ملف الإشعار أو أنه ملف غير صالح كصورة إشعار.'

    return True, None


def _is_authorized_for_order(request, order):
    """التحقق من ملكية الطلب (صاحب الحساب، الإدارة، أو نفس جلسة الشراء الحالية)"""
    if request.session.get('last_order_number') == order.order_number:
        return True
    if order.order_number in (request.session.get('recent_order_numbers') or []):
        return True
    if request.user.is_authenticated:
        if request.user.is_staff or (order.user_id and order.user_id == request.user.id):
            return True
    return False
