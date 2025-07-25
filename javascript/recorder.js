import { getFullDomPath, getXPath, captureSelectors } from './selectorHelper.js';
import {getAllAttributes} from './domanalyser.js'

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
        
  function showBotflowsGridCriteriaPrompt(callback) {
    if (document.getElementById("botflows-prompt")) return;

    window.__pendingValidation = true;

    const container = document.createElement("div");
    container.id = "botflows-prompt";
    container.style.position = "fixed";
    container.style.top = "0";
    container.style.left = "0";
    container.style.width = "100vw";
    container.style.height = "100vh";
    container.style.backgroundColor = "rgba(0,0,0,0.5)";
    container.style.zIndex = 9999;
    container.style.display = "flex";
    container.style.alignItems = "center";
    container.style.justifyContent = "center";
    container.style.fontFamily = "Arial, sans-serif";
    container.setAttribute("data-botflows-ui", "true");

    const dialog = document.createElement("div");
    dialog.style.background = "white";
    dialog.style.padding = "20px";
    dialog.style.borderRadius = "12px";
    dialog.style.width = "460px";
    dialog.style.boxShadow = "0 5px 15px rgba(0,0,0,0.3)";
    dialog.setAttribute("data-botflows-ui", "true");

    dialog.innerHTML = `
      <h2 style="margin-top:0; font-size:20px; color:#333;">🔁 Botflows – Row Action Condition</h2>
      <p style="margin: 10px 0;">Only click this element if a column in the current row matches:</p>
      
      <label for="grid-column">Column Name:</label>
      <input id="grid-column" placeholder="e.g. Status" style="width:100%; padding:8px; font-size:14px; margin-bottom:10px;" />

      <label for="grid-value">Equals Value:</label>
      <input id="grid-value" placeholder="e.g. Pending" style="width:100%; padding:8px; font-size:14px;" />

      <div style="margin-top:20px; display: flex; justify-content: flex-end; gap: 10px;">
        <button id="cancel-btn" style="padding: 6px 12px; background: #eee; border: 1px solid #ccc;">Cancel</button>
        <button id="submit-btn" style="padding: 6px 12px; background: #2563eb; color: white; border: none;">Submit</button>
      </div>
    `;

    container.appendChild(dialog);
    document.body.appendChild(container);

    const inputCol = dialog.querySelector("#grid-column");
    const inputVal = dialog.querySelector("#grid-value");

    inputCol.focus();

    dialog.querySelector("#cancel-btn").onclick = () => {
      document.body.removeChild(container);
      window.__pendingValidation = false;
      callback(null, null);
    };

    dialog.querySelector("#submit-btn").onclick = () => {
      const col = inputCol.value.trim();
      const val = inputVal.value.trim();
      document.body.removeChild(container);
      window.__pendingValidation = false;
      callback(col || null, val || null);
    };
  }

  function showBotflowsDateCriteriaPrompt(callback) {
    if (document.getElementById("botflows-prompt")) return;

    window.__pendingValidation = true;

    const container = document.createElement("div");
    container.id = "botflows-prompt";
    container.style.position = "fixed";
    container.style.top = "0";
    container.style.left = "0";
    container.style.width = "100vw";
    container.style.height = "100vh";
    container.style.backgroundColor = "rgba(0,0,0,0.5)";
    container.style.zIndex = 9999;
    container.style.display = "flex";
    container.style.alignItems = "center";
    container.style.justifyContent = "center";
    container.style.fontFamily = "Arial, sans-serif";
    container.setAttribute("data-botflows-ui", "true");

    const dialog = document.createElement("div");
    dialog.style.background = "white";
    dialog.style.padding = "20px";
    dialog.style.borderRadius = "12px";
    dialog.style.width = "460px";
    dialog.style.boxShadow = "0 5px 15px rgba(0,0,0,0.3)";
    dialog.setAttribute("data-botflows-ui", "true");

    const criteria = [
      { value: "firstActiveDate", label: "First Active Date" },
      { value: "today", label: "Today" },
      { value: "nextWeekday", label: "Next Weekday" },
      { value: "specificDate", label: "Specific Date (Coming Soon)" }
    ];

    dialog.innerHTML = `
      <h2 style="margin-top:0; font-size:20px; color:#333;">📅 Botflows – Date Picker Criteria</h2>
      <p style="margin: 10px 0;">Choose how this date should be selected during automation:</p>

      <label for="botflows-date-criteria">Date Selection:</label>
      <select id="botflows-date-criteria" style="width:100%; padding:8px; font-size:14px;">
        ${criteria.map(c => `<option value="${c.value}">${c.label}</option>`).join("")}
      </select>

      <div style="margin-top:20px; display: flex; justify-content: flex-end; gap: 10px;">
        <button id="cancel-btn" style="padding: 6px 12px; background: #eee; border: 1px solid #ccc;">Cancel</button>
        <button id="submit-btn" style="padding: 6px 12px; background: #2563eb; color: white; border: none;">Submit</button>
      </div>
    `;

    container.appendChild(dialog);
    document.body.appendChild(container);

    const selector = dialog.querySelector("#botflows-date-criteria");

    dialog.querySelector("#cancel-btn").onclick = () => {
      document.body.removeChild(container);
      window.__pendingValidation = false;
      callback(null);
    };

    dialog.querySelector("#submit-btn").onclick = () => {
      const selected = selector.value;
      document.body.removeChild(container);
      window.__pendingValidation = false;
      callback(selected);
    };
  }

  function showBotflowsColumnPrompt(columns, onSubmit) {
    if (document.getElementById("botflows-prompt")) return;

    const container = document.createElement("div");
    container.id = "botflows-prompt";
    container.style.position = "fixed";
    container.style.top = "0";
    container.style.left = "0";
    container.style.width = "100vw";
    container.style.height = "100vh";
    container.style.backgroundColor = "rgba(0,0,0,0.5)";
    container.style.zIndex = 9999;
    container.style.display = "flex";
    container.style.alignItems = "center";
    container.style.justifyContent = "center";
    container.style.fontFamily = "Arial, sans-serif";
    container.setAttribute("data-botflows-ui", "true");

    const dialog = document.createElement("div");
    dialog.style.background = "white";
    dialog.style.padding = "20px";
    dialog.style.borderRadius = "12px";
    dialog.style.width = "460px";
    dialog.style.boxShadow = "0 5px 15px rgba(0,0,0,0.3)";
    dialog.setAttribute("data-botflows-ui", "true");

    let selectedIndex = null;
    let transformValue = "";
    let transformType = "regex";

    function getRawPreview() {
      if (selectedIndex == null) return "";
      return columns[selectedIndex]?.preview || "";
    }

    function getTransformedPreview(val) {
      if (!val) return "";

      try {
        if (transformType === "regex") {
          const re = new RegExp(transformValue);
          const match = val.match(re);
          return match?.[1] || match?.[0] || "(no match)";
        } else if (transformType === "js") {
          const fn = new Function("value", `return value${transformValue}`);
          return fn(val);
        }
      } catch (e) {
        return "(error)";
      }
      return val;
    }

    window.getTransformedPreview = getTransformedPreview;
    
    function renderPreview() {
      dialog.querySelector("#botflows-raw-value").textContent = getRawPreview();
      dialog.querySelector("#botflows-transformed-value").textContent = getTransformedPreview(getRawPreview());
    }

    dialog.innerHTML = `
      <h2 style="margin-top:0; font-size:20px; color:#333;">🔁 Botflows – Map Field to Column</h2>
      <p style="margin: 10px 0;">Select a column to map this input to:</p>
      <select id="column-select" style="width:100%; padding:8px; font-size:14px;">
        <option value="">-- Skip Mapping --</option>
        ${columns.map((col, i) => `<option value="${i}">${col.label}</option>`).join("")}
      </select>
      <p style="margin: 10px 0 5px;">Transform type:</p>
      <select id="transform-type" style="width:100%; padding:8px; font-size:14px;">
        <option value="regex">Regex</option>
        <option value="js">JS Expression (e.g. .trim(), .slice(0,3))</option>
      </select>
      <p style="margin: 10px 0 5px;">Transformation rule:</p>
      <input id="transform-input" type="text" placeholder="e.g., (.+?)\\s or .trim()" style="width:100%; padding:8px; font-size:14px;" />
      <div style="margin-top:16px; font-style:italic;">
        <div>Raw: <span id="botflows-raw-value" style="font-weight:bold;"></span></div>
        <div>Result: <span id="botflows-transformed-value" style="font-weight:bold;"></span></div>
      </div>
      <div style="margin-top:20px; display: flex; justify-content: flex-end; gap: 10px;">
        <button id="cancel-btn" style="padding: 6px 12px; background: #eee; border: 1px solid #ccc;">Cancel</button>
        <button id="submit-btn" style="padding: 6px 12px; background: #2563eb; color: white; border: none;">Submit</button>
      </div>
    `;

    container.appendChild(dialog);
    document.body.appendChild(container);

    dialog.querySelector("#column-select").onchange = (e) => {
      selectedIndex = parseInt(e.target.value);
      renderPreview();
    };

    dialog.querySelector("#transform-input").oninput = (e) => {
      transformValue = e.target.value;
      renderPreview();
    };

    dialog.querySelector("#transform-type").onchange = (e) => {
      transformType = e.target.value;
      renderPreview();
    };

    dialog.querySelector("#cancel-btn").onclick = () => {
      document.body.removeChild(container);
      onSubmit(null);
    };

    dialog.querySelector("#submit-btn").onclick = () => {
      document.body.removeChild(container);
      onSubmit(selectedIndex != null ? {
        index: selectedIndex,
        transform: transformValue,
        transformType
      } : null);
    };
  }


  function getFieldOptionsFromSource(sourceStep) {
    if (!sourceStep) return [];

    if (sourceStep.type === "gridExtract") {
      debugger;
      return (sourceStep.columnMappings || []).map((c, i) => ({
        label: `${i + 1}. ${c.header?.header || "Unnamed"}`,
        value: c.header?.header || "",
        preview: c.preview || "sample"
      }));

    }

    if (sourceStep.type === "apiExtract") {
      return (sourceStep.fields || []).map(f => ({
        label: f.path,
        value: f.path,
        preview: f.preview || "sample"
      }));
    }

    // Extend here for Excel, SQL, etc.
    return [];
  }

  function hideValidationOverlay() {
    const el = document.getElementById("__botflows_validation_overlay");
    if (el) el.remove();
  }
  window.hideValidationOverlay = hideValidationOverlay;
  window.showValidationOverlay = showValidationOverlay;

  function isInternalUI(target) {
    return target.closest("[data-botflows-ui]");
  }

  const sendEvent = (event, override = {}) => {
    if (window.__botflows_replaying__) {
      console.debug("[Botflows] In replay mode — event suppressed:", event.type);
      return;
    }

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

    if (isInternalUI(target)) {
      console.debug("[Botflows] Skipping event from Botflows UI:", target);
      return;
    }

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

    const now = Date.now();
    const selectors = captureSelectors(target);

    function getTopSelector(result) {
      if (!result || !result.selectors || result.selectors.length === 0) return null;

      const best = result.selectors.reduce((a, b) => (a.score > b.score ? a : b));
      return best.selector;
    }
    const primarySelector = getTopSelector(selectors);

    const metadata = {
      tagName: target.tagName.toLowerCase(),
      id: target.id || null,
      name: target.getAttribute("name") || null,
      classList: Array.from(target.classList || []),
      attributes: getAllAttributes(target),
      text: target.innerText?.trim() || "",
      elementText: target.textContent?.trim() || "",
      boundingBox: target.getBoundingClientRect?.(),
      outerHTML: target.outerHTML || "",
      selector: primarySelector || "",
      domPath: getFullDomPath(target),
      xpath: getXPath(target)
    };

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
      url: window.location.href,
      value: target.value || null,
      timestamp: now,
      ...metadata
    };

    // 🔁 Dynamic Param Logic — Source-aware
    const sourceStep = window.loopContext?.sourceStep;
    const fields = getFieldOptionsFromSource(sourceStep);

    if (
      window.loopContext?.active &&
      fields.length &&
      ["input", "select", "textarea", "a", "button"].includes(target.tagName.toLowerCase()) &&
      target.getAttribute("data-botflows-mapped") !== window.loopContext?.loopName
    ) {
      // Auto param if user typed {{field}}
      if (typeof target.value === "string" && /\{\{.*\}\}/.test(target.value)) {
        const match = target.value.match(/\{\{(.*?)\}\}/);
        const key = match?.[1]?.trim();
        const field = fields.find(f => f.value === key);
        if (field) {
          target.setAttribute("data-botflows-mapped", window.loopContext?.loopName || "global");
          target.setAttribute("data-dynamic-value", `{{${field.value}}}`);
          target.dispatchEvent(new Event("change", { bubbles: true }));
          console.debug(`[Botflows] Auto-mapped input to: {{${field.value}}}`);
          finalizeAndSend();
          return;
        }
      }

      // Prompt if UI action is high-intent
      const shouldPrompt =
        ["select", "a", "button", "div"].includes(target.tagName.toLowerCase()) ||
        ["combobox", "link", "option"].includes(target.getAttribute("role"));
      debugger;
      if (shouldPrompt || target.tagName.toLowerCase() === "input") {
        debugger;
        const inputType = (target.getAttribute("type") || "").toLowerCase();
        const nameLower = (target.getAttribute("name") || "").toLowerCase();
        const classLower = (target.className || "").toLowerCase();

        // ➤ If user clicked a link/button inside a grid row, show criteria prompt
        if (
          type === "click" &&
          window.loopContext?.active
        ) {
          // Try resolving the row using multiple strategies
          const rowEl = target.closest("[role='row'], tr, .MuiDataGrid-row, .sticky-row, [data-row], [data-rowindex]");
          if (!rowEl) {
            console.warn("[Botflows] No row found");
            finalizeAndSend();
            return;
          }

          // Resolve grid (for additional metadata if needed later)
          const gridEl = rowEl.closest("[role='grid'], table, .MuiDataGrid-root, .patient-list-grid, [data-grid]");

          // Prefer role-based cells, fall back to row children
          let cellEls = Array.from(rowEl.querySelectorAll("[role='gridcell'], [role='cell']"));
          if (cellEls.length === 0) {
            cellEls = Array.from(rowEl.children || []);
          }

          const columnIndex = cellEls.findIndex(cell => cell.contains(target));
          const columnMappings = window.loopContext?.sourceStep?.columnMappings || [];

          if (columnIndex < 0 || columnIndex >= columnMappings.length) {
            console.warn("[Botflows] Couldn't resolve clicked column index");
            finalizeAndSend();
            return;
          }

          const columnHeader = columnMappings[columnIndex]?.header || `Column ${columnIndex + 1}`;
          const tag = target.tagName.toLowerCase();
          const role = target.getAttribute("role")?.toLowerCase() || "";
          const typeAttr = target.getAttribute("type")?.toLowerCase() || "";

          function inferActionType(el) {
            if (el.tagName.toLowerCase() === "input" && ["text", "search"].includes(typeAttr)) return "type";
            if (el.tagName.toLowerCase() === "select") return "select";
            if (["button", "a", "div"].includes(tag) || ["button", "link"].includes(role)) return "click";
            return "click";
          }

          const actionType = inferActionType(target);

          window.__botflowsTempStepExtras__ = {
            type: "clickInColumn",
            columnIndex,
            columnHeader,
            actionType,
            targetTag: tag,
            selector: primarySelector
          };

          console.debug(`[Botflows] Auto-captured smart column action → column ${columnIndex} (${columnHeader}), action: ${actionType}, tag: ${tag}`);
          finalizeAndSend();
          return;
        }

        const isDateLike =
          inputType === "date" ||
          nameLower.includes("date") ||
          classLower.includes("date") ||
          classLower.includes("calendar");

        if (isDateLike) {
          debugger;
          // ➤ Handle special logic for date input
          showBotflowsDateCriteriaPrompt((selectedCriteria) => {
            if (!selectedCriteria) {
              target.setAttribute("data-botflows-mapped", window.loopContext?.loopName || "global");
              finalizeAndSend();
              return;
            }

            // Save criteria + loop info for final step
            target.setAttribute("data-botflows-date-criteria", selectedCriteria);
            target.setAttribute("data-botflows-mapped", window.loopContext?.loopName || "global");

            // Temp metadata to include in stepPayload
            window.__botflowsTempStepExtras__ = {
              dateCriteria: selectedCriteria
            };

            finalizeAndSend();
          });

          return;
        }

        // ➤ Normal input, show column mapping + transform options
        showBotflowsColumnPrompt(fields, (selected) => {
          if (!selected) {
            target.setAttribute("data-botflows-mapped", window.loopContext?.loopName || "global");
            finalizeAndSend();
            return;
          }

          const selectedField = fields[selected.index];
          const dynamicVal = `{{${selectedField.value}}}`;
          const previewValue = selectedField.preview || "sample";

          const transformType = selected.transformType || null;
          const transform = selected.transform || "";

          const transformed = window.getTransformedPreview(previewValue) || previewValue;
          target.value = transformed;

          target.setAttribute("data-botflows-mapped", window.loopContext?.loopName || "global");
          target.setAttribute("data-dynamic-value", dynamicVal);

          if (transformType) {
            target.setAttribute("data-transform-type", transformType);
            target.setAttribute("data-transform", transform);
          }

          target.dispatchEvent(new Event("input", { bubbles: true }));
          target.dispatchEvent(new Event("change", { bubbles: true }));

          console.debug(`[Botflows] Mapped input to: ${dynamicVal} (with ${transformType || "no"} transform: ${transform})`);
          finalizeAndSend();
        });

        return;
      }
    }

    finalizeAndSend();

    function finalizeAndSend() {
      if (window.__botflowsTempStepExtras__) {
        Object.assign(actionData, window.__botflowsTempStepExtras__);
        window.__botflowsTempStepExtras__ = null;
      }

      console.debug("[Botflows] Sending event to Python:", actionData);
      window.__pendingValidation = true;
      showValidationOverlay();
      window.sendEventToPython(actionData);
      waitForValidationComplete();
    }
  };

  ["click", "focus", "change", "dblclick"].forEach(type => {
    document.addEventListener(type, sendEvent, true);
    console.debug(`[Botflows] Event listener attached for ${type}`);
  });

  function waitForValidationComplete(timeout = 5000) {
    return new Promise((resolve) => {
      const handler = (event) => {
        if (event.data?.type === "validationComplete") {
          window.removeEventListener("message", handler);
          window.__pendingValidation = false;
          hideValidationOverlay();
          resolve();
        }
      };

      window.addEventListener("message", handler);

      // Safety timeout
      setTimeout(() => {
        window.removeEventListener("message", handler);
        console.warn("[Botflows] Validation timeout");
        window.__pendingValidation = false;
        hideValidationOverlay();
        resolve();
      }, timeout);
    });
  }

  let inputDebounceTimer = null;
  let lastInputValue = "";

  function flushInput(target) {
    const value = target.value || "";
    if (value !== lastInputValue) {
      lastInputValue = value;
      const fakeEvent = new Event("input");
      fakeEvent.target = target;
      sendEvent(fakeEvent);
    }
  }

  // Debounced handler for input events
  document.addEventListener("input", (event) => {
    if (isInPickMode()) return;
    const target = event.target;
    if (!target.matches("input, textarea")) return;

    clearTimeout(inputDebounceTimer);
    inputDebounceTimer = setTimeout(() => flushInput(target), 300);
  }, true);

  // Flush immediately on Enter
  document.addEventListener("keydown", (event) => {
    if (isInPickMode()) return;
    const target = event.target;
    if (!target.matches("input, textarea")) return;

    if (event.key === "Enter") {
      clearTimeout(inputDebounceTimer);
      flushInput(target);
    }
  }, true);

  // Flush on blur
  document.addEventListener("blur", (event) => {
    if (isInPickMode()) return;
    const target = event.target;
    if (!target.matches("input, textarea, select")) return;

    clearTimeout(inputDebounceTimer);
    flushInput(target);
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
