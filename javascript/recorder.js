(() => {
  function getUniqueSelector(el) {
    if (!el) return "";
    if (el.id) return `#${el.id}`;
    if (el.name) return `[name="${el.name}"]`;
    const path = [];
    while (el && el.nodeType === Node.ELEMENT_NODE) {
      let selector = el.nodeName.toLowerCase();
      if (el.className)
        selector += "." + el.className.trim().replace(/\s+/g, ".");
      path.unshift(selector);
      el = el.parentNode;
    }
    return path.join(" > ");
  }

  function record(type, target, extra = {}) {
    const selector = getUniqueSelector(target);
    const timestamp = Date.now();
    const event = { action: type, selector, timestamp, ...extra };
    if (typeof window.sendEventToPython === "function") {
      window.sendEventToPython(event);
    }
  }

  document.addEventListener('click', e => record('click', e.target));
  document.addEventListener('input', e => record('type', e.target, { value: e.target.value }));
  document.addEventListener('change', e => record('change', e.target, { value: e.target.value }));
  document.addEventListener('submit', e => {
    e.preventDefault();
    record('submit', e.target);
  });
  document.addEventListener('keydown', e => record('keydown', e.target, { key: e.key }));
  document.addEventListener('focus', e => record('focus', e.target), true);
  document.addEventListener('blur', e => record('blur', e.target), true);
})();
