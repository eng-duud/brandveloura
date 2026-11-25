import hashlib
import os
import secrets
import sys
from decimal import Decimal
from urllib.parse import quote, urlencode
import requests

from django.contrib import messages
from django.contrib.auth import (
    authenticate,
    login as auth_login,
    logout as auth_logout,
    update_session_auth_hash,
)
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from ..models import Notification, Order, ShippingZone, StoreSettings, UserProfile
from ..cache_service import cache_delete, cache_get, cache_get_or_set_safe
from ..push_notifications import link_endpoint_to_user
from .cart import (
    merge_and_restore_user_cart,
    refresh_cart_reservation,
    sync_cart_to_profile,
)
from .helpers import (
    _bump_rate_limit,
    _find_profile_by_phone,
    _get_client_ip,
    _get_safe_redirect,
    _normalize_phone,
    _yer_to_sar,
)


def _sync_session_push_to_user(request, user):
    """ربط اشتراك إشعارات الجهاز المحفوظ في الجلسة بالمستخدم المسجل تلقائياً"""
    ep = request.session.get('push_endpoint', '')
    if ep:
        link_endpoint_to_user(ep, user)


def login_view(request):
    """صفحة تسجيل الدخول الفاخرة للعملاء مع حماية ضد التخمين ودعم الدخول عبر Google"""
    if request.user.is_authenticated:
        return redirect('store:account_profile')

    next_url = request.GET.get('next', '')

    if request.method == 'POST':
        client_ip = _get_client_ip(request)
        identifier = request.POST.get('identifier', '').strip()
        password = request.POST.get('password', '')
        remember_me = request.POST.get('remember_me')
        next_url = request.POST.get('next', '')

        ip_throttle_key = f"bv_login_fails_ip_{client_ip}"
        ident_hash = hashlib.sha256(identifier.lower().encode('utf-8')).hexdigest()[:16] if identifier else 'empty'
        acct_throttle_key = f"bv_login_fails_acct_{ident_hash}"

        if (cache_get(ip_throttle_key, 0) or 0) >= 10 or (identifier and (cache_get(acct_throttle_key, 0) or 0) >= 8):
            messages.error(request, 'تم تجاوز الحد الأقصى لمحاولات تسجيل الدخول. يرجى الانتظار 10 دقائق والمحاولة مجدداً.')
            return render(request, 'store/auth/login.html', {'identifier': identifier, 'next_url': next_url})

        if not identifier or not password:
            messages.error(request, 'يرجى إدخال رقم الهاتف أو البريد الإلكتروني والرمز السري.')
            return render(request, 'store/auth/login.html', {'identifier': identifier, 'next_url': next_url})

        username = identifier
        if '@' in identifier:
            matched_user = User.objects.filter(email__iexact=identifier).first()
            if matched_user:
                username = matched_user.username
        else:
            matched_user_by_name = User.objects.filter(username__iexact=identifier).first()
            if matched_user_by_name:
                username = matched_user_by_name.username
            else:
                matched_profile = _find_profile_by_phone(identifier)
                if matched_profile:
                    username = matched_profile.user.username

        user = authenticate(request, username=username, password=password)
        if user is not None:
            if user.is_active:
                cache_delete(ip_throttle_key)
                cache_delete(acct_throttle_key)
                auth_login(request, user)

                expiry_seconds = 60 * 60 * 24 * 365 if remember_me else 60 * 60 * 24 * 90
                request.session.set_expiry(expiry_seconds)

                merge_and_restore_user_cart(request, user)
                _sync_session_push_to_user(request, user)

                display_name = user.first_name or user.username
                messages.success(request, f'تم تسجيل الدخول بنجاح. مرحباً {display_name}.')
                return redirect(_get_safe_redirect(request, default='store:home'))
            else:
                messages.error(request, 'هذا الحساب معطل حالياً. يرجى التواصل مع إدارة المتجر.')
        else:
            _bump_rate_limit(ip_throttle_key, timeout=600)
            if identifier:
                _bump_rate_limit(acct_throttle_key, timeout=600)
            messages.error(request, 'بيانات الدخول غير صحيحة. يرجى التحقق من رقم الهاتف أو البريد الإلكتروني والرمز السري.')

    return render(request, 'store/auth/login.html', {'next_url': next_url})


def register_view(request):
    """صفحة إنشاء حساب جديد برقم الهاتف والرمز السري"""
    if request.user.is_authenticated:
        return redirect('store:account_profile')

    next_url = request.GET.get('next', '')

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        email_raw = request.POST.get('email', '').strip().lower()
        phone = request.POST.get('phone', '').strip()
        password = request.POST.get('password', '')
        password_confirm = request.POST.get('password_confirm', '')
        next_url = request.POST.get('next', '')

        def _render_register_error(err_text):
            messages.error(request, err_text)
            return render(request, 'store/auth/register.html', {
                'next_url': next_url,
                'name': name,
                'email': email_raw,
                'phone': phone,
            })

        client_ip = _get_client_ip(request)
        reg_throttle_key = f"bv_register_rate_{client_ip}"
        reg_count = cache_get(reg_throttle_key, 0)
        if reg_count >= 10:
            return _render_register_error('تم تجاوز الحد المسموح لمحاولات إنشاء الحسابات من هذا الجهاز مؤقتاً. يرجى الانتظار 15 دقيقة.')

        if not name:
            return _render_register_error('يرجى إدخال الاسم.')

        if not phone:
            return _render_register_error('يرجى إدخال رقم الهاتف (مطلوب لتوثيق الحساب وتسجيل الدخول).')

        clean_phone_digits = _normalize_phone(phone)
        if len(clean_phone_digits) < 8:
            return _render_register_error('يرجى إدخال رقم هاتف صحيح لا يقل عن 8 أرقام.')

        if _find_profile_by_phone(phone):
            return _render_register_error('رقم الهاتف هذا مسجل مسبقاً بحساب آخر. يرجى تسجيل الدخول به.')

        email = email_raw
        if email:
            if '@' not in email:
                return _render_register_error('يرجى إدخال بريد إلكتروني صحيح أو ترك الحقل فارغاً.')
            if User.objects.filter(email__iexact=email).exists():
                return _render_register_error('البريد الإلكتروني مسجل مسبقاً. يرجى تسجيل الدخول.')
        else:
            email = f"u_{clean_phone_digits}@brandveloura.local"

        if password != password_confirm:
            return _render_register_error('الرمزان السريان غير متطابقين.')

        try:
            temp_user = User(username=f"u_{clean_phone_digits}", email=email, first_name=name)
            validate_password(password, user=temp_user)
        except ValidationError as exc:
            return _render_register_error(' '.join(exc.messages))

        clean_prefix = f"u_{clean_phone_digits}" if clean_phone_digits else (''.join(c for c in email.split('@')[0] if c.isalnum() or c in '_-') or 'user')
        final_username = clean_prefix
        counter = 1
        while User.objects.filter(username=final_username).exists():
            final_username = f"{clean_prefix}_{counter}"
            counter += 1

        new_user = User.objects.create_user(
            username=final_username,
            email=email,
            password=password,
            first_name=name,
        )

        UserProfile.objects.create(
            user=new_user,
            phone=phone,
        )

        _bump_rate_limit(reg_throttle_key, timeout=900)
        auth_login(request, new_user)
        request.session.set_expiry(60 * 60 * 24 * 365)
        sync_cart_to_profile(request)
        _sync_session_push_to_user(request, new_user)

        messages.success(request, f'تم إنشاء الحساب بنجاح. مرحباً {name}.')
        return redirect(_get_safe_redirect(request, default='store:home'))

    return render(request, 'store/auth/register.html', {'next_url': next_url})


def logout_view(request):
    """تسجيل الخروج الآمن مع منع هجمات تسجيل الخروج القسري من مواقع خارجية (Cross-Site GET Logout)"""
    if request.method != 'POST':
        sec_site = (request.headers.get('Sec-Fetch-Site') or '').lower()
        referer = request.META.get('HTTP_REFERER', '')
        if sec_site in ('cross-site', 'same-site'):
            return redirect('store:home')
        if referer and not url_has_allowed_host_and_scheme(url=referer, allowed_hosts={request.get_host()}):
            return redirect('store:home')
    auth_logout(request)
    messages.success(request, 'تم تسجيل الخروج بنجاح.')
    return redirect('store:home')


def google_login_redirect(request):
    """بدء تدفق المصادقة عبر Google OAuth 2.0 مع حماية state ضد هجمات Login CSRF"""
    settings = StoreSettings.get_settings()
    client_id = settings.effective_google_client_id
    next_url = request.GET.get('next', '')

    if not client_id:
        messages.info(
            request,
            'لتفعيل الدخول عبر Google، يرجى حفظ معرف Google Client ID في إعدادات المتجر بلوحة الإدارة.',
        )
        return redirect(f"{reverse('store:login')}?next={quote(next_url)}")

    redirect_uri = request.build_absolute_uri(reverse('store:google_callback'))
    if os.getenv('DJANGO_DEBUG', 'False').lower() not in ('true', '1') and redirect_uri.startswith('http://'):
        redirect_uri = redirect_uri.replace('http://', 'https://', 1)

    oauth_state = secrets.token_urlsafe(24)
    request.session['google_oauth_state'] = oauth_state
    if next_url and url_has_allowed_host_and_scheme(url=next_url, allowed_hosts={request.get_host()}):
        request.session['google_oauth_next'] = next_url
    else:
        request.session.pop('google_oauth_next', None)
    request.session.modified = True

    params = {
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': 'openid email profile',
        'access_type': 'online',
        'prompt': 'select_account',
        'state': oauth_state,
    }
    return redirect(f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}")


@csrf_exempt
def google_auth_callback(request):
    """
    استقبال التحقق من Google وتسجيل الدخول / إنشاء الحساب تلقائياً:
    1. عبر Google Identity Services (GIS) Token POST مع التحقق من g_csrf_token و aud و iss
    2. عبر OAuth 2.0 Authorization Code GET مع التحقق الصارم من state و email_verified
    """
    settings = StoreSettings.get_settings()
    saved_next = request.session.pop('google_oauth_next', '')
    next_url = _get_safe_redirect(request, default='store:home', candidate=saved_next)
    http_client = getattr(sys.modules.get('store.views'), 'requests', requests)

    credential = request.POST.get('credential')
    code = request.GET.get('code')

    user_email = None
    first_name = ''
    last_name = ''
    avatar_url = ''

    if credential:
        g_csrf_cookie = request.COOKIES.get('g_csrf_token', '')
        g_csrf_body = request.POST.get('g_csrf_token', '')
        if not g_csrf_cookie or not g_csrf_body or not secrets.compare_digest(g_csrf_cookie, g_csrf_body):
            messages.error(request, 'تعذر التحقق من رمز حماية CSRF الخاص بجلسة Google.')
            return redirect('store:login')

        client_id = settings.effective_google_client_id
        if not client_id:
            messages.error(request, 'تسجيل الدخول عبر Google غير مهيأ حالياً في المتجر.')
            return redirect('store:login')

        try:
            verify_res = http_client.post(
                'https://oauth2.googleapis.com/tokeninfo',
                data={'id_token': credential},
                timeout=8,
            )
            if verify_res.status_code == 200:
                payload = verify_res.json()
                if payload.get('aud') != client_id:
                    messages.error(request, 'رمز المصادقة غير صالح أو صادر لتطبيق آخر.')
                    return redirect('store:login')
                if payload.get('iss') not in ('https://accounts.google.com', 'accounts.google.com'):
                    messages.error(request, 'مصدر رمز المصادقة غير موثوق.')
                    return redirect('store:login')
                if payload.get('email_verified') not in (True, 'true'):
                    messages.error(request, 'البريد الإلكتروني لحساب Google غير موثق.')
                    return redirect('store:login')
                user_email = payload.get('email', '').strip().lower()
                first_name = payload.get('given_name') or payload.get('name', 'مستخدم')
                last_name = payload.get('family_name', '')
                avatar_url = payload.get('picture', '')
            else:
                messages.error(request, 'تعذر التحقق من رمز المصادقة المقدم من Google.')
                return redirect('store:login')
        except Exception:
            messages.error(request, 'تعذر الاتصال بخوادم Google في الوقت الحالي.')
            return redirect('store:login')

    elif code:
        expected_state = request.session.pop('google_oauth_state', None)
        received_state = request.GET.get('state', '')
        if not expected_state or not received_state or not secrets.compare_digest(str(expected_state), str(received_state)):
            messages.error(request, 'انتهت صلاحية جلسة المصادقة مع Google. يرجى المحاولة مرة أخرى.')
            return redirect('store:login')

        client_id = settings.effective_google_client_id
        client_secret = settings.effective_google_client_secret
        redirect_uri = request.build_absolute_uri(reverse('store:google_callback'))
        if os.getenv('DJANGO_DEBUG', 'False').lower() not in ('true', '1') and redirect_uri.startswith('http://'):
            redirect_uri = redirect_uri.replace('http://', 'https://', 1)

        try:
            token_res = http_client.post(
                'https://oauth2.googleapis.com/token',
                data={
                    'code': code,
                    'client_id': client_id,
                    'client_secret': client_secret,
                    'redirect_uri': redirect_uri,
                    'grant_type': 'authorization_code',
                },
                timeout=8,
            )
            token_json = token_res.json()
            access_token = token_json.get('access_token')
            if access_token:
                userinfo_res = http_client.get(
                    'https://www.googleapis.com/oauth2/v3/userinfo',
                    headers={'Authorization': f'Bearer {access_token}'},
                    timeout=8,
                )
                if userinfo_res.status_code == 200:
                    u_data = userinfo_res.json()
                    if u_data.get('email_verified') not in (True, 'true') and u_data.get('verified_email') is not True:
                        messages.error(request, 'البريد الإلكتروني لحساب Google غير موثق.')
                        return redirect('store:login')
                    user_email = u_data.get('email', '').strip().lower()
                    first_name = u_data.get('given_name') or u_data.get('name', 'مستخدم')
                    last_name = u_data.get('family_name', '')
                    avatar_url = u_data.get('picture', '')
                else:
                    messages.error(request, 'تعذر قراءة بيانات الملف الشخصي من Google.')
                    return redirect('store:login')
            else:
                err_desc = token_json.get('error_description') or token_json.get('error') or 'تعذر التحقق من كود المصادقة'
                messages.error(request, f'تعذر تسجيل الدخول عبر Google: {err_desc}')
                return redirect('store:login')
        except Exception:
            messages.error(request, 'تعذر استكمال الاتصال بخدمة Google في الوقت الحالي.')
            return redirect('store:login')

    else:
        messages.error(request, 'لم يتم تلقي بيانات مصادقة صالحة من Google.')
        return redirect('store:login')

    if not user_email:
        messages.error(request, 'لم نتمكن من قراءة البريد الإلكتروني من حساب Google.')
        return redirect('store:login')

    user = User.objects.filter(email__iexact=user_email).first()
    if not user:
        clean_prefix = ''.join(c for c in user_email.split('@')[0] if c.isalnum() or c in '_-') or 'google_user'
        final_username = clean_prefix
        counter = 1
        while User.objects.filter(username=final_username).exists():
            final_username = f"{clean_prefix}_{counter}"
            counter += 1

        user = User.objects.create_user(
            username=final_username,
            email=user_email,
            first_name=first_name,
            last_name=last_name,
        )
        user.set_unusable_password()
        user.save()
    else:
        profile_existing = UserProfile.objects.filter(user=user).first()
        was_google_verified = bool(profile_existing and profile_existing.avatar_url and 'googleusercontent.com' in profile_existing.avatar_url)
        if not user.is_staff and not user.is_superuser and not was_google_verified and user.has_usable_password():
            user.set_unusable_password()
            user.save(update_fields=['password'])

    Order.objects.filter(user__isnull=True, customer_email__iexact=user_email).update(user=user)

    profile, _ = UserProfile.objects.get_or_create(user=user)
    if avatar_url and not profile.avatar_url:
        profile.avatar_url = avatar_url
        profile.save(update_fields=['avatar_url'])

    auth_login(request, user)
    request.session.set_expiry(60 * 60 * 24 * 365)
    merge_and_restore_user_cart(request, user)
    _sync_session_push_to_user(request, user)

    display_name = user.first_name or user.username
    messages.success(request, f'تم تسجيل الدخول عبر Google بنجاح. مرحباً {display_name}.')
    return redirect(next_url)


@login_required(login_url='store:login')
def account_profile_view(request):
    """الملف الشخصي للمستخدم، سجل الطلبات، وتحديث بيانات التوصيل وكلمة المرور"""
    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'change_password':
            current_password = request.POST.get('current_password', '')
            new_password = request.POST.get('new_password', '')
            confirm_password = request.POST.get('confirm_password', '')

            if not request.user.has_usable_password():
                messages.info(request, 'تم تسجيل هذا الحساب عبر Google، ولا يتطلب كلمة مرور.')
                return redirect('store:account_profile')

            if not request.user.check_password(current_password):
                messages.error(request, 'كلمة المرور الحالية غير صحيحة.')
            elif new_password != confirm_password:
                messages.error(request, 'كلمتا المرور غير متطابقتين.')
            else:
                try:
                    validate_password(new_password, user=request.user)
                except ValidationError as exc:
                    messages.error(request, ' '.join(exc.messages))
                else:
                    request.user.set_password(new_password)
                    request.user.save()
                    update_session_auth_hash(request, request.user)
                    messages.success(request, 'تم تغيير كلمة المرور بنجاح.')
            return redirect('store:account_profile')

        else:
            first_name = request.POST.get('first_name', '').strip()
            last_name = request.POST.get('last_name', '').strip()
            phone = request.POST.get('phone', '').strip()
            preferred_city = request.POST.get('preferred_city', '').strip()
            shipping_address = request.POST.get('shipping_address', '').strip()

            if first_name:
                request.user.first_name = first_name
            if last_name:
                request.user.last_name = last_name
            request.user.save(update_fields=['first_name', 'last_name'])

            if not profile.phone and phone:
                clean_phone_digits = _normalize_phone(phone)
                if len(clean_phone_digits) >= 8 and not _find_profile_by_phone(phone):
                    profile.phone = phone

            profile.preferred_city = preferred_city
            profile.shipping_address = shipping_address
            profile.save()

            messages.success(request, 'تم حفظ البيانات بنجاح.')
            return redirect('store:account_profile')

    orders = (
        Order.objects.filter(user=request.user)
        .select_related('payment_method')
        .prefetch_related('items__product')
        .order_by('-created_at')
    )

    orders_list = list(orders)
    total_orders_count = len(orders_list)
    active_statuses = {'pending_verification', 'payment_verified', 'processing', 'out_for_delivery'}
    active_orders_count = sum(1 for o in orders_list if o.status in active_statuses)
    delivered_orders_count = sum(1 for o in orders_list if o.status == 'delivered')

    total_spent_yer = sum((o.total_yer for o in orders_list if o.status != 'cancelled'), Decimal('0.00'))
    settings = StoreSettings.get_settings()
    yer_per_sar = settings.yer_per_sar or Decimal('530.00')
    total_spent_sar = _yer_to_sar(total_spent_yer, yer_per_sar)

    shipping_zones = list(
        (
            cache_get_or_set_safe(
                'bv_shipping_zones_active',
                lambda: {z.id: z for z in ShippingZone.objects.filter(is_active=True).order_by('city_name')},
                timeout=300,
            ) or {}
        ).values()
    )

    notifications = list(Notification.objects.filter(recipient=request.user).order_by('-created_at'))
    notifications_unread_count = sum(1 for n in notifications if not n.is_read)

    context = {
        'profile': profile,
        'orders': orders_list,
        'shipping_zones': shipping_zones,
        'total_orders_count': total_orders_count,
        'active_orders_count': active_orders_count,
        'delivered_orders_count': delivered_orders_count,
        'total_spent_yer': total_spent_yer,
        'total_spent_sar': total_spent_sar,
        'notifications': notifications,
        'notifications_unread_count': notifications_unread_count,
    }
    return render(request, 'store/auth/account.html', context)


@login_required(login_url='store:login')
@require_POST
def reorder_view(request, order_number):
    """إعادة طلب منتجات من طلب سابق بالسعر الحي الحالي مع فحص المخزون ودعم الباقات"""
    order = get_object_or_404(
        Order.objects.prefetch_related('items__product__images', 'items__bundle__items__product'),
        order_number=order_number,
    )

    if order.user_id != request.user.id and not request.user.is_staff:
        messages.error(request, 'غير مصرح بالوصول إلى هذا الطلب.')
        return redirect('store:account_profile')

    cart = request.session.get('cart', {})
    added_count = 0

    for item in order.items.all():
        if item.bundle and item.bundle.is_active:
            bundle = item.bundle
            b_items = list(bundle.items.all())
            if b_items and all(
                bi.product and bi.product.is_active and bi.product.stock_quantity >= bi.quantity
                for bi in b_items
            ):
                b_key = f"bundle_{bundle.id}"
                cart[b_key] = {
                    'product_id': bundle.id,
                    'is_bundle': True,
                    'bundle_id': bundle.id,
                    'name': bundle.title_ar,
                    'brand': 'Brand Veloura',
                    'price_yer': float(bundle.price_yer),
                    'image_url': bundle.primary_image_url,
                    'quantity': cart.get(b_key, {}).get('quantity', 0) + 1,
                    'variant_info': f"باقة جاهزة ({len(b_items)} عناصر)",
                    'grade': '',
                }
                added_count += 1
        elif item.product and item.product.is_active and item.product.stock_quantity > 0:
            prod = item.product
            grade = 'original' if 'أصلي' in (item.variant_info or '') else ('master' if 'ماستر' in (item.variant_info or '') else '')
            live_price = float(prod.price_yer)
            if prod.has_grades:
                if grade == 'master' and prod.price_master_yer:
                    live_price = float(prod.price_master_yer)
                elif grade == 'original' and prod.price_original_yer:
                    live_price = float(prod.price_original_yer)

            existing_qty_for_prod = sum(
                int(v.get('quantity', 0))
                for v in cart.values()
                if not v.get('is_bundle') and str(v.get('product_id')) == str(prod.id)
            )
            available_to_add = max(0, prod.stock_quantity - existing_qty_for_prod)
            if available_to_add <= 0:
                continue
            qty_to_add = min(item.quantity, available_to_add)

            item_key = f"{prod.id}_{item.variant_info or 'default'}"
            if item_key in cart:
                cart[item_key]['quantity'] += qty_to_add
                cart[item_key]['price_yer'] = live_price
            else:
                cart[item_key] = {
                    'product_id': prod.id,
                    'name': prod.name_ar,
                    'brand': prod.effective_brand_name,
                    'price_yer': live_price,
                    'image_url': prod.primary_image_url or item.product_image_url,
                    'quantity': qty_to_add,
                    'variant_info': item.variant_info,
                    'grade': grade,
                }
            added_count += qty_to_add

    request.session['cart'] = cart
    request.session.modified = True
    sync_cart_to_profile(request)
    refresh_cart_reservation(request)

    if added_count > 0:
        messages.success(request, f'تمت إضافة {added_count} قطعة من طلبكم السابق #{order.order_number} إلى سلة المشتريات بنجاح.')
        return redirect('store:cart_view')
    else:
        messages.warning(request, 'عفواً، منتجات هذا الطلب لم تعد متوفرة في المخزون حالياً.')
        return redirect('store:account_profile')
