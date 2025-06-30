import { captureSelectors } from './selectorHelper.js';

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

  const isInPickMode = () => window.__pickModeActive === true;

  function showValidationOverlay() {
    if (document.getElementById("__botflows_validation_overlay")) return;

    const overlay = document.createElement("div");
    overlay.id = "__botflows_validation_overlay";
    Object.assign(overlay.style, {
      position: "fixed",
      top: 0,
      left: 0,
      width: "100vw",
      height: "100vh",
      backgroundColor: "rgba(255, 255, 255, 0.6)",
      zIndex: 999999,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      fontSize: "22px",
      fontFamily: "sans-serif",
      fontWeight: "bold",
      color: "#333"
    });
    overlay.innerText = "Validating action… Please wait";
    document.body.appendChild(overlay);
  }

  function hideValidationOverlay() {
    const el = document.getElementById("__botflows_validation_overlay");
    if (el) el.remove();
  }
  window.hideValidationOverlay = hideValidationOverlay;


  const sendEvent = (event, override = {}) => {
    if (isInPickMode()) {
      console.debug("[Botflows] In pick mode — event suppressed:", event.type);
      return;
    }

    if (window.__pendingValidation) {
      console.debug("[Botflows] Skipping event while previous validation is pending");
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

    const meta = captureSelectors(target);
    if (!meta || !meta.selectors?.length) return;

    const now = Date.now();
    const primarySelector = meta.selectors[0].selector;

    if (type === "click" && primarySelector === lastClick.selector && now - lastClick.timestamp < 80) {
      console.debug("[Botflows] Suppressed duplicate click:", primarySelector);
      return;
    }

    if (type === "focus") {
      const tag = target.tagName.toLowerCase();
      if (!["input", "textarea", "select"].includes(tag)) {
        console.debug("[Botflows] Ignored focus event on non-input element:", tag);
        return;
      }
    }

    if (type === "click") lastClick = { selector: primarySelector, timestamp: now };
    if (type === "focus") lastFocus = { selector: primarySelector, timestamp: now };

    const actionData = {
      action: type === "input" ? "type" : type,
      selector: primarySelector,
      selectors: meta.selectors,
      timestamp: now,
      value: target.value || null,
      url: window.location.href,
      tagName: target.tagName || null,
      classList: Array.from(target.classList || []),
      attributes: meta.attributes,
      innerText: meta.text,
      elementText: target.textContent || null,
      boundingBox: meta.boundingBox,
      ...override
    };

    console.debug("[Botflows] Sending event to Python:", actionData);
    window.__pendingValidation = true;
    showValidationOverlay();
    window.sendEventToPython(actionData);
  };

  ["click", "focus", "change", "dblclick"].forEach(type => {
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
