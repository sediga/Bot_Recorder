import { getAllAttributes } from "./domanalyser";

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

function isSkippable(el) {
  const skipTags = ['BODY', 'HTML', 'MAIN'];
  const skipClassPatterns = [/^min-h-screen$/, /^bg-/, /^text-/];
  if (!el || skipTags.includes(el.tagName)) return true;
  const classes = Array.from(el.classList);
  return classes.some(cls => skipClassPatterns.some(p => p.test(cls)));
}

function isLikelyDynamicId(id) {
  return id && id.length > 12 && /[A-Z]/.test(id) && /\d/.test(id);
}

function climbToClickable(el) {
  while (el && el !== document.body && !isClickable(el)) {
    if (isSkippable(el)) break;
    el = el.parentElement;
  }
  return el;
}

function isLikelyGeneratedId(id) {
  if (!id || id.length < 6) return false;
  if (id.length > 16) return true;
  if (/^[A-Za-z0-9_-]{10,}$/.test(id)) {
    const hasMixedCase = /[a-z]/.test(id) && /[A-Z]/.test(id);
    const hasNumbers = /\d/.test(id);
    return hasMixedCase && hasNumbers;
  }
  return false;
}

export function getSmartSelector(el) {
  if (!el || el === document || el.nodeType !== 1) return '';

  // Handle span asterisks like * (required)
  if (el.tagName === 'SPAN' && el.textContent.trim() === '*') {
    const label = el.closest('label');
    if (label?.htmlFor) return `#${CSS.escape(label.htmlFor)}`;
    const input = el.closest('div')?.querySelector('input, textarea, select');
    if (input) return getSmartSelector(input);
  }

  // Handle label with for attr
  if (el.tagName === 'LABEL' && el.htmlFor) {
    return `#${CSS.escape(el.htmlFor)}`;
  }

  // Handle containers wrapping form fields
  if (['DIV', 'SPAN'].includes(el.tagName)) {
    const labeled = el.querySelector('label[for]');
    if (labeled) {
      const input = document.getElementById(labeled.htmlFor);
      if (input) return getSmartSelector(input);
    }
    const input = el.querySelector('input, textarea, select');
    if (input) return getSmartSelector(input);
  }

  const isFormField = el.matches('input, textarea, select');
  const targetEl = isFormField ? el : (climbToClickable(el) || el);
  const tag = targetEl.tagName.toLowerCase();
  const text = getVisibleText(targetEl);

  // Prioritize stable attributes
  if (targetEl.getAttribute('data-testid')) {
    return `[data-testid="${CSS.escape(targetEl.getAttribute('data-testid'))}"]`;
  }

  // ✅ Enhanced: Context-aware [aria-label]
  const ariaLabel = targetEl.getAttribute('aria-label');
  if (ariaLabel) {
    const columnHeader = targetEl.closest('div[role="columnheader"][data-field]');
    if (columnHeader) {
      const dataField = columnHeader.getAttribute('data-field');
      return `div[role="columnheader"][data-field="${CSS.escape(dataField)}"] [aria-label="${CSS.escape(ariaLabel)}"]`;
    }
    return `[aria-label="${CSS.escape(ariaLabel)}"]`;
  }

  if (targetEl.id && !isLikelyGeneratedId(targetEl.id)) {
    return `#${CSS.escape(targetEl.id)}`;
  }
  if (targetEl.name) {
    return `[name="${CSS.escape(targetEl.name)}"]`;
  }
  if (targetEl.placeholder) {
    return `[placeholder="${CSS.escape(targetEl.placeholder)}"]`;
  }

  // ✅ DataGrid column header support
  if (
    targetEl.getAttribute('role') === 'columnheader' &&
    targetEl.hasAttribute('data-field')
  ) {
    return `div[role="columnheader"][data-field="${CSS.escape(
      targetEl.getAttribute('data-field')
    )}"]`;
  }

  // Text-based selectors
  if (tag === 'button' && text) return `button:has-text("${text}")`;
  if (tag === 'a' && text) return `a:has-text("${text}")`;

  const type = targetEl.getAttribute('type');
  const role = targetEl.getAttribute('role');
  if (tag === 'input' && type === 'button' && targetEl.value)
    return `input[type="button"][value="${CSS.escape(targetEl.value)}"]`;
  if ((role === 'button' || role === 'link') && text)
    return `[role="${CSS.escape(role)}"]:has-text("${text}")`;

  // Fallback class-based
  const classes = Array.from(targetEl.classList).filter(cls =>
    /^[a-zA-Z0-9_-]+$/.test(cls)
  );
  let classSelector = '';
  if (classes.length) {
    classSelector = '.' + classes.slice(0, 3).map(CSS.escape).join('.');
  }

  let selector = `${tag}${classSelector}`;
  if (text) selector += `:has-text("${text}")`;

  // Disambiguate by index
  const matches = Array.from(document.querySelectorAll(tag));
  const matchingSiblings = matches.filter(node =>
    node.textContent?.includes(text)
  );
  if (matchingSiblings.length > 1) {
    const index = matchingSiblings.indexOf(targetEl);
    if (index >= 0) selector += `:nth-of-type(${index + 1})`;
  }

  if (selector.startsWith('body:has-text("*")')) return '';

  return selector;
}

export function getDevtoolsLikeSelector(el) {
  if (!(el instanceof Element)) return "";

  const parts = [];
  while (el && el.nodeType === Node.ELEMENT_NODE) {
    let part = el.nodeName.toLowerCase();

    if (el.id) {
      part = `#${CSS.escape(el.id)}`;
      parts.unshift(part);
      break;
    } else {
      const className = (el.className || "").toString().trim().replace(/\s+/g, ".");
      if (className) {
        part += "." + className.replace(/^\.+/, "");
      }
    }

    const parent = el.parentNode;
    if (parent) {
      const siblings = Array.from(parent.children).filter(child => child.tagName === el.tagName);
      if (siblings.length > 1) {
        const index = siblings.indexOf(el) + 1;
        part += `:nth-child(${index})`;
      }
    }

    parts.unshift(part);
    el = el.parentNode;
  }

  return parts.join(" > ");
}

export function captureSelectors(el) {
  if (!el || el.nodeType !== 1) return null;

  const smartSelector = getSmartSelector(el);
  const devtoolsSelector = getDevtoolsLikeSelector(el);
  const attributes = getAllAttributes(el);
  const text = el.innerText?.trim() || "";
  const rect = el.getBoundingClientRect();

  const selectors = [];

  if (smartSelector) selectors.push({ strategy: "smart", selector: smartSelector });
  if (attributes["data-testid"]) {
    selectors.push({ strategy: "testid", selector: `[data-testid="${CSS.escape(attributes["data-testid"])}"]` });
  }
  if (attributes["id"] && !isLikelyGeneratedId(attributes["id"])) {
    selectors.push({ strategy: "id", selector: `#${CSS.escape(attributes["id"])}` });
  }
  if (attributes["name"]) {
    selectors.push({ strategy: "name", selector: `[name="${CSS.escape(attributes["name"])}"]` });
  }
  if (attributes["aria-label"]) {
    selectors.push({ strategy: "aria", selector: `[aria-label="${CSS.escape(attributes["aria-label"])}"]` });
  }
  if (devtoolsSelector) {
    selectors.push({ strategy: "devtools", selector: devtoolsSelector });
  }

  return {
    selectors, // prioritized array
    smartSelector,
    devtoolsSelector,
    attributes,
    boundingBox: {
      x: rect.x,
      y: rect.y,
      width: rect.width,
      height: rect.height
    },
    text
  };
}

window.getSmartSelectorLib = {
  getSmartSelector,
  getDevtoolsLikeSelector
  // include any other helpers here
};
