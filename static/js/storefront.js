/**
 * Brand Veloura — Storefront Core UI, HTMX Hooks & Native-Style Top-Bar Push Notifications
 */
(function () {
    'use strict';

    function getCsrfToken() {
        const el = document.getElementById('bv-csrf-token');
        return (el && el.dataset.token) ? el.dataset.token : '';
    }

    function getCurrentUserKey() {
        return (document.body && document.body.dataset.userId) ? document.body.dataset.userId : 'guest';
    }

    // =========================================================================
    // 1. Cart Badges & Stock Alerts
    // =========================================================================
    function syncCartBadges() {
        const topContainer = document.getElementById('cart-badge-container');
        const bottomBadge = document.getElementById('bottom-bar-cart-badge');
        if (topContainer && bottomBadge) {
            bottomBadge.innerHTML = topContainer.innerHTML;
        }
    }

    // =========================================================================
    // 2. Toast Helper
    // =========================================================================
    function showToast(message, type = 'success') {
        const container = document.getElementById('toast-container');
        if (!container) return;
        const toast = document.createElement('div');
        const bgClass = type === 'success' ? 'bg-slate-900 text-white' : 'bg-brand-600 text-white';
        toast.className = `${bgClass} px-5 py-3 rounded-2xl shadow-luxury-lg text-xs font-bold flex items-center gap-2 animate-toast pointer-events-auto border border-white/10`;
        toast.innerHTML = `<i data-lucide="check-circle" class="w-4 h-4 text-rose-300"></i>`;
        const msgSpan = document.createElement('span');
        msgSpan.textContent = message;
        toast.appendChild(msgSpan);
        container.appendChild(toast);
        if (window.lucide) window.lucide.createIcons(toast);
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translate(-50%, -20px)';
            toast.style.transition = 'all 0.3s ease';
            setTimeout(() => toast.remove(), 300);
        }, 2500);
    }

    // =========================================================================
    // 3. Native-App Top Status-Bar / Heads-Up Notification Banner
    // =========================================================================
    const shownPushKeys = new Set();

    function playSubtleNotificationCue() {
        try {
            if (navigator.vibrate) {
                navigator.vibrate([120, 60, 120]);
            }
        } catch (_) {}
    }

    function showNativeTopNotification(notif) {
        if (!notif || (!notif.title && !notif.body)) return;

        const dedupeKey = String(notif.id || notif.tag || `${notif.title}::${notif.body}`);
        if (shownPushKeys.has(dedupeKey)) return;
        shownPushKeys.add(dedupeKey);
        if (shownPushKeys.size > 50) {
            const first = shownPushKeys.values().next().value;
            shownPushKeys.delete(first);
        }

        const container = document.getElementById('native-push-banner-container');
        if (!container) return;

        playSubtleNotificationCue();

        const targetUrl = notif.url || '/account/?tab=notifications';
        const iconUrl = notif.icon || '/static/icons/icon-192.png';

        const card = document.createElement('div');
        card.setAttribute('role', 'status');
        card.setAttribute('aria-live', 'polite');
        card.className = [
            'pointer-events-auto w-full max-w-md mx-auto',
            'bg-slate-900/95 text-white backdrop-blur-md',
            'rounded-2xl shadow-2xl',
            'border border-white/15 px-3.5 py-3 mb-2',
            'transition-all duration-300 ease-out cursor-pointer select-none'
        ].join(' ');
        card.style.transform = 'translateY(-24px)';
        card.style.opacity = '0';

        const wrapper = document.createElement('div');
        wrapper.className = 'flex items-start gap-3';

        const img = document.createElement('img');
        img.src = iconUrl;
        img.alt = 'Brand Veloura';
        img.width = 40;
        img.height = 40;
        img.className = 'w-10 h-10 rounded-xl object-cover border border-pink-300/40 shrink-0 mt-0.5 bg-white';

        const textWrap = document.createElement('div');
        textWrap.className = 'flex-1 min-w-0';

        const metaRow = document.createElement('div');
        metaRow.className = 'flex items-center justify-between gap-2 text-[10px] text-pink-200/90 font-semibold mb-0.5';
        const appName = document.createElement('span');
        appName.textContent = 'Brand Veloura • الآن';
        const closeBtn = document.createElement('button');
        closeBtn.type = 'button';
        closeBtn.setAttribute('aria-label', 'إغلاق الإشعار');
        closeBtn.className = 'text-slate-400 hover:text-white px-1.5 py-0.5 rounded-md text-xs leading-none cursor-pointer';
        closeBtn.textContent = '✕';

        metaRow.appendChild(appName);
        metaRow.appendChild(closeBtn);

        const titleEl = document.createElement('p');
        titleEl.className = 'text-xs sm:text-sm font-extrabold text-white truncate';
        titleEl.textContent = notif.title || 'Brand Veloura';

        const bodyEl = document.createElement('p');
        bodyEl.className = 'text-[11px] sm:text-xs text-slate-200/95 leading-snug line-clamp-2 mt-0.5';
        bodyEl.textContent = notif.body || '';

        textWrap.appendChild(metaRow);
        textWrap.appendChild(titleEl);
        if (notif.body) textWrap.appendChild(bodyEl);

        wrapper.appendChild(img);
        wrapper.appendChild(textWrap);
        card.appendChild(wrapper);

        const handleBar = document.createElement('div');
        handleBar.className = 'w-9 h-1 rounded-full bg-white/25 mx-auto mt-2';
        card.appendChild(handleBar);

        let dismissed = false;
        function dismissCard() {
            if (dismissed) return;
            dismissed = true;
            card.style.transform = 'translateY(-24px)';
            card.style.opacity = '0';
            setTimeout(() => card.remove(), 280);
        }

        closeBtn.addEventListener('click', function (e) {
            e.stopPropagation();
            dismissCard();
        });

        card.addEventListener('click', function () {
            dismissCard();
            if (targetUrl) {
                window.location.href = targetUrl;
            }
        });

        // Touch swipe-up to dismiss like iOS/Android heads-up notifications
        let touchStartY = null;
        card.addEventListener('touchstart', function (e) {
            if (e.touches && e.touches.length === 1) {
                touchStartY = e.touches[0].clientY;
            }
        }, { passive: true });
        card.addEventListener('touchmove', function (e) {
            if (touchStartY !== null && e.touches && e.touches.length === 1) {
                const deltaY = e.touches[0].clientY - touchStartY;
                if (deltaY < -28) {
                    touchStartY = null;
                    dismissCard();
                }
            }
        }, { passive: true });

        container.appendChild(card);
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                card.style.transform = 'translateY(0)';
                card.style.opacity = '1';
            });
        });

        setTimeout(dismissCard, 6500);
    }

    function inspectNotificationBadgeForNewAlert(seedOnly) {
        const badge = document.getElementById('notification-badge');
        if (!badge) return;
        const userKey = getCurrentUserKey();
        if (!userKey || userKey === 'guest') return;

        const latestId = parseInt(badge.dataset.notifId || '0', 10);
        if (!latestId) return;

        const storageKey = `bv_last_seen_notif_${userKey}`;
        let prevId = 0;
        try {
            prevId = parseInt(localStorage.getItem(storageKey) || '0', 10) || 0;
        } catch (_) {}

        if (seedOnly && prevId === 0) {
            try {
                localStorage.setItem(storageKey, String(latestId));
            } catch (_) {}
            return;
        }

        if (latestId > prevId) {
            try {
                localStorage.setItem(storageKey, String(latestId));
            } catch (_) {}

            const payload = {
                id: `db-notif-${latestId}`,
                title: badge.dataset.notifTitle || 'Brand Veloura',
                body: badge.dataset.notifBody || '',
                url: badge.dataset.notifUrl || '/account/?tab=notifications',
                icon: '/static/icons/icon-192.png'
            };

            showNativeTopNotification(payload);

            // If tab is hidden/backgrounded, also raise an OS status-bar notification
            if (document.hidden && 'Notification' in window && Notification.permission === 'granted' && 'serviceWorker' in navigator) {
                navigator.serviceWorker.ready.then((reg) => {
                    reg.showNotification(payload.title, {
                        body: payload.body,
                        icon: payload.icon,
                        badge: '/static/icons/icon-192.png',
                        vibrate: [200, 100, 200],
                        renotify: true,
                        tag: payload.id,
                        dir: 'rtl',
                        lang: 'ar',
                        data: { url: payload.url }
                    });
                }).catch(() => {});
            }
        }
    }

    // =========================================================================
    // 4. Catalog Search & Filter Controls
    // =========================================================================
    function updateActiveFiltersBar(form) {
        if (!form) return;
        const activeBar = form.querySelector('.active-filters-bar');
        if (!activeBar) return;

        const qInput = form.querySelector('input[name="q"]');
        const searchVal = qInput ? qInput.value.trim() : '';

        const activeChips = [];
        if (searchVal) {
            activeChips.push(`"${searchVal}"`);
        }

        const selects = form.querySelectorAll('select');
        selects.forEach((s) => {
            if (s.name === 'sort') {
                if (s.value && s.value !== 'newest') {
                    const opt = s.options[s.selectedIndex];
                    if (opt) activeChips.push(opt.text);
                }
            } else if (s.value && s.value !== '') {
                const opt = s.options[s.selectedIndex];
                if (opt) activeChips.push(opt.dataset.short || opt.text);
            }
        });

        if (activeChips.length > 0) {
            activeBar.classList.remove('hidden');
            const chipsContainer = activeBar.querySelector('.active-filter-chips') || activeBar.querySelector('div:first-child');
            if (chipsContainer) {
                chipsContainer.innerHTML = '';
                const titleSpan = document.createElement('span');
                titleSpan.textContent = 'تصفية نشطة:';
                chipsContainer.appendChild(titleSpan);
                activeChips.forEach((c) => {
                    const chipSpan = document.createElement('span');
                    chipSpan.className = 'px-2 py-0.5 rounded-md bg-pink-100 text-brand-700 font-medium inline-block';
                    chipSpan.textContent = c;
                    chipsContainer.appendChild(chipSpan);
                });
            }
        } else {
            activeBar.classList.add('hidden');
        }
    }

    function syncFilterBtn(select) {
        const btn = select.closest('.filter-btn');
        if (!btn) return;
        const label = btn.querySelector('.filter-label');
        const icon = btn.querySelector('i, svg');
        const dot = btn.querySelector('.filter-dot');
        const val = select.value;
        const isSort = select.name === 'sort';
        const isDefault = !val || (isSort && val === 'newest');

        if (isDefault) {
            if (label) label.textContent = select.dataset.defaultLabel || 'تصفية';
            btn.classList.remove('bg-slate-900', 'text-white', 'border-slate-900', 'shadow-xs');
            btn.classList.add('bg-pink-50/40', 'hover:bg-pink-100/60', 'text-slate-700', 'border-pink-200/80');
            if (icon) {
                icon.classList.remove('text-pink-300');
                icon.classList.add('text-brand-600');
            }
            if (dot) dot.classList.add('hidden');
        } else {
            const opt = select.options[select.selectedIndex];
            const text = (opt && (opt.dataset.short || opt.getAttribute('data-short'))) ||
                         (opt ? opt.text.replace(/^(عطور|ساعات|محرك|مستحضرات)\s+/, '') : '');
            if (label && text) label.textContent = text;
            btn.classList.remove('bg-pink-50/40', 'hover:bg-pink-100/60', 'text-slate-700', 'border-pink-200/80');
            btn.classList.add('bg-slate-900', 'text-white', 'border-slate-900', 'shadow-xs');
            if (icon) {
                icon.classList.remove('text-brand-600');
                icon.classList.add('text-pink-300');
            }
            if (dot) dot.classList.remove('hidden');
        }
        updateActiveFiltersBar(select.closest('form'));
    }

    function toggleSearchInput(btn) {
        const form = btn.closest('form');
        if (!form) return;
        const searchRow = form.querySelector('.catalog-search-row') || form.querySelector('#search-input-row');
        if (!searchRow) return;

        const isHidden = searchRow.classList.contains('hidden');
        if (isHidden) {
            searchRow.classList.remove('hidden');
            const input = searchRow.querySelector('input[name="q"]');
            if (input) {
                input.focus();
                input.select();
            }
        } else {
            const input = searchRow.querySelector('input[name="q"]');
            if (input && input.value.trim() !== '') {
                if (window.htmx) {
                    window.htmx.trigger(input, 'search');
                }
            } else {
                searchRow.classList.add('hidden');
            }
        }
        if (window.lucide) {
            window.lucide.createIcons(searchRow);
        }
    }

    function handleSearchInput(input) {
        const form = input.closest('form');
        const clearBtn = form ? form.querySelector('.search-clear-btn') : input.parentElement.querySelector('.search-clear-btn');
        if (clearBtn) {
            if (input.value && input.value.trim().length > 0) {
                clearBtn.classList.remove('hidden');
            } else {
                clearBtn.classList.add('hidden');
            }
        }
        if (form) {
            const searchBtn = form.querySelector('.search-toggle-btn') || form.querySelector('#search-toggle-btn');
            if (searchBtn) {
                const label = searchBtn.querySelector('.filter-label');
                const dot = searchBtn.querySelector('.filter-dot');
                const icon = searchBtn.querySelector('i, svg');
                const val = input.value.trim();
                const isFiveButtons = searchBtn.closest('.grid-cols-5') || (searchBtn.parentElement && searchBtn.parentElement.classList.contains('flex'));
                const maxLen = isFiveButtons ? 6 : 8;
                if (val) {
                    if (label) label.textContent = val.length > maxLen ? val.substring(0, maxLen) + '...' : val;
                    if (dot) dot.classList.remove('hidden');
                    searchBtn.classList.add('bg-slate-900', 'text-white', 'border-slate-900', 'shadow-xs');
                    searchBtn.classList.remove('bg-pink-50/40', 'hover:bg-pink-100/60', 'text-slate-700', 'border-pink-200/80');
                    if (icon) {
                        icon.classList.add('text-pink-300');
                        icon.classList.remove('text-brand-600');
                    }
                } else {
                    if (label) label.textContent = 'البحث';
                    if (dot) dot.classList.add('hidden');
                    searchBtn.classList.remove('bg-slate-900', 'text-white', 'border-slate-900', 'shadow-xs');
                    searchBtn.classList.add('bg-pink-50/40', 'hover:bg-pink-100/60', 'text-slate-700', 'border-pink-200/80');
                    if (icon) {
                        icon.classList.remove('text-pink-300');
                        icon.classList.add('text-brand-600');
                    }
                }
            }
            updateActiveFiltersBar(form);
        }
    }

    function clearSearchInput(btnOrEl) {
        const form = btnOrEl.closest('form');
        if (!form) return;
        const input = form.querySelector('input[name="q"]');
        if (!input) return;
        input.value = '';
        const clearBtn = form.querySelector('.search-clear-btn');
        if (clearBtn) clearBtn.classList.add('hidden');
        handleSearchInput(input);
        updateActiveFiltersBar(form);
        input.focus();
        if (window.htmx) {
            window.htmx.trigger(input, 'search');
        }
    }

    function resetCatalogFilterForm(el) {
        const form = (el && el.closest('form')) || document.querySelector('#perfumes-filter-form, #watches-filter-form, #cosmetics-filter-form, #filter-controls-form, #brand-filter-form');
        if (!form) return;

        const qInput = form.querySelector('input[name="q"]');
        if (qInput) {
            qInput.value = '';
            const clearBtn = qInput.parentElement.querySelector('.search-clear-btn');
            if (clearBtn) clearBtn.classList.add('hidden');
        }

        const searchRow = form.querySelector('.catalog-search-row') || form.querySelector('#search-input-row');
        if (searchRow) searchRow.classList.add('hidden');

        const searchBtn = form.querySelector('.search-toggle-btn') || form.querySelector('#search-toggle-btn');
        if (searchBtn) {
            const label = searchBtn.querySelector('.filter-label');
            if (label) label.textContent = 'البحث';
            const dot = searchBtn.querySelector('.filter-dot');
            if (dot) dot.classList.add('hidden');
            searchBtn.classList.remove('bg-slate-900', 'text-white', 'border-slate-900', 'shadow-xs');
            searchBtn.classList.add('bg-pink-50/40', 'hover:bg-pink-100/60', 'text-slate-700', 'border-pink-200/80');
            const icon = searchBtn.querySelector('i, svg');
            if (icon) {
                icon.classList.remove('text-pink-300');
                icon.classList.add('text-brand-600');
            }
        }

        const selects = form.querySelectorAll('select');
        selects.forEach((select) => {
            select.selectedIndex = 0;
            select.value = select.name === 'sort' ? 'newest' : '';
            syncFilterBtn(select);
        });

        const activeBar = form.querySelector('.active-filters-bar');
        if (activeBar) activeBar.classList.add('hidden');
    }

    // =========================================================================
    // 5. Modals, Sidebars & Dropdowns
    // =========================================================================
    function openQuickViewModal() {
        const modal = document.getElementById('quick-view-modal');
        if (modal) {
            modal.classList.remove('hidden');
            modal.classList.add('flex');
            document.body.style.overflow = 'hidden';
            if (window.lucide) window.lucide.createIcons(modal);
        }
    }

    function closeQuickViewModal() {
        const modal = document.getElementById('quick-view-modal');
        if (modal) {
            modal.classList.add('hidden');
            modal.classList.remove('flex');
            document.body.style.overflow = '';
        }
    }

    function openMobileSidebar() {
        const drawer = document.getElementById('mobile-sidebar-drawer');
        const backdrop = document.getElementById('mobile-sidebar-backdrop');
        const panel = document.getElementById('mobile-sidebar-panel');
        if (!drawer || !backdrop || !panel) return;

        drawer.classList.remove('pointer-events-none');
        backdrop.classList.remove('opacity-0');
        backdrop.classList.add('opacity-100');
        panel.classList.remove('translate-x-full');
        panel.classList.add('translate-x-0');
        document.body.style.overflow = 'hidden';
        if (window.lucide) window.lucide.createIcons(panel);
    }

    function closeMobileSidebar() {
        const drawer = document.getElementById('mobile-sidebar-drawer');
        const backdrop = document.getElementById('mobile-sidebar-backdrop');
        const panel = document.getElementById('mobile-sidebar-panel');
        if (!drawer || !backdrop || !panel) return;

        backdrop.classList.remove('opacity-100');
        backdrop.classList.add('opacity-0');
        panel.classList.remove('translate-x-0');
        panel.classList.add('translate-x-full');
        setTimeout(() => {
            drawer.classList.add('pointer-events-none');
            document.body.style.overflow = '';
        }, 300);
    }

    function toggleMobileSearch() {
        const searchBar = document.getElementById('mobile-search-bar');
        const searchInput = document.getElementById('mobile-search-input');
        if (!searchBar) return;
        const isHidden = searchBar.classList.contains('hidden');
        if (isHidden) {
            searchBar.classList.remove('hidden');
            if (searchInput) {
                setTimeout(() => searchInput.focus(), 60);
            }
        } else {
            searchBar.classList.add('hidden');
        }
    }

    function toggleUserMenu(event) {
        if (event) event.stopPropagation();
        const notifMenu = document.getElementById('notifications-dropdown-menu');
        if (notifMenu) notifMenu.classList.add('hidden');
        const menu = document.getElementById('user-dropdown-menu');
        if (menu) {
            menu.classList.toggle('hidden');
        }
    }

    function toggleNotificationsMenu(event) {
        if (event) event.stopPropagation();
        const userMenu = document.getElementById('user-dropdown-menu');
        if (userMenu) userMenu.classList.add('hidden');
        const menu = document.getElementById('notifications-dropdown-menu');
        if (menu) {
            menu.classList.toggle('hidden');
            if (!menu.classList.contains('hidden')) {
                if (navigator.clearAppBadge) {
                    navigator.clearAppBadge().catch(() => {});
                }
                if (window.lucide) {
                    window.lucide.createIcons(menu);
                }
            }
        }
    }

    // =========================================================================
    // 6. PWA Install & Web Push Subscription Management
    // =========================================================================
    let deferredPrompt = null;
    let notifPromptTimer = null;
    let notifAnimTimer = null;

    function urlBase64ToUint8Array(base64String) {
        const padding = '='.repeat((4 - base64String.length % 4) % 4);
        const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
        const rawData = window.atob(base64);
        const outputArray = new Uint8Array(rawData.length);
        for (let i = 0; i < rawData.length; ++i) {
            outputArray[i] = rawData.charCodeAt(i);
        }
        return outputArray;
    }

    async function subscribeAndSyncPushEndpoint(forceResubscribe) {
        if (!('serviceWorker' in navigator) || !('PushManager' in window)) return false;
        if (!('Notification' in window) || Notification.permission !== 'granted') return false;

        try {
            const reg = await navigator.serviceWorker.ready;
            let subscription = await reg.pushManager.getSubscription();

            if (!subscription || forceResubscribe) {
                const keyRes = await fetch('/api/push/vapid-key/');
                const keyData = await keyRes.json();
                if (!keyData || !keyData.publicKey) return false;
                subscription = await reg.pushManager.subscribe({
                    userVisibleOnly: true,
                    applicationServerKey: urlBase64ToUint8Array(keyData.publicKey)
                });
            }

            if (!subscription) return false;

            const res = await fetch('/api/push/subscribe/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken()
                },
                body: JSON.stringify(subscription)
            });

            if (res.ok) {
                try {
                    sessionStorage.setItem(`bv_push_synced_${getCurrentUserKey()}`, '1');
                } catch (_) {}
                return true;
            }
        } catch (err) {
            console.warn('Push sync error:', err);
        }
        return false;
    }

    function dismissInstallBanner() {
        const installBanner = document.getElementById('pwa-install-banner');
        if (installBanner) installBanner.classList.add('hidden');
        try {
            sessionStorage.setItem('bv_install_dismissed', 'true');
        } catch (_) {}
    }

    function scheduleNotifPrompt(delay = 1200, force = false) {
        if (notifPromptTimer) {
            clearTimeout(notifPromptTimer);
            notifPromptTimer = null;
        }
        notifPromptTimer = setTimeout(() => {
            showNotifPromptCard(force);
        }, delay);
    }

    function showNotifPromptCard(force = false) {
        const notifCard = document.getElementById('pwa-notif-card');
        if (!notifCard) return;
        if (!('Notification' in window) || !('serviceWorker' in navigator)) return;
        if (Notification.permission === 'granted' || Notification.permission === 'denied' || localStorage.getItem('bv_notif_granted') === 'true') return;
        if (!force && sessionStorage.getItem('bv_notif_dismissed')) return;

        if (notifAnimTimer) {
            clearTimeout(notifAnimTimer);
            notifAnimTimer = null;
        }

        if (!notifCard.classList.contains('hidden') && notifCard.classList.contains('opacity-100')) return;

        notifCard.classList.remove('hidden');
        notifAnimTimer = setTimeout(() => {
            notifCard.classList.remove('translate-y-4', 'opacity-0', 'pointer-events-none');
            notifCard.classList.add('translate-y-0', 'opacity-100', 'pointer-events-auto');
            if (window.lucide) window.lucide.createIcons(notifCard);
        }, 60);
    }

    function hideNotifPromptCard() {
        const notifCard = document.getElementById('pwa-notif-card');
        if (!notifCard) return;
        if (notifAnimTimer) {
            clearTimeout(notifAnimTimer);
            notifAnimTimer = null;
        }
        notifCard.classList.remove('translate-y-0', 'opacity-100', 'pointer-events-auto');
        notifCard.classList.add('translate-y-4', 'opacity-0', 'pointer-events-none');
        notifAnimTimer = setTimeout(() => {
            notifCard.classList.add('hidden');
        }, 300);
    }

    function dismissNotifPrompt() {
        if (notifPromptTimer) {
            clearTimeout(notifPromptTimer);
            notifPromptTimer = null;
        }
        hideNotifPromptCard();
        try {
            sessionStorage.setItem('bv_notif_dismissed', 'true');
        } catch (_) {}
    }

    async function requestPushPermission() {
        if (notifPromptTimer) {
            clearTimeout(notifPromptTimer);
            notifPromptTimer = null;
        }

        if (!('Notification' in window) || !('serviceWorker' in navigator)) {
            showToast('المتصفح الحالي لا يدعم خاصية الإشعارات', 'error');
            hideNotifPromptCard();
            return;
        }

        if (Notification.permission === 'denied') {
            showToast('تم رفض إذن الإشعارات مسبقاً. يرجى تفعيلها من إعدادات المتصفح أو جهازك.', 'error');
            hideNotifPromptCard();
            sessionStorage.setItem('bv_notif_dismissed', 'true');
            return;
        }

        const notifActionBtn = document.querySelector('#pwa-notif-card button[onclick="requestPushPermission()"]');
        const originalBtnHtml = notifActionBtn ? notifActionBtn.innerHTML : '';
        if (notifActionBtn) {
            notifActionBtn.disabled = true;
            notifActionBtn.classList.add('opacity-75');
            notifActionBtn.innerHTML = '<span>جاري التفعيل...</span>';
        }

        try {
            const permission = await Notification.requestPermission();
            if (permission === 'granted') {
                await subscribeAndSyncPushEndpoint(false);
                localStorage.setItem('bv_notif_granted', 'true');
                sessionStorage.removeItem('bv_notif_dismissed');
                hideNotifPromptCard();
                showToast('تم تفعيل الإشعارات بنجاح ✨ ستصلك تحديثات طلباتك وعروضنا في الشريط العلوي لهاتفك.', 'success');
            } else {
                hideNotifPromptCard();
                sessionStorage.setItem('bv_notif_dismissed', 'true');
                if (permission === 'denied') {
                    showToast('تم رفض إذن الإشعارات من المتصفح.', 'error');
                }
            }
        } catch (err) {
            console.error('Push permission request failed:', err);
            hideNotifPromptCard();
            sessionStorage.setItem('bv_notif_dismissed', 'true');
        } finally {
            if (notifActionBtn) {
                notifActionBtn.disabled = false;
                notifActionBtn.classList.remove('opacity-75');
                notifActionBtn.innerHTML = originalBtnHtml;
                if (window.lucide) window.lucide.createIcons(notifActionBtn);
            }
        }
    }

    function bindInstallButton() {
        const installBtn = document.getElementById('pwa-install-btn');
        if (!installBtn || installBtn.dataset.bound === '1') return;
        installBtn.dataset.bound = '1';
        installBtn.addEventListener('click', async () => {
            if (!deferredPrompt) return;
            deferredPrompt.prompt();
            const { outcome } = await deferredPrompt.userChoice;
            deferredPrompt = null;
            const installBanner = document.getElementById('pwa-install-banner');
            if (installBanner) installBanner.classList.add('hidden');
            if (outcome === 'accepted' && 'Notification' in window && Notification.permission === 'default') {
                sessionStorage.removeItem('bv_notif_dismissed');
                scheduleNotifPrompt(1500, true);
            }
        });
    }

    // =========================================================================
    // 7. Event Listeners & Lifecycle Initialization
    // =========================================================================
    function checkStandaloneNotificationPrompt() {
        const isStandalone = (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) || window.navigator.standalone === true;
        if (isStandalone && 'Notification' in window && Notification.permission === 'default' && localStorage.getItem('bv_notif_granted') !== 'true') {
            if (!sessionStorage.getItem('bv_notif_dismissed')) {
                scheduleNotifPrompt(1200);
            }
        }
    }

    function initGlobalListeners() {
        try {
            localStorage.removeItem('bv_notif_dismissed_until');
        } catch (_) {}

        if (window.lucide) window.lucide.createIcons();
        bindInstallButton();
        inspectNotificationBadgeForNewAlert(true);
        checkStandaloneNotificationPrompt();

        document.body.addEventListener('cartUpdated', syncCartBadges);
        document.body.addEventListener('outOfStock', function () {
            showToast('نعتذر، هذا المنتج غير متوفر في المخزون حالياً.', 'error');
        });
        document.body.addEventListener('maxStockReached', function () {
            showToast('تم الوصول للحد الأقصى المتوفر في المخزون لهذا المنتج.', 'error');
        });

        document.body.addEventListener('htmx:configRequest', function (evt) {
            const verb = (evt.detail.verb || 'get').toUpperCase();
            if (verb !== 'GET' && verb !== 'HEAD' && verb !== 'OPTIONS') {
                const token = getCsrfToken();
                if (token) {
                    evt.detail.headers['X-CSRFToken'] = token;
                }
            }
        });

        document.body.addEventListener('htmx:afterSwap', function (evt) {
            const target = evt.detail && evt.detail.target;
            if (window.lucide) window.lucide.createIcons(target || document);
            if (target && target.id === 'quick-view-content') {
                openQuickViewModal();
            }
            if (target && target.id === 'cart-badge-container') {
                syncCartBadges();
            }
            if (target && target.id === 'notification-badge-container') {
                inspectNotificationBadgeForNewAlert(false);
            }
            bindInstallButton();
        });

        document.addEventListener('htmx:afterSettle', function (evt) {
            if (window.lucide && typeof window.lucide.createIcons === 'function') {
                window.lucide.createIcons((evt.detail && evt.detail.elt) || document);
            }
            if (typeof window.initLuxurySliders === 'function') {
                window.initLuxurySliders();
            }
            // Re-sync push subscription if user logged in via hx-boost
            if ('Notification' in window && Notification.permission === 'granted') {
                const syncFlag = `bv_push_synced_${getCurrentUserKey()}`;
                if (!sessionStorage.getItem(syncFlag)) {
                    subscribeAndSyncPushEndpoint(false);
                }
            }
        });

        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') {
                closeQuickViewModal();
                closeMobileSidebar();
            }
        });

        document.addEventListener('click', function (e) {
            const menu = document.getElementById('user-dropdown-menu');
            const container = document.getElementById('user-menu-dropdown-container');
            if (menu && !menu.classList.contains('hidden')) {
                if (container && !container.contains(e.target)) {
                    menu.classList.add('hidden');
                }
            }
            const notifMenu = document.getElementById('notifications-dropdown-menu');
            const notifContainer = document.getElementById('notifications-menu-container');
            if (notifMenu && !notifMenu.classList.contains('hidden')) {
                if (notifContainer && !notifContainer.contains(e.target)) {
                    notifMenu.classList.add('hidden');
                }
            }
        });

        window.addEventListener('beforeinstallprompt', (e) => {
            e.preventDefault();
            deferredPrompt = e;
            const installBanner = document.getElementById('pwa-install-banner');
            if (installBanner && !sessionStorage.getItem('bv_install_dismissed')) {
                installBanner.classList.remove('hidden');
            }
            bindInstallButton();
        });

        window.addEventListener('appinstalled', () => {
            const installBanner = document.getElementById('pwa-install-banner');
            if (installBanner) installBanner.classList.add('hidden');
            deferredPrompt = null;
            if ('Notification' in window && Notification.permission === 'default') {
                sessionStorage.removeItem('bv_notif_dismissed');
                scheduleNotifPrompt(1200, true);
            }
        });

        if ('serviceWorker' in navigator) {
            // Listen for real-time Web Push messages relayed from sw.js while app is in foreground
            navigator.serviceWorker.addEventListener('message', (event) => {
                if (!event.data || event.data.type !== 'BV_PUSH_RECEIVED') return;
                const payload = event.data.payload || {};
                showNativeTopNotification({
                    id: payload.tag || `sw-${Date.now()}`,
                    title: payload.title,
                    body: payload.body,
                    url: payload.url,
                    icon: payload.icon
                });
                if (window.htmx) {
                    window.htmx.trigger(document.body, 'refreshBadge');
                }
            });

            const registerSw = () => {
                navigator.serviceWorker.register('/sw.js').then(() => {
                    if (!('Notification' in window)) return;
                    if (Notification.permission === 'granted') {
                        // Ensure subscription is active and linked to current user/session
                        const syncFlag = `bv_push_synced_${getCurrentUserKey()}`;
                        if (!sessionStorage.getItem(syncFlag)) {
                            subscribeAndSyncPushEndpoint(false);
                        }
                    } else if (Notification.permission === 'default') {
                        const isStandalone = (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) || window.navigator.standalone === true;
                        scheduleNotifPrompt(isStandalone ? 1200 : 3500);
                    }
                }).catch((err) => console.warn('SW registration warning:', err));
            };

            if (document.readyState === 'complete') {
                registerSw();
            } else {
                window.addEventListener('load', registerSw);
            }
        }
    }

    // Export public functions to window for inline template handlers
    window.syncCartBadges = syncCartBadges;
    window.showToast = showToast;
    window.showNativeTopNotification = showNativeTopNotification;
    window.updateActiveFiltersBar = updateActiveFiltersBar;
    window.syncFilterBtn = syncFilterBtn;
    window.toggleSearchInput = toggleSearchInput;
    window.handleSearchInput = handleSearchInput;
    window.clearSearchInput = clearSearchInput;
    window.resetCatalogFilterForm = resetCatalogFilterForm;
    window.openQuickViewModal = openQuickViewModal;
    window.closeQuickViewModal = closeQuickViewModal;
    window.openMobileSidebar = openMobileSidebar;
    window.closeMobileSidebar = closeMobileSidebar;
    window.toggleMobileSearch = toggleMobileSearch;
    window.toggleUserMenu = toggleUserMenu;
    window.toggleNotificationsMenu = toggleNotificationsMenu;
    window.dismissInstallBanner = dismissInstallBanner;
    window.scheduleNotifPrompt = scheduleNotifPrompt;
    window.showNotifPromptCard = showNotifPromptCard;
    window.hideNotifPromptCard = hideNotifPromptCard;
    window.dismissNotifPrompt = dismissNotifPrompt;
    window.requestPushPermission = requestPushPermission;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initGlobalListeners);
    } else {
        initGlobalListeners();
    }
})();
