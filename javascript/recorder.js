import { getSmartSelector, getVisibleText } from './selectorHelper.js';
import { getSelectorAnalysisPayload, getAllAttributes } from './domanalyser.js';

(function () {
  if (window.__recorderInjected) return;
  window.__recorderInjected = true;
  console.log("[Botflows] Recorder script injected successfully");

  // Manual trigger from dashboard
  window.sendSelectorSnapshot = () => {
    if (typeof window.sendSelectorAnalysisToPython === "function") {
      const payload = {
        source: "manual-trigger",
        ...getSelectorAnalysisPayload()
      };
      window.sendSelectorAnalysisToPython(payload);
    }
  };

  // Define send handler
  window.sendSelectorAnalysisToPython = function (snapshot) {
    console.log("Sending selector snapshot to /api/snapshot", snapshot);
    fetch("http://localhost:8000/api/snapshot", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(snapshot)
    }).catch(e => console.warn("Failed to send snapshot to Python agent", e));
  };
  window.getSelectorAnalysisPayload = getSelectorAnalysisPayload;

  // Register exported functions
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

    if (type === "click" && selector === lastClick.selector && now - lastClick.timestamp < 150) return;
    if (type === "focus" && selector === lastFocus.selector && now - lastFocus.timestamp < 150) return;

    if (type === "click") lastClick = { selector, timestamp: now };
    if (type === "focus") lastFocus = { selector, timestamp: now };

    if (type === "input" && (target.tagName === "INPUT" || target.tagName === "TEXTAREA")) {
      clearTimeout(typingDebounce);
      lastTypedElement = target;
      typingDebounce = setTimeout(() => {
        if (lastTypedElement) {
          const actionData = {
            action: "type",
            selector: getSmartSelector(lastTypedElement),
            timestamp: Date.now(),
            value: lastTypedElement.value,
            url: window.location.href
          };

          window.sendEventToPython(actionData);
          window.parent.postMessage({ type: 'recorded-event', data: actionData }, '*');

          fetch("http://localhost:8000/api/stream_action", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(actionData)
          });

          lastTypedElement = null;
        }
      }, 800);
    } else {
      const actionData = {
        action: type,
        selector,
        timestamp: now,
        value: target.value || undefined,
        url: window.location.href
      };

      window.sendEventToPython(actionData);
      window.parent.postMessage({ type: 'recorded-event', data: actionData }, '*');

      fetch("http://localhost:8000/api/stream_action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(actionData)
      });
    }

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
          innerText: target.innerText.trim(),
          parentTag,
          siblingText
        },
        timestamp: new Date().toISOString(),
        pageUrl: window.location.href
      });
    }
  };

  ["click", "focus", "change", "input"].forEach(type => {
    document.addEventListener(type, sendEvent, true);
  });

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
      setTimeout(waitForBodyAndObserve, 100); // Retry until body exists
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
  // Trigger initial snapshot when DOM is ready
  // function triggerInitialSnapshot() {
  //   if (typeof window.sendSelectorAnalysisToPython === "function") {
  //     debugger;
  //     const snapshot = {
  //       source: "initial-snapshot",
  //       ...getSelectorAnalysisPayload()
  //     };
  //     console.log("Triggering initial selector snapshot");
  //     window.sendSelectorAnalysisToPython(snapshot);
  //   } else {
  //     console.warn("sendSelectorAnalysisToPython is not defined");
  //   }
  // }

  const snapshotSentUrls = new Set(JSON.parse(sessionStorage.getItem("snapshotSentUrls") || "[]"));

  function shouldSendSnapshot(url) {
    return !snapshotSentUrls.has(url);
  }

  function markSnapshotSent(url) {
    snapshotSentUrls.add(url);
    sessionStorage.setItem("snapshotSentUrls", JSON.stringify([...snapshotSentUrls]));
  }

  function trySendSnapshot(sourceLabel = "auto-snapshot") {
    const url = window.location.href;
    if (typeof window.sendSelectorAnalysisToPython !== "function") return;

    const analysisPayload = window.getSelectorAnalysisPayload();
    const hasElements = Array.isArray(analysisPayload.Elements) && analysisPayload.Elements.length > 0;

    if (!hasElements) {
      console.warn(`Skipping snapshot for ${url}: No elements found.`);
      return;
    }

    if (shouldSendSnapshot(url)) {
      const payload = {
        Source: sourceLabel,
        Url: url,
        Timestamp: new Date().toISOString(),
        ...analysisPayload
      };
      console.log(`📸 Snapshot sent for ${url}`);
      window.sendSelectorAnalysisToPython(payload);
      markSnapshotSent(url);
    } else {
      console.log(`Snapshot already sent for ${url}`);
    }
  }

  // Hook into navigation
  function setupSnapshotOnNavigation() {
    // Initial snapshot after full load
    window.addEventListener("load", () => {
      setTimeout(() => trySendSnapshot("initial-load"), 1000);
    });

    // Handle back/forward
    window.addEventListener("popstate", () => {
      setTimeout(() => trySendSnapshot("history-nav"), 1000);
    });

    // Patch history API
    const patchHistory = (method) => {
      const original = history[method];
      history[method] = function (...args) {
        const result = original.apply(this, args);
        setTimeout(() => trySendSnapshot(`history-${method}`), 1000);
        return result;
      };
    };
    patchHistory("pushState");
    patchHistory("replaceState");
  }

  setupSnapshotOnNavigation();


})();
