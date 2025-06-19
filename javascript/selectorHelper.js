function getVisibleText(el) {
  if (!el || !el.textContent) return '';
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null);
  const texts = [];
  while (walker.nextNode()) {
    const text = walker.currentNode.textContent.trim().replace(/\s+/g, ' ');
    if (text && text.length < 100) texts.push(text);
  }

  if (texts.length === 0) return '';
  const sorted = texts.sort((a, b) => a.length - b.length);
  return sorted[0].replace(/["']/g, '');
}

function isClickable(el) {
  const tag = el.tagName.toLowerCase();
  const role = el.getAttribute('role') || '';
  const classes = Array.from(el.classList).join(' ').toLowerCase();
  return (
    ['a', 'button'].includes(tag) ||
    ['button', 'link'].includes(role) ||
    el.hasAttribute('onclick') ||
    el.hasAttribute('tabindex') ||
    /cursor-pointer|clickable|btn|card|link|action|nav/i.test(classes)
  );
}

function climbToClickable(el) {
  while (el && el !== document.body && !isClickable(el)) {
    el = el.parentElement;
  }
  return el;
}

export function getSmartSelector(el) {
  if (!el || el === document || el.nodeType !== 1) return '';

  const targetEl = climbToClickable(el) || el;
  const tag = targetEl.tagName.toLowerCase();
  const text = getVisibleText(targetEl);

  if (targetEl.id) return `#${CSS.escape(targetEl.id)}`;
  if (targetEl.name) return `[name="${CSS.escape(targetEl.name)}"]`;
  if (targetEl.getAttribute('data-testid')) return `[data-testid="${CSS.escape(targetEl.getAttribute('data-testid'))}"]`;
  if (targetEl.getAttribute('aria-label')) return `[aria-label="${CSS.escape(targetEl.getAttribute('aria-label'))}"]`;
  if (targetEl.placeholder) return `[placeholder="${CSS.escape(targetEl.placeholder)}"]`;

  // Semantic shortcut
  if (tag === 'button' && text) return `button:has-text("${text}")`;
  if (tag === 'a' && text) return `a:has-text("${text}")`;
  const type = targetEl.getAttribute('type');
  const role = targetEl.getAttribute('role');
  if (tag === 'input' && type === 'button' && targetEl.value)
    return `input[type="button"][value="${CSS.escape(targetEl.value)}"]`;
  if ((role === 'button' || role === 'link') && text)
    return `[role="${CSS.escape(role)}"]:has-text("${text}")`;

  // Build class-based selector
  const classes = Array.from(targetEl.classList).filter(cls =>
    /^[a-zA-Z0-9_-]+$/.test(cls)
  );
  let classSelector = '';
  if (classes.length) {
    classSelector = '.' + classes.slice(0, 3).map(CSS.escape).join('.');
  }

  let selector = `${tag}${classSelector}`;
  if (text) {
    selector += `:has-text("${text}")`;
  }

  // ✅ Disambiguate if needed
  const matches = Array.from(document.querySelectorAll(tag));
  const matchingSiblings = matches.filter(node =>
    node.textContent?.includes(text)
  );
  if (matchingSiblings.length > 1) {
    const index = matchingSiblings.indexOf(targetEl);
    if (index >= 0) {
      selector += `:nth-of-type(${index + 1})`;
    }
  }

  return selector;
}
