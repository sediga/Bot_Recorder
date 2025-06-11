(function () {
  if (window.__recorderInjected) return;
  window.__recorderInjected = true;

  let typingDebounce;
  let lastTypedElement = null;
  let lastClick = { selector: null, timestamp: 0 };
  let lastFocus = { selector: null, timestamp: 0 };

  const sendEvent = (event) => {
    const original = event.target;
    const target = original.closest('a, button, input[type="button"], [role="button"]') || original;
    const type = event.type;

    if (!target || typeof window.sendEventToPython !== "function") return;

    const selector = generateSmartSelector(target);
    const now = Date.now();

    if (type === "click") {
      if (selector === lastClick.selector && now - lastClick.timestamp < 150) return;
      lastClick = { selector, timestamp: now };
    }

    if (type === "focus") {
      if (selector === lastFocus.selector && now - lastFocus.timestamp < 150) return;
      lastFocus = { selector, timestamp: now };
    }

    if (type === "input" && (target.tagName === "INPUT" || target.tagName === "TEXTAREA")) {
      clearTimeout(typingDebounce);
      lastTypedElement = target;
      typingDebounce = setTimeout(() => {
        if (lastTypedElement) {
          window.sendEventToPython({
            action: "type",
            selector: generateSmartSelector(lastTypedElement),
            timestamp: Date.now(),
            value: lastTypedElement.value,
          });
          lastTypedElement = null;
        }
      }, 800);
    } else {
      window.sendEventToPython({
        action: type,
        selector,
        timestamp: now,
        value: target.value || undefined,
      });
    }
  };

  const escapeQuotes = (str) => str.replace(/"/g, '\\"').replace(/'/g, "\\'");

  const generateSmartSelector = (el) => {
    if (!el || el === document) return "";

    const clickable = el.closest("button, [role='button'], a, input[type='button']");
    const target = clickable || el;

    if (target.id) return `#${target.id}`;

    if (target.tagName?.toLowerCase() === 'a' && target.getAttribute('aria-label')) {
      return `a[aria-label='${escapeQuotes(target.getAttribute('aria-label'))}']`;
    }

    if (target.name) return `[name='${escapeQuotes(target.name)}']`;
    if (target.getAttribute("data-testid"))
      return `[data-testid='${escapeQuotes(target.getAttribute("data-testid"))}']`;
    if (target.getAttribute("aria-label"))
      return `[aria-label='${escapeQuotes(target.getAttribute("aria-label"))}']`;
    if (target.placeholder)
      return `[placeholder='${escapeQuotes(target.placeholder)}']`;

    const tag = target.tagName?.toLowerCase();

    if (tag?.toLowerCase() === "button") {
      const label = target.getAttribute("aria-label") || target.textContent.trim();
      return `button:has-text("${escapeQuotes(label)}")`;
    }

    if (tag?.toLowerCase() === "input" && target.type?.toLowerCase() === "button") {
      return `input[type="button"][value='${escapeQuotes(target.value)}']`;
    }

    const role = target.getAttribute("role");
    const label = target.getAttribute("aria-label") || target.textContent.trim();
    if ((role?.toLowerCase() === "button" || role?.toLowerCase() === "link") && label) {
      return `[role='${escapeQuotes(role)}']:has-text("${escapeQuotes(label)}")`;
    }

    // Try meaningful class name selector before fallback
    const classList = [...target.classList]
      .filter(cls => !/^\d+$/.test(cls) && /^[A-Za-z0-9_-]+$/.test(cls)); // only safe class names

    if (classList.length) {
      console.log("Using class selector:", classList);
      const classSelector = '.' + classList.join('.');
      const matches = document.querySelectorAll(classSelector);
      if (matches.length === 1) {
        return classSelector; // Unique enough, use it
      }
    }
    // Fallback: DOM path with filtered classnames
    const path = [];
    let elWalker = target;
    while (elWalker && elWalker.nodeType === Node.ELEMENT_NODE && elWalker !== document.body) {
      let part = elWalker.nodeName.toLowerCase();
      const classList = [...elWalker.classList].filter(cls => !/^\d+$/.test(cls));
      if (classList.length) part += '.' + classList.join('.');
      const siblings = Array.from(elWalker.parentNode.children)
        .filter(n => n.nodeName === elWalker.nodeName);
      if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(elWalker) + 1})`;
      path.unshift(part);
      elWalker = elWalker.parentNode;
    }

    return path.join(" > ");
  };

  ["click", "focus", "blur", "change", "input", 'mousedown'].forEach(type => {
    document.addEventListener(type, sendEvent, true);
  });

  const notifyUrlChange = () => {
    if (typeof window.sendUrlChangeToPython === "function") {
      window.sendUrlChangeToPython(window.location.href);
    }
  };

  new MutationObserver(notifyUrlChange).observe(document.body, {
    childList: true,
    subtree: true,
  });

  const patchHistory = (method) => {
    const original = history[method];
    history[method] = function (...args) {
      original.apply(this, args);
      notifyUrlChange();
    };
  };

  patchHistory("pushState");
  patchHistory("replaceState");
  window.addEventListener("popstate", notifyUrlChange);
  notifyUrlChange();
})();
