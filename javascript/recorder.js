import { getAllAttributes } from './domanalyser.js';

(function () {
  console.debug("[Botflows] Recorder script starting execution...");
  if (window.__recorderInjected) {
    console.debug(`[Botflows] Recorder already injected at ${window.__recorderInjectedTime}, skipping.`);
    return;
  }
  window.__recorderInjected = true;
  window.__recorderInjectedTime = new Date().toISOString();
  console.debug("[Botflows] Recorder script injected successfully");

  let lastClick = { selector: null, timestamp: 0 };
  let lastFocus = { selector: null, timestamp: 0 };

  const getSmartSelector = window.getSmartSelectorLib.getSmartSelector;
  const isInPickMode = () => window.__pickModeActive === true;

  const sendEvent = (event, override = {}) => {
    if (isInPickMode()) {
      console.debug("[Botflows] In pick mode — event suppressed:", event.type);
      return;
    }

    const original = event.target;
    const target =
      original.closest('a, button, input[type="button"], [role="button"]') || original;
    const type = event.type;

    if (
      !target ||
      target === document ||
      target === document.body ||
      !document.contains(target) ||
      typeof window.sendEventToPython !== "function"
    ) {
      console.debug("[Botflows] Ignoring untrackable target:", target);
      return;
    }

    const selector = getSmartSelector(target);
    const now = Date.now();

    if (type === "click" && selector === lastClick.selector && now - lastClick.timestamp < 80) {
      console.debug("[Botflows] Suppressed duplicate click:", selector);
      return;
    }

    if (type === "focus") {
      const tag = target.tagName.toLowerCase();
      if (!["input", "textarea", "select"].includes(tag)) {
        console.debug("[Botflows] Ignored focus event on non-input element:", tag);
        return;
      }
    }

    if (type === "click") lastClick = { selector, timestamp: now };
    if (type === "focus") lastFocus = { selector, timestamp: now };

    const actionData = {
      action: type === "input" ? "type" : type,
      selector,
      timestamp: now,
      value: target.value || null,
      url: window.location.href,
      tagName: target.tagName || null,
      classList: Array.from(target.classList || []),
      attributes: getAllAttributes(target),
      innerText: target.innerText || null,
      elementText: target.textContent || null,
      ...override
    };

    console.debug("[Botflows] Event recorded:", actionData);

    window.sendEventToPython(actionData);
    window.parent.postMessage({ type: "recorded-event", data: actionData }, "*");

    if (type === "click" && typeof window.sendLogToPython === "function") {
      const parentTag = target.parentElement?.tagName?.toLowerCase() || null;
      const siblingText = Array.from(target.parentElement?.children || [])
        .filter(sib => sib !== target)
        .map(sib => sib.innerText.trim())
        .filter(Boolean);

      const logData = {
        event: "click",
        selector,
        elementMeta: {
          tag: target.tagName.toLowerCase(),
          attributes: getAllAttributes(target),
          innerText: target.innerText?.trim(),
          parentTag,
          siblingText
        },
        timestamp: new Date().toISOString(),
        pageUrl: window.location.href
      };

      console.debug("[Botflows] Sending log to Python:", logData);
      window.sendLogToPython(logData);
    }
  };

  ["click", "focus", "change"].forEach(type => {
    document.addEventListener(type, sendEvent, true);
    console.debug(`[Botflows] Event listener attached for ${type}`);
  });

  document.addEventListener("blur", (event) => {
    if (isInPickMode()) {
      console.debug("[Botflows] Blur event suppressed in pick mode");
      return;
    }

    const target = event.target;
    if (!target.matches("input, textarea, select")) return;

    console.debug("[Botflows] Blur captured as type event");
    sendEvent(event, {
      action: "type",
      value: target.value
    });
  }, true);

  let lastKnownUrl = window.location.href;

  const notifyUrlChange = () => {
    const currentUrl = window.location.href;
    if (
      currentUrl !== lastKnownUrl &&
      typeof window.sendUrlChangeToPython === "function"
    ) {
      lastKnownUrl = currentUrl;
      console.debug("[Botflows] Detected SPA URL change:", currentUrl);
      window.sendUrlChangeToPython(currentUrl);
    }
  };

  const waitForBodyAndObserve = () => {
    if (document.body) {
      console.debug("[Botflows] Setting up mutation observer for body");
      new MutationObserver(notifyUrlChange).observe(document.body, {
        childList: true,
        subtree: true,
      });
    } else {
      setTimeout(waitForBodyAndObserve, 100);
    }
  };

  waitForBodyAndObserve();

  const patchHistory = (method) => {
    const original = history[method];
    history[method] = function (...args) {
      original.apply(this, args);
      console.debug(`[Botflows] Intercepted history.${method}`);
      notifyUrlChange();
    };
  };

  window.addEventListener("popstate", notifyUrlChange);
  notifyUrlChange();
  patchHistory("pushState");
  patchHistory("replaceState");
})();
