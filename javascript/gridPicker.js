(function () {
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

    function looksLikeDate(text) {
        const date = Date.parse(text);
        return !isNaN(date);
    }

    function variableizeDate(text) {
        const dateRegex = /\b(?:\d{1,2}[\/\-.]\d{1,2}[\/\-.]\d{2,4}|\w+\s\d{1,2},\s\d{4})\b/g;
        return text.replace(dateRegex, "{Date}");
    }

    function isImageCell(cell) {
        if (!cell || cell.offsetParent === null) return false; // skip hidden cells

        // 1. DOM elements
        const hasImage = !!cell.querySelector("img, svg, use");

        // 2. Background image
        const bgImage = window.getComputedStyle(cell).getPropertyValue("background-image");
        const hasBackgroundImage = bgImage &&
            bgImage !== "none" &&
            !bgImage.includes("about:blank") &&
            !bgImage.includes("data:image/gif") &&
            !bgImage.includes("transparent");

        // 3. Class-based hints
        const classNames = cell.className?.toLowerCase() || "";
        const hasImageClass = /(icon|avatar|photo|thumb|image|status|flag|badge)/.test(classNames);

        // 4. Data attributes or ARIA hints
        const hasAriaImage = cell.getAttribute("role") === "img" ||
                            cell.getAttribute("aria-label")?.toLowerCase().includes("image");

        return hasImage || hasBackgroundImage || hasImageClass || hasAriaImage;
    }

    function inferColumnType(grid, colIndex) {
        const BOOLEAN_VALUES = new Set(["true", "false", "yes", "no", "on", "off"]);
        const rowElements = Array.from(grid.querySelectorAll('[role="row"]'));

        if (rowElements.length === 0) {
            console.warn("[inferColumnType] No [role='row'] found, applying fallback...");
            rowElements.push(...grid.querySelectorAll('.MuiDataGrid-row, tr'));
        }

        console.log(`[inferColumnType] Inferring type for column: ${colIndex}`);
        console.log(`[inferColumnType] Total rows found (after fallback): ${rowElements.length}`);

        const cells = rowElements.map(row => {
            let cell = row.querySelector(`[data-colindex="${colIndex}"]`);
            if (!cell) {
                const allCells = Array.from(row.querySelectorAll('[role="cell"], td, th'));
                cell = allCells[colIndex];
            }
            return cell ? cell.innerText.trim() : "";
        }).filter(text => text.length > 0).slice(0, 10);

        console.log("[inferColumnType] Sampled Cell Texts:", cells);


        let imageDetectedCount = 0;

        for (const row of rowElements) {
            let cell = row.querySelector(`[data-colindex="${colIndex}"]`);
            if (!cell) {
                const allCells = Array.from(row.querySelectorAll('[role="cell"], td, th'));
                if (colIndex < allCells.length) {
                    cell = allCells[colIndex];
                }
            }

            if (isImageCell(cell)) {
                imageDetectedCount++;
            }
        }

        const ratio = imageDetectedCount / rowElements.length;
        console.log(`[inferColumnType] Detected image-based column: ${imageDetectedCount}/${rowElements.length}`);
        if (ratio >= 0.4) return "img";

        if (cells.length === 0) return "text";

        const isBoolean = text => BOOLEAN_VALUES.has(text.toLowerCase());
        const isDate = text => looksLikeDate(text);
        const isNumber = text => !isNaN(parseFloat(text)) && isFinite(text);

        const isTextWithDate = () => {
            const dateRegex = /\b(?:\d{1,2}[\/\-.]\d{1,2}[\/\-.]\d{2,4}|\w+\s\d{1,2},\s\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}-[A-Za-z]{3}-\d{4})\b/g;
            const hasValidDateInside = (text) => {
                const matches = text.match(dateRegex);
                return matches?.some(date => looksLikeDate(date));
            };
            const count = cells.filter(text => text !== "" && hasValidDateInside(text)).length;
            console.log("inferred type is text_with_date: " + count + "/" + cells.length);
            return (count / cells.length) >= 0.6;
        };

        if (cells.every(isBoolean)) return "boolean";
        if (cells.every(isDate)) return "date";
        if (cells.every(isNumber)) return "number";
        if (isTextWithDate()) return "text_with_date";

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

        const columnHeadersTemp = Array.from(grid.querySelectorAll('[role="columnheader"], th')).map((th, colIndex) => {
            let header = th.innerText.trim();

            if (!header) {
                const img = th.querySelector("img");
                if (img) {
                    header = img.alt || img.title || img.getAttribute("aria-label") || `Image Column ${colIndex + 1}`;
                }

                if (!header) {
                    const cls = th.className || "";
                    if (cls.includes("signal")) header = "Signal Icon";
                    else if (cls.includes("icon")) header = "Icon Column";
                    else header = `Column ${colIndex + 1}`;
                }
            }

            return header;
        });

        console.log("[onClick] Column headers found:", columnHeadersTemp);

        const columnHeaders = columnHeadersTemp.map((header, colIndex) => {
            const type = inferColumnType(grid, colIndex);
            const variableized = [];

        if (type === "text_with_date") {
            const rowElements = Array.from(grid.querySelectorAll('[role="row"]'));
            if (rowElements.length === 0) {
                rowElements.push(...grid.querySelectorAll('.MuiDataGrid-row, tr'));
            }

            const seenFormats = new Set();
            const variables = [];

            const inferDateFormat = (dateStr) => {
                if (/^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}$/.test(dateStr)) return "dd/MM/yyyy";
                if (/^\d{4}-\d{2}-\d{2}$/.test(dateStr)) return "yyyy-MM-dd";
                if (/^\d{2}-[A-Za-z]{3}-\d{4}$/.test(dateStr)) return "dd-MMM-yyyy";
                if (/^[A-Za-z]+\s\d{1,2},\s\d{4}$/.test(dateStr)) return "MMMM d, yyyy";
                return "unknown";
            };

            const extractDates = (text) => {
                const dateRegex = /\b(\d{1,2}[\/\-.]\d{1,2}[\/\-.]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{2}-[A-Za-z]{3}-\d{4}|\w+\s\d{1,2},\s\d{4})\b/g;
                return [...text.matchAll(dateRegex)].map(match => match[1]);
            };

            rowElements.forEach(row => {
                let cell = row.querySelector(`[data-colindex="${colIndex}"]`);
                if (!cell) {
                    const allCells = Array.from(row.querySelectorAll('[role="cell"], td, th'));
                    if (colIndex < allCells.length) {
                        cell = allCells[colIndex];
                    }
                }
                const text = cell?.innerText.trim();
                if (text) {
                    const dates = extractDates(text);
                    dates.forEach(date => {
                        const format = inferDateFormat(date);
                        if (!seenFormats.has(format)) {
                            seenFormats.add(format);
                            variables.push({
                                name: `date${variables.length + 1}`,
                                type: "date",
                                format
                            });
                        }
                    });
                }
            });

            return {
                header,
                type,
                ...(variables.length ? { variables } : {})
            };
        }
        return { header, type }; 
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
                    gridSelector,
                    boundingBox: {
                        top: boundingBox.top,
                        left: boundingBox.left,
                        width: boundingBox.width,
                        height: boundingBox.height
                    },
                    columnHeaders
                    // rowSamples
                }
            });
        }

        const overlay = document.createElement("div");
        overlay.id = "__botflows_picker_overlay";
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

    window.finishPicker = () => {
        const overlay = document.getElementById("__botflows_picker_overlay");
        if (overlay) overlay.remove();
        window.__pickModeActive = false;
        window.__picked = false;
        cleanup();
    };
})();
