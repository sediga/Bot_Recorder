export function getSmartSelector(el) {
  if (!el || el.nodeType !== Node.ELEMENT_NODE) return '';

  // Prioritize meaningful attributes
  const preferAttr = (element) => {
    const attrPriority = ['id', 'data-testid', 'aria-label', 'name', 'placeholder', 'title'];
    for (const attr of attrPriority) {
      const value = element.getAttribute(attr);
      if (value) return `[${attr}="${cssEscape(value)}"]`;
    }
    return null;
  };

  // Prefer text for buttons/links
  const tag = el.tagName.toLowerCase();
  if (tag === 'button' || tag === 'a') {
    const label = el.getAttribute('aria-label') || el.textContent.trim();
    if (label) return `${tag}:has-text("${label}")`;
  }

  // Check preferred attributes
  const preferred = preferAttr(el);
  if (preferred) return preferred;

  // Walk up for the nearest uniquely identifiable ancestor
  const ancestor = el.closest('button, a, [role="button"], input[type="button"], div, span');
  if (ancestor && ancestor !== el) return getSmartSelector(ancestor);

  // Fallback to class-based DOM path (excluding auto-generated)
  const path = [];
  let node = el;
  while (node && node !== document.body) {
    let segment = node.tagName.toLowerCase();

    // Filter classes to avoid dynamic ones
    const classList = [...node.classList].filter(cls =>
      cls.length > 1 && !/^\d+$/.test(cls) && !cls.includes('ng-') && !cls.includes('jsx')
    );
    if (classList.length > 0) segment += '.' + classList.join('.');

    // Add :nth-of-type if siblings with same tag exist
    const siblings = Array.from(node.parentNode?.children || []).filter(n => n.tagName === node.tagName);
    if (siblings.length > 1) {
      const index = siblings.indexOf(node);
      segment += `:nth-of-type(${index + 1})`;
    }

    path.unshift(segment);
    node = node.parentNode;
  }

  return path.join(' > ');
}

function cssEscape(str) {
  return str.replace(/["\\]/g, '\\$&');
}
