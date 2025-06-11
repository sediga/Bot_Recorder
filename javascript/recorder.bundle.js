(() => {
  // javascript/selectorHelper.js
  function getSmartSelector(el) {
    if (!el || el === document || el.nodeType !== 1) return "";
    const interactiveAncestor = el.closest('button, [role="button"], a, input[type="button"], [tabindex]');
    const targetEl = interactiveAncestor || el;
    if (targetEl.id) return `#${CSS.escape(targetEl.id)}`;
    if (targetEl.name) return `[name='${CSS.escape(targetEl.name)}']`;
    if (targetEl.getAttribute("data-testid"))
      return `[data-testid='${CSS.escape(targetEl.getAttribute("data-testid"))}']`;
    if (targetEl.getAttribute("aria-label"))
      return `[aria-label='${CSS.escape(targetEl.getAttribute("aria-label"))}']`;
    if (targetEl.placeholder) return `[placeholder='${CSS.escape(targetEl.placeholder)}']`;
    const tag = targetEl.tagName.toLowerCase();
    const type = targetEl.getAttribute("type");
    const role = targetEl.getAttribute("role");
    const text = targetEl.textContent.trim().replace(/\s+/g, " ").replace(/["']/g, "");
    if (tag === "button" && text) return `button:has-text("${text}")`;
    if (tag === "input" && type === "button" && targetEl.value)
      return `input[type="button"][value="${CSS.escape(targetEl.value)}"]`;
    if ((role === "button" || role === "link") && text)
      return `[role='${role}']:has-text("${text}")`;
    if (tag === "a" && text) return `a:has-text("${text}")`;
    if (["span", "div", "p", "strong", "li", "label"].includes(tag) && text.length > 0 && text.length < 100) {
      return `${tag}:has-text("${text}")`;
    }
    const path = [];
    let elWalker = targetEl;
    while (elWalker && elWalker.nodeType === 1 && elWalker !== document.body) {
      let selector = elWalker.tagName.toLowerCase();
      const classes = [...elWalker.classList].filter((cls) => !/^\d+$/.test(cls));
      if (classes.length) selector += "." + classes.map((c) => CSS.escape(c)).join(".");
      const siblings = Array.from(elWalker.parentNode.children).filter(
        (sibling) => sibling.tagName === elWalker.tagName
      );
      if (siblings.length > 1) selector += `:nth-of-type(${siblings.indexOf(elWalker) + 1})`;
      path.unshift(selector);
      elWalker = elWalker.parentNode;
    }
    return path.join(" > ");
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
