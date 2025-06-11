(() => {
  // javascript/selectorHelper.js
  function getSmartSelector(el) {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return "";
    const preferAttr = (element) => {
      const attrPriority = ["id", "data-testid", "aria-label", "name", "placeholder", "title"];
      for (const attr of attrPriority) {
        const value = element.getAttribute(attr);
        if (value) return `[${attr}="${cssEscape(value)}"]`;
      }
      return null;
    };
    const tag = el.tagName.toLowerCase();
    if (tag === "button" || tag === "a") {
      const label = el.getAttribute("aria-label") || el.textContent.trim();
      if (label) return `${tag}:has-text("${label}")`;
    }
    const preferred = preferAttr(el);
    if (preferred) return preferred;
    const ancestor = el.closest('button, a, [role="button"], input[type="button"], div, span');
    if (ancestor && ancestor !== el) return getSmartSelector(ancestor);
    const path = [];
    let node = el;
    while (node && node !== document.body) {
      let segment = node.tagName.toLowerCase();
      const classList = [...node.classList].filter(
        (cls) => cls.length > 1 && !/^\d+$/.test(cls) && !cls.includes("ng-") && !cls.includes("jsx")
      );
      if (classList.length > 0) segment += "." + classList.join(".");
      const siblings = Array.from(node.parentNode?.children || []).filter((n) => n.tagName === node.tagName);
      if (siblings.length > 1) {
        const index = siblings.indexOf(node);
        segment += `:nth-of-type(${index + 1})`;
      }
      path.unshift(segment);
      node = node.parentNode;
    }
    return path.join(" > ");
  }
  function cssEscape(str) {
    return str.replace(/["\\]/g, "\\$&");
  }

  // javascript/recorder.js
  (function() {
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
      const selector = getSmartSelector(target);
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
              selector: getSmartSelector(lastTypedElement),
              timestamp: Date.now(),
              value: lastTypedElement.value
            });
            lastTypedElement = null;
          }
        }, 800);
      } else {
        window.sendEventToPython({
          action: type,
          selector,
          timestamp: now,
          value: target.value || void 0
        });
      }
    };
    const escapeQuotes = (str) => str.replace(/"/g, '\\"').replace(/'/g, "\\'");
    ["click", "focus", "blur", "change", "input", "mousedown"].forEach((type) => {
      document.addEventListener(type, sendEvent, true);
    });
    const notifyUrlChange = () => {
      if (typeof window.sendUrlChangeToPython === "function") {
        window.sendUrlChangeToPython(window.location.href);
      }
    };
    new MutationObserver(notifyUrlChange).observe(document.body, {
      childList: true,
      subtree: true
    });
    const patchHistory = (method) => {
      const original = history[method];
      history[method] = function(...args) {
        original.apply(this, args);
        notifyUrlChange();
      };
    };
    patchHistory("pushState");
    patchHistory("replaceState");
    window.addEventListener("popstate", notifyUrlChange);
    notifyUrlChange();
  })();
})();
