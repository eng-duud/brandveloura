/* ==============================================================================
   Brand Veloura - Admin Gift Bundle Product Picker Interactive Script
   ============================================================================== */

document.addEventListener('DOMContentLoaded', function () {
    const container = document.getElementById('id_bundle_products');
    if (!container) return;

    // 1. Create Toolbar (Search input + Select All / Deselect All buttons)
    const toolbar = document.createElement('div');
    toolbar.className = 'bundle-picker-toolbar';

    const searchInput = document.createElement('input');
    searchInput.type = 'text';
    searchInput.className = 'bundle-picker-search';
    searchInput.placeholder = '🔍 ابحث عن عطر أو ساعة أو منتج للتحديد...';

    const actionsDiv = document.createElement('div');
    actionsDiv.className = 'bundle-picker-actions';

    const countBadge = document.createElement('span');
    countBadge.style.fontSize = '12px';
    countBadge.style.fontWeight = 'bold';
    countBadge.style.color = '#be185d';
    countBadge.style.marginRight = '8px';

    const selectAllBtn = document.createElement('button');
    selectAllBtn.type = 'button';
    selectAllBtn.className = 'bundle-picker-btn';
    selectAllBtn.innerText = '☑ تحديد الكل';

    const deselectAllBtn = document.createElement('button');
    deselectAllBtn.type = 'button';
    deselectAllBtn.className = 'bundle-picker-btn';
    deselectAllBtn.innerText = '☐ إلغاء التحديد';

    actionsDiv.appendChild(countBadge);
    actionsDiv.appendChild(selectAllBtn);
    actionsDiv.appendChild(deselectAllBtn);

    toolbar.appendChild(searchInput);
    toolbar.appendChild(actionsDiv);

    // Insert toolbar right before the checkbox grid
    container.parentNode.insertBefore(toolbar, container);

    function updateCount() {
        const checked = container.querySelectorAll('input[type="checkbox"]:checked');
        countBadge.innerText = `تم اختيار ${checked.length} منتجات`;
    }

    // Update active class on label when checkbox toggles
    function syncLabelClasses() {
        container.querySelectorAll('label').forEach(label => {
            const cb = label.querySelector('input[type="checkbox"]');
            if (cb && cb.checked) {
                label.classList.add('is-checked');
            } else {
                label.classList.remove('is-checked');
            }
        });
        updateCount();
    }

    container.addEventListener('change', syncLabelClasses);

    // Live Search Filter
    searchInput.addEventListener('input', function () {
        const query = this.value.trim().toLowerCase();
        container.querySelectorAll('label').forEach(label => {
            const text = label.textContent.toLowerCase();
            const parent = label.closest('div') || label;
            if (text.includes(query)) {
                parent.style.display = '';
            } else {
                parent.style.display = 'none';
            }
        });
    });

    // Select All (visible items)
    selectAllBtn.addEventListener('click', function () {
        container.querySelectorAll('label').forEach(label => {
            const parent = label.closest('div') || label;
            if (parent.style.display !== 'none') {
                const cb = label.querySelector('input[type="checkbox"]');
                if (cb) cb.checked = true;
            }
        });
        syncLabelClasses();
    });

    // Deselect All
    deselectAllBtn.addEventListener('click', function () {
        container.querySelectorAll('input[type="checkbox"]').forEach(cb => {
            cb.checked = false;
        });
        syncLabelClasses();
    });

    syncLabelClasses();
});

