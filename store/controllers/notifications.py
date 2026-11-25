from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from ..models import Notification
from ..cache_service import cache_get_or_set_safe, invalidate_notification_cache


def notification_badge_view(request):
    """مكون HTMX لشارة عدد الإشعارات غير المقروءة + تمرير أحدث إشعار لعرضه في الشريط العلوي كالتطبيقات الأصلية"""
    unread_count = 0
    latest_unread = None
    if request.user.is_authenticated:
        user_cache_key = f'bv_unread_notifications_user_{request.user.pk}'
        unread_count = cache_get_or_set_safe(
            user_cache_key,
            lambda: Notification.objects.filter(recipient=request.user, is_read=False).count(),
            timeout=15,
            jitter_ratio=0.0,
        ) or 0
        if unread_count > 0:
            latest_unread = (
                Notification.objects.filter(recipient=request.user, is_read=False)
                .only('id', 'title', 'message', 'link', 'created_at')
                .order_by('-created_at')
                .first()
            )
    return render(request, 'store/partials/notification_badge.html', {
        'unread_count': unread_count,
        'latest_unread': latest_unread,
    })


def notifications_dropdown_view(request):
    """مكون HTMX لقائمة الإشعارات المنبثقة من أيقونة الجرس"""
    if not request.user.is_authenticated:
        return render(request, 'store/partials/notifications_dropdown.html', {
            'is_guest': True,
            'notifications': [],
            'unread_count': 0,
        })

    notifications = Notification.objects.filter(recipient=request.user).order_by('-created_at')[:8]
    unread_count = Notification.objects.filter(recipient=request.user, is_read=False).count()

    return render(request, 'store/partials/notifications_dropdown.html', {
        'is_guest': False,
        'notifications': notifications,
        'unread_count': unread_count,
    })


@require_POST
def mark_notification_read_view(request, notification_id):
    """تحديد إشعار واحد كمقروء وتحديث الحالة أو التوجيه"""
    if not request.user.is_authenticated:
        return JsonResponse({'status': 'unauthorized'}, status=401)

    notification = get_object_or_404(Notification, id=notification_id)
    if notification.recipient != request.user and not (notification.for_admin and request.user.is_staff):
        return JsonResponse({'status': 'forbidden'}, status=403)

    notification.mark_as_read()

    if request.headers.get('HX-Request'):
        notifications = Notification.objects.filter(recipient=request.user).order_by('-created_at')[:8]
        unread_count = Notification.objects.filter(recipient=request.user, is_read=False).count()
        return render(request, 'store/partials/notifications_dropdown.html', {
            'is_guest': False,
            'notifications': notifications,
            'unread_count': unread_count,
        })

    target_link = notification.link
    if target_link and url_has_allowed_host_and_scheme(url=target_link, allowed_hosts={request.get_host()}):
        return redirect(target_link)
    return redirect('store:account_profile')


@require_POST
def mark_all_notifications_read_view(request):
    """تحديد كافة إشعارات العميل كمقروءة دفعة واحدة"""
    if not request.user.is_authenticated:
        return JsonResponse({'status': 'unauthorized'}, status=401)

    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    invalidate_notification_cache(user_id=request.user.pk)

    if request.user.is_staff and request.POST.get('admin_scope') == '1':
        Notification.objects.filter(for_admin=True, is_read=False).update(is_read=True)
        invalidate_notification_cache(for_admin=True)

    if request.headers.get('HX-Request'):
        notifications = Notification.objects.filter(recipient=request.user).order_by('-created_at')[:8]
        return render(request, 'store/partials/notifications_dropdown.html', {
            'is_guest': False,
            'notifications': notifications,
            'unread_count': 0,
        })

    messages.success(request, 'تم تحديد كافة التنبيهات كمقروءة بنجاح.')
    return redirect('store:account_profile')
