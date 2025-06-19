export function scoreElement(elData) {
  let score = 0;

  const tag = elData.Tag;
  const attrs = elData.Attributes || {};
  const classNames = (elData.Classes || []).join(" ").toLowerCase();

  if (["a", "button"].includes(tag) || elData.Role === "button") score += 10;
  if (elData.Id) score += 8;
  if (attrs["data-testid"] || attrs["aria-label"] || attrs["name"]) score += 6;
  if (elData.Text?.trim()) score += 5;
  if (["submit", "button"].includes(elData.Type)) score += 3;
  if (["input", "select", "textarea"].includes(tag)) score += 3;
  if (classNames.includes("btn") || classNames.includes("clickable")) score += 3;

  return score;
}

export function getAllAttributes(el) {
  const attrs = {};
  for (let attr of el.attributes) {
    if (attr.name && attr.value) {
      attrs[attr.name] = attr.value;
    }
  }
  return attrs;
}

export function collectAllElementsForSelectorAnalysis(limit = 1000) {
  const elements = Array.from(document.querySelectorAll('*')).filter(el => {
    const tag = el.tagName.toLowerCase();
    const interactiveTags = ['a', 'button', 'input', 'select', 'textarea', 'label'];
    const semanticTags = ['section', 'article', 'nav', 'header', 'footer'];
    const isVisible = el.offsetParent !== null || getComputedStyle(el).display !== 'none';
    const bounding = el.getBoundingClientRect();
    const isZeroSized = bounding.width === 0 || bounding.height === 0;

    return (
      !isZeroSized &&
      (
        interactiveTags.includes(tag) ||
        semanticTags.includes(tag) ||
        (isVisible && el.innerText?.trim())
      )
    );
  });

  const scored = elements.map(el => {
    const attr = (name) => el.getAttribute(name);
    const text = el.innerText?.trim().substring(0, 100) || '';

    const rawData = {
      Tag: el.tagName.toLowerCase(),
      Id: attr('id') || "",
      Classes: [...el.classList],
      Role: attr('role') || "",
      Name: attr('name') || "",
      Type: attr('type') || "",
      Text: text,
      Attributes: getAllAttributes(el),
    };

    return {
      ...rawData,
      Score: scoreElement(rawData)
    };
  });

  // ⚠️ Adjust threshold if needed
  return scored.filter(el => el.Score >= 10);
}

export function getSelectorAnalysisPayload(limit = 1000) {
  return {
    Url: window.location.href,
    Timestamp: new Date().toISOString(),
    Source: 'forced-delayed-snapshot',
    Elements: collectAllElementsForSelectorAnalysis(limit)
  };
}
