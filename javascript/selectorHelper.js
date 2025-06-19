
function getVisibleText(el) {
  if (!el || !el.textContent) return '';
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null);
  const texts = new Set();
  while (walker.nextNode()) {
    const text = walker.currentNode.textContent.trim().replace(/\s+/g, ' ');
    if (text && text.length < 100) texts.add(text);
  }
  return Array.from(texts).join(' ').trim().replace(/["']/g, '');
}

export function getSmartSelector(el) {
  if (!el || el === document || el.nodeType !== 1) return '';

  const interactiveAncestor = el.closest('button, [role="button"], a, input[type="button"], [tabindex]');
  const targetEl = interactiveAncestor || el;

  // Stable attributes
  if (targetEl.id) return `#${CSS.escape(targetEl.id)}`;
  if (targetEl.name) return `[name="${CSS.escape(targetEl.name)}"]`;
  if (targetEl.getAttribute('data-testid')) return `[data-testid="${CSS.escape(targetEl.getAttribute('data-testid'))}"]`;
  if (targetEl.getAttribute('aria-label')) return `[aria-label="${CSS.escape(targetEl.getAttribute('aria-label'))}"]`;
  if (targetEl.placeholder) return `[placeholder="${CSS.escape(targetEl.placeholder)}"]`;

  const tag = targetEl.tagName.toLowerCase();
  const type = targetEl.getAttribute('type');
  const role = targetEl.getAttribute('role');
  const text = getVisibleText(targetEl);

  // Buttons
  if (tag === 'button' && text) return `button:has-text("${text}")`;
  if (tag === 'input' && type === 'button' && targetEl.value)
    return `input[type="button"][value="${CSS.escape(targetEl.value)}"]`;

  if ((role === 'button' || role === 'link') && text)
    return `[role="${CSS.escape(role)}"]:has-text("${text}")`;

  if (tag === 'a' && text) return `a:has-text("${text}")`;

  if (
    ['span', 'div', 'p', 'strong', 'li', 'label'].includes(tag) &&
    text?.length > 0 &&
    text.length < 100
  ) {
    return `${tag}:has-text("${text}")`;
  }

  // Fallback: DOM path
  const path = [];
  let elWalker = targetEl;
  while (elWalker && elWalker.nodeType === 1 && elWalker !== document.body) {
    let selector = elWalker.tagName.toLowerCase();
    const classes = [...elWalker.classList].filter(cls => !/^\d+$/.test(cls));
    if (classes.length) selector += '.' + classes.map(CSS.escape).join('.');
    const siblings = Array.from(elWalker.parentNode.children).filter(
      sibling => sibling.tagName === elWalker.tagName
    );
    if (siblings.length > 1) selector += `:nth-of-type(${siblings.indexOf(elWalker) + 1})`;
    path.unshift(selector);
    elWalker = elWalker.parentNode;
  }

  return path.join(' > ');
}
