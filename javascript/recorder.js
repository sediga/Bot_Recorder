import { getSmartSelector } from './selectorHelper.js';

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
    
      // 🧠 New: Send selector metadata for training AI model
    if (type === "click" && typeof window.sendLogToPython === "function") {
      const parentTag = target.parentElement?.tagName?.toLowerCase() || null;
      const siblingText = Array.from(target.parentElement?.children || [])
        .filter(sib => sib !== target)
        .map(sib => sib.innerText.trim())
        .filter(Boolean);

      window.sendLogToPython({
        event: "click",
        selector,
        elementMeta: {
          tag: target.tagName.toLowerCase(),
          attributes: getAttributes(target),
          innerText: target.innerText.trim(),
          parentTag,
          siblingText
        },
        timestamp: new Date().toISOString(),
        pageUrl: window.location.href
      });
    }
  };

  const escapeQuotes = (str) => str.replace(/"/g, '\\"').replace(/'/g, "\\'");

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

function getAttributes(el) {
  const attrs = {};
  for (let attr of el.attributes) {
    attrs[attr.name] = attr.value;
  }
  return attrs;
}
