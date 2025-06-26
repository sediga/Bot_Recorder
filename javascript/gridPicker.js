(() => {
    if (window.__pickModeActive) return;
    window.__pickModeActive = true;
    window.__picked = false;

    const highlightStyle = "2px dashed orange";
    const grids = Array.from(document.querySelectorAll('[role="grid"], .MuiDataGrid-root, table'));

    function getUniqueSelector(el) {
        if (!el) return "";
        if (el.id) return `#${el.id}`;
        const parts = [];
        let current = el;
        while (current && current.nodeType === 1 && current.tagName.toLowerCase() !== "body") {
            let selector = current.tagName.toLowerCase();
            if (current.className && typeof current.className === "string") {
                const classes = current.className.trim().split(/\s+/).filter(Boolean).slice(0, 2);
                if (classes.length) selector += "." + classes.join(".");
            }
            const siblings = current.parentNode ? Array.from(current.parentNode.children) : [];
            const sameTagSiblings = siblings.filter(sib => sib.tagName === current.tagName);
            if (sameTagSiblings.length > 1) {
                const index = sameTagSiblings.indexOf(current) + 1;
                let testSelector = selector;
                if (index > 1) testSelector += `:nth-of-type(${index})`;
                const fullSelector = [...parts].reverse().join(" > ");
                const testFullSelector = fullSelector ? `${testSelector} > ${fullSelector}` : testSelector;
                if (document.querySelectorAll(testFullSelector).length === 1) {
                    selector = testSelector;
                } else {
                    selector = `${selector}:nth-of-type(${index})`;
                }
            }
            parts.unshift(selector);
            const fullSelector = parts.join(" > ");
            if (document.querySelectorAll(fullSelector).length === 1) break;
            current = current.parentElement;
        }
        if (current && current.tagName.toLowerCase() === "body") parts.unshift("body");
        return parts.join(" > ");
    }

    function inferColumnType(grid, colIndex) {
        const BOOLEAN_VALUES = new Set(["true", "false", "yes", "no", "on", "off"]);
        const cells = Array.from(grid.querySelectorAll('[role="row"]')).map(row => {
            let cell = row.querySelector(`[data-colindex="${colIndex}"]`);
            if (!cell) {
                const allCells = Array.from(row.querySelectorAll('[role="cell"], td'));
                cell = allCells[colIndex];
            }
            return cell ? cell.innerText.trim() : "";
        }).filter(text => text.length > 0).slice(0, 10);
        if (cells.length === 0) return "text";
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
        const isBoolean = text => BOOLEAN_VALUES.has(text.toLowerCase());
        const isDate = text => !isNaN(Date.parse(text));
        const isNumber = text => !isNaN(parseFloat(text)) && isFinite(text);
        if (cells.every(isBoolean)) return "boolean";
        if (cells.every(isDate)) return "date";
        if (cells.every(isNumber)) return "number";
        return "text";
    }

    const cleanup = () => {
        grids.forEach(grid => {
            grid.style.outline = "";
            grid.removeEventListener("mouseover", onMouseOver, true);
            grid.removeEventListener("mouseout", onMouseOut, true);
            grid.removeEventListener("click", onClick, true);
        });
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

        const columnHeadersTemp = Array.from(grid.querySelectorAll('[role="columnheader"], th')).map(th => th.innerText.trim());
        const columnHeaders = columnHeadersTemp.map((header, colIndex) => ({
            header,
            type: inferColumnType(grid, colIndex)
        }));

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
                    gridSelector,
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
        }

        // Blur + overlay
        const overlay = document.createElement("div");
        overlay.id = "__botflows_overlay";
        overlay.style.position = "fixed";
        overlay.style.top = "0";
        overlay.style.left = "0";
        overlay.style.width = "100%";
        overlay.style.height = "100%";
        overlay.style.zIndex = "9999";
        overlay.style.backdropFilter = "blur(3px)";
        overlay.style.backgroundColor = "rgba(255,255,255,0.6)";
        overlay.style.display = "flex";
        overlay.style.alignItems = "center";
        overlay.style.justifyContent = "center";
        overlay.innerHTML = `<div style="font-size: 20px; font-weight: bold; background: #fff; padding: 20px; border: 2px solid #333; border-radius: 10px;">Finish setup in the Botflows dashboard...</div>`;
        document.body.appendChild(overlay);

        window.__picked = true;
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

    // Expose finish method to dashboard
    window.finishPicker = () => {
        const overlay = document.getElementById("__botflows_overlay");
        if (overlay) overlay.remove();
        window.__pickModeActive = false;
        window.__picked = false;
        cleanup();
    };
})();
