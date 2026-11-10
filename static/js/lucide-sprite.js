(function () {
  const script = document.currentScript;
  const spriteUrl = script?.dataset.spriteUrl || '/static/icons/lucide-sprite.svg';
  const svgNs = 'http://www.w3.org/2000/svg';
  const xlinkNs = 'http://www.w3.org/1999/xlink';

  function createIcons(root = document) {
    if (!root || typeof root.querySelectorAll !== 'function') return;
    root.querySelectorAll('i[data-lucide], svg[data-lucide]').forEach((source) => {
      const name = source.getAttribute('data-lucide');
      if (!name || !/^[a-z0-9-]+$/i.test(name)) return;

      const icon = document.createElementNS(svgNs, 'svg');
      for (const attribute of source.attributes) {
        if (attribute.name !== 'data-lucide') {
          icon.setAttribute(attribute.name, attribute.value);
        }
      }
      icon.setAttribute('data-lucide', name);
      icon.setAttribute('viewBox', '0 0 24 24');
      icon.setAttribute('fill', 'none');
      icon.setAttribute('stroke', 'currentColor');
      icon.setAttribute('stroke-width', source.getAttribute('stroke-width') || '2');
      icon.setAttribute('stroke-linecap', 'round');
      icon.setAttribute('stroke-linejoin', 'round');
      icon.setAttribute('focusable', 'false');
      if (!icon.hasAttribute('aria-label') && !icon.hasAttribute('role')) {
        icon.setAttribute('aria-hidden', 'true');
      }

      const use = document.createElementNS(svgNs, 'use');
      const href = `${spriteUrl}#${encodeURIComponent(name)}`;
      use.setAttribute('href', href);
      use.setAttributeNS(xlinkNs, 'xlink:href', href);
      icon.appendChild(use);
      source.replaceWith(icon);
    });
  }

  window.lucide = { createIcons };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => createIcons(), { once: true });
  } else {
    createIcons();
  }
})();
