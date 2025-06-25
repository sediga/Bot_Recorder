(() => {
    if (window.__pickModeActive) return;
    window.__pickModeActive = true;
    window.__picked = false;

    const highlightStyle = "2px dashed orange";
    const grids = Array.from(document.querySelectorAll('[role="grid"], .MuiDataGrid-root, table'));

    function getUniqueSelector(el) {
        if (!el) return "";

        // If element has ID, use it directly
        if (el.id) return `#${el.id}`;

        const parts = [];
        let current = el;

        while (current && current.nodeType === 1 && current.tagName.toLowerCase() !== "body") {
            let selector = current.tagName.toLowerCase();

            // Use first 1 or 2 classes only (to avoid long auto-generated classes)
            if (current.className && typeof current.className === "string") {
                const classes = current.className.trim().split(/\s+/).filter(Boolean).slice(0, 2);
                if (classes.length) {
                    selector += "." + classes.join(".");
                }
            }

            // Check if this selector is unique among siblings
            const siblings = current.parentNode ? Array.from(current.parentNode.children) : [];
            const sameTagSiblings = siblings.filter(sib => sib.tagName === current.tagName);

            // Add nth-of-type only if needed to make it unique
            if (sameTagSiblings.length > 1) {
                const index = sameTagSiblings.indexOf(current) + 1;

                // Test if selector alone is unique
                let testSelector = selector;
                if (index > 1) {
                    testSelector += `:nth-of-type(${index})`;
                }

                // Build full selector for testing uniqueness
                const fullSelector = [...parts].reverse().join(" > ");
                const testFullSelector = fullSelector ? `${testSelector} > ${fullSelector}` : testSelector;

                if (document.querySelectorAll(testFullSelector).length === 1) {
                    selector = testSelector;
                } else {
                    // If still not unique, fallback to nth-of-type (ensures uniqueness)
                    selector = `${selector}:nth-of-type(${index})`;
                }
            }

            parts.unshift(selector);

            // Check if current combined selector is unique for the element, stop climbing if yes
            const fullSelector = parts.join(" > ");
            if (document.querySelectorAll(fullSelector).length === 1) {
                break;
            }

            current = current.parentElement;
        }

        // Add body at the start if not included
        if (current && current.tagName.toLowerCase() === "body") {
            parts.unshift("body");
        }

        return parts.join(" > ");
    }

    // Helper to infer column type by checking sample cell values (first 5 rows)
    function inferColumnType(grid, colIndex) {
    const BOOLEAN_VALUES = new Set(["true", "false", "yes", "no", "on", "off"]);
    
    const cells = Array.from(grid.querySelectorAll('[role="row"]')).map(row => {
        let cell = row.querySelector(`[data-colindex="${colIndex}"]`);
        if (!cell) {
        const allCells = Array.from(row.querySelectorAll('[role="cell"], td'));
        cell = allCells[colIndex];
        }
        return cell ? cell.innerText.trim() : "";
    }).filter(text => text.length > 0).slice(0, 10); // Sample up to 10 cells
    
    if (cells.length === 0) return "text";

    // Detect if any cell contains image or background-image
    for (const row of grid.querySelectorAll('[role="row"]')) {
        let cell = row.querySelector(`[data-colindex="${colIndex}"]`);
        if (!cell) {
        const allCells = Array.from(row.querySelectorAll('[role="cell"], td'));
        cell = allCells[colIndex];
        }
        if (cell && (cell.querySelector("img") || window.getComputedStyle(cell).backgroundImage !== "none")) {
        return "image";
        }
    }

    // Helper functions to test types
    const isBoolean = text => BOOLEAN_VALUES.has(text.toLowerCase());
    const isDate = text => !isNaN(Date.parse(text));
    const isNumber = text => !isNaN(parseFloat(text)) && isFinite(text);

    // Check all cells against each type
    const allBoolean = cells.every(isBoolean);
    if (allBoolean) return "boolean";

    const allDate = cells.every(isDate);
    if (allDate) return "date";

    const allNumber = cells.every(isNumber);
    if (allNumber) return "number";

    // Mixed or no clear type, fallback to text
    return "text";
    }

    const cleanup = () => {
        grids.forEach(grid => {
            grid.style.outline = "";
            grid.removeEventListener("mouseover", onMouseOver, true);
            grid.removeEventListener("mouseout", onMouseOut, true);
            grid.removeEventListener("click", onClick, true);
        });
        window.__picked = true;
    };

    const onMouseOver = (e) => {
        if (!window.__pickModeActive || window.__picked) return;
        const el = e.currentTarget;
        if (el) el.style.outline = "3px solid red";
    };

    const onMouseOut = (e) => {
        if (!window.__pickModeActive || window.__picked) return;
        const el = e.currentTarget;
        if (el) el.style.outline = highlightStyle;
    };

    const onClick = async (e) => {
        if (!window.__pickModeActive || window.__picked) return;

        e.preventDefault();
        e.stopPropagation();

        grids.forEach(g => g.style.outline = "");

        const grid = e.currentTarget;
        const index = grid.dataset.gridPickerIndex;
        const html = grid.outerHTML;
        const boundingBox = grid.getBoundingClientRect();

        // Get headers
        const columnHeadersTemp = Array.from(grid.querySelectorAll('[role="columnheader"], th')).map(th => th.innerText.trim());

        // Build columns array with header + inferred type
        const columnHeaders = columnHeadersTemp.map((header, colIndex) => {
            return {
                header,
                type: inferColumnType(grid, colIndex)
            };
        });

        const rowSamples = Array.from(grid.querySelectorAll('[role="row"]')).slice(0, 3).map(row =>
            Array.from(row.querySelectorAll('[role="cell"], td')).map(cell => cell.innerText.trim())
        );

        const gridSelector = getUniqueSelector(grid);
        if (typeof window.sendEventToPython === "function") {
            window.sendEventToPython({
                type: "targetPicked",
                metadata: {
                    gridId: "grid-" + index,
                    outerHTML: html,
                    gridSelector: gridSelector,
                    boundingBox: {
                        top: boundingBox.top,
                        left: boundingBox.left,
                        width: boundingBox.width,
                        height: boundingBox.height
                    },
                    columnHeaders,
                    rowSamples
                }
            });
            cleanup();
        }
    };

    grids.forEach((grid, index) => {
        grid.dataset.gridPickerIndex = index;
        grid.style.outline = highlightStyle;
        grid.addEventListener("mouseover", onMouseOver, true);
        grid.addEventListener("mouseout", onMouseOut, true);
        grid.addEventListener("click", onClick, true);
    });

    const interval = setInterval(() => {
        if (!window.__pickModeActive) {
            clearInterval(interval);
            cleanup();
        }
    }, 500);
})();
