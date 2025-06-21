import { getSmartSelector } from './selectorHelper.js';
import { getAllAttributes } from './domanalyser.js';

(function () {
  if (window.__recorderInjected) return;
  window.__recorderInjected = true;
  console.log("[Botflows] Recorder script injected successfully");

  let lastClick = { selector: null, timestamp: 0 };
  let lastFocus = { selector: null, timestamp: 0 };

  const sendEvent = (event, override = {}) => {
    const original = event.target;
    const target =
      original.closest('a, button, input[type="button"], [role="button"]') || original;
    const type = event.type;

    // 💡 Skip invalid targets
    if (
      !target ||
      target === document ||
      target === document.body ||
      !document.contains(target) ||
      typeof window.sendEventToPython !== "function"
    ) {
      return;
    }

    const selector = getSmartSelector(target);
    const now = Date.now();

    // ⏱ Skip duplicate clicks within 80ms
    if (type === "click" && selector === lastClick.selector && now - lastClick.timestamp < 80)
      return;

    // 🎯 Only record focus for form fields
    if (type === "focus") {
      const tag = target.tagName.toLowerCase();
      if (!["input", "textarea", "select"].includes(tag)) return;
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

    // 🔁 Stream to all consumers
    window.sendEventToPython(actionData);
    window.parent.postMessage({ type: "recorded-event", data: actionData }, "*");
    fetch("http://localhost:8000/api/stream_action", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(actionData)
    });

    // 🪵 Optional click insight logging
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
          attributes: getAllAttributes(target),
          innerText: target.innerText?.trim(),
          parentTag,
          siblingText
        },
        timestamp: new Date().toISOString(),
        pageUrl: window.location.href
      });
    }
  };

  // 👂 Core interaction listeners
  ["click", "focus", "change"].forEach(type => {
    document.addEventListener(type, sendEvent, true);
  });

  // ✅ Record final input value only once on blur (user finishes typing)
  document.addEventListener("blur", (event) => {
    const target = event.target;
    if (!target.matches("input, textarea, select")) return;

    sendEvent(event, {
      action: "type",
      value: target.value
    });
  }, true);

  // 🔁 URL tracking helpers
  const notifyUrlChange = () => {
    if (typeof window.sendUrlChangeToPython === "function") {
      window.sendUrlChangeToPython(window.location.href);
    }
  };

  const waitForBodyAndObserve = () => {
    if (document.body) {
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
      notifyUrlChange();
    };
  };

  window.addEventListener("popstate", notifyUrlChange);
  notifyUrlChange();
  patchHistory("pushState");
  patchHistory("replaceState");
})();
