from bs4 import BeautifulSoup
import dateparser
import re

from common import state

def infer_date_format(date_str: str) -> str:
    if re.match(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", date_str): return "dd/MM/yyyy"
    if re.match(r"\d{4}-\d{2}-\d{2}", date_str): return "yyyy-MM-dd"
    if re.match(r"\d{2}-[A-Za-z]{3}-\d{4}", date_str): return "dd-MMM-yyyy"
    if re.match(r"[A-Za-z]+\s\d{1,2},\s\d{4}", date_str): return "MMMM d, yyyy"
    return "unknown"

async def resolve_grid_selector(page, outer_html: str):
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(outer_html, "html.parser")
    tag = soup.find()
    if not tag:
        return None, ""

    candidates = await page.query_selector_all(tag.name)
    for el in candidates:
        try:
            html = await el.evaluate("el => el.outerHTML")
            if html.strip() == outer_html.strip():
                smart_selector = await el.evaluate("el => window.getSmartSelector ? getSmartSelector(el) : ''")
                return el, smart_selector
        except:
            continue

    return None, ""

async def infer_column_metadata(page, grid_selector: str):
    headers = []
    mappings = []

    grid = page.locator(grid_selector)
    header_els = await grid.locator("[role='columnheader'], th").all()

    for idx, el in enumerate(header_els):
        header = (await el.inner_text()).strip() or await el.get_attribute("aria-label") or f"Column {idx+1}"

        possible_selectors = [
            "td:nth-child({idx_plus})",
            "div[role='gridcell'][data-colindex='{idx}']",
            "[role='cell']:nth-child({idx_plus})",
            "td:nth-child({idx_plus}) input",
            "td:nth-child({idx_plus}) div",
            "td:nth-child({idx_plus}) *"
        ]

        valid_selector = None
        for sel in possible_selectors:
            sel_formatted = sel.format(idx=idx, idx_plus=idx + 1)
            full_selector = f"{grid_selector} {sel_formatted}"
            try:
                await page.wait_for_selector(full_selector, timeout=2000)
                valid_selector = sel_formatted
                break
            except:
                continue

        if not valid_selector:
            print(f"All selector strategies failed for column {idx}: {header}")
            raise Exception(f"Could not resolve selector for column {idx}")

        sample_cells = []
        row_locator = page.locator(f"{grid_selector} [role='row'], {grid_selector} tr")
        row_count = await row_locator.count()

        for i in range(min(row_count, 10)):
            row = row_locator.nth(i)
            cell = None

            for sel in possible_selectors:
                sel_formatted = sel.format(idx=idx, idx_plus=idx + 1)
                candidate = row.locator(sel_formatted)
                try:
                    await candidate.wait_for(state="attached", timeout=1000)
                    try:
                        await candidate.wait_for(state="visible", timeout=1000)
                        cell = candidate
                        break
                    except:
                        nested = candidate.locator("*")
                        await nested.first.wait_for(state="visible", timeout=1000)
                        cell = nested.first
                        break
                except:
                    continue

            if not cell:
                print(f"Could not resolve column {idx} inside row {i}")
                continue

            try:
                await cell.wait_for(state="visible", timeout=1000)
                txt = await cell.inner_text()
                if not txt.strip():
                    txt = await cell.evaluate("el => el.value || el.textContent?.trim() || ''")
                sample_cells.append(txt.strip())
            except Exception as e:
                print(f"Failed to get data from cell at row {i} using selector '{valid_selector}': {e}")
                continue

            # Early bailout after first 3 samples if content is likely non-useful
            if i == 2:
                sample_trimmed = [c.strip().lower() for c in sample_cells if c.strip()]
                unique_values = set(sample_trimmed)
                if not sample_trimmed or unique_values <= {"true", "false", "yes", "no", "on", "off"}:
                    print(f"Early skip of column {idx} ('{header}') detected as checkbox/toggle.")
                    valid_selector = None  # prevent this column from being added
                    break

        if not valid_selector or not sample_cells:
            continue


        def contains_date(txt):
            return bool(re.search(
                r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}|"
                r"[A-Za-z]+\s\d{1,2},\s\d{4}|\d{2}-[A-Za-z]{3}-\d{4}",
                txt
            ))

        col_type = "text"
        variables = []

        if all(c.lower() in {"true", "false", "yes", "no"} for c in sample_cells):
            col_type = "boolean"
        elif all(c.replace(",", "").replace(".", "").isdigit() for c in sample_cells):
            col_type = "number"
        elif all(contains_date(c) for c in sample_cells):
            col_type = "date"
        elif sum(1 for c in sample_cells if contains_date(c)) / len(sample_cells or [1]) >= 0.6:
            col_type = "text_with_date"
            seen_formats = set()
            for c in sample_cells:
                for match in re.findall(
                    r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}|"
                    r"[A-Za-z]+\s\d{1,2},\s\d{4}|\d{2}-[A-Za-z]{3}-\d{4}", c
                ):
                    fmt = infer_date_format(match)
                    if fmt not in seen_formats:
                        seen_formats.add(fmt)
                        variables.append({ "name": f"date{len(variables)+1}", "type": "date", "format": fmt })

        headers.append({
            "header": header,
            "type": col_type,
            **({"variables": variables} if variables else {})
        })

        mappings.append({
            "header": header,
            "columnIndex": idx,
            "selector": valid_selector
        })

    return headers, mappings

async def validate_selector(page, selector: str) -> bool:
    try:
        await page.wait_for_selector(selector, timeout=3000)
        return True
    except:
        return False

async def get_verified_selector_from_outer_html(page, outer_html: str) -> str:
    from common.selectorHelper import getSmartSelector

    # Parse the outerHTML to get tag and class info
    soup = BeautifulSoup(outer_html, "html.parser")
    tag = soup.find()
    if not tag:
        return ""

    candidates = await page.query_selector_all(tag.name)
    for el in candidates:
        try:
            el_html = await el.evaluate("el => el.outerHTML")
            if el_html.strip() == outer_html.strip():
                # Call JS-side getSmartSelector if available
                return await el.evaluate("el => window.getSmartSelector ? getSmartSelector(el) : ''")
        except:
            continue

    return ""  # fallback if not found

def infer_type(cells: list[str]) -> str:
    import re
    BOOLEAN_VALUES = {"true", "false", "yes", "no", "on", "off"}
    date_patterns = [
        r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", r"\d{4}-\d{2}-\d{2}", r"[A-Za-z]+\s\d{1,2},\s\d{4}", r"\d{2}-[A-Za-z]{3}-\d{4}"
    ]

    if all(c.lower() in BOOLEAN_VALUES for c in cells): return "boolean"
    if all(c.replace(',', '').replace('.', '').isdigit() for c in cells): return "number"
    if all(any(re.search(p, c) for p in date_patterns) for c in cells): return "date"

    date_count = sum(1 for c in cells if any(re.search(p, c) for p in date_patterns))
    if date_count / len(cells) >= 0.6: return "text_with_date"

    return "text"

async def infer_headers_and_types(page, grid_selector: str):
    grid = page.locator(grid_selector)
    header_els = await grid.locator("[role='columnheader'], th").all()
    headers = []

    for col_index, el in enumerate(header_els):
        text = (await el.inner_text()).strip()
        if not text:
            text = await el.get_attribute("aria-label") or f"Column {col_index+1}"

        # Extract 10 sample cells for inference
        col_cells = await page.eval_on_selector_all(
            f"{grid_selector} [role='row'] [role='cell']:nth-child({col_index+1})",
            "els => els.map(el => el.innerText.trim()).filter(Boolean).slice(0, 10)"
        )

        def is_boolean(val): return val.lower() in {"true", "false", "yes", "no"}
        def is_number(val): return val.replace(',', '').replace('.', '').isdigit()
        def contains_date(val): return bool(re.search(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{2}-[A-Za-z]{3}-\d{4}|[A-Za-z]+\s\d{1,2},\s\d{4}", val))

        col_type = "text"
        variables = []

        if col_cells and all(is_boolean(v) for v in col_cells):
            col_type = "boolean"
        elif col_cells and all(is_number(v) for v in col_cells):
            col_type = "number"
        elif col_cells and all(contains_date(v) for v in col_cells):
            col_type = "date"
        elif col_cells:
            # Check if date embedded in text (text_with_date)
            count = sum(1 for val in col_cells if contains_date(val))
            if count / len(col_cells) >= 0.6:
                col_type = "text_with_date"
                seen_formats = set()
                for val in col_cells:
                    matches = re.findall(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{2}-[A-Za-z]{3}-\d{4}|[A-Za-z]+\s\d{1,2},\s\d{4}", val)
                    for date_str in matches:
                        fmt = infer_date_format(date_str)
                        if fmt not in seen_formats:
                            seen_formats.add(fmt)
                            variables.append({
                                "name": f"date{len(variables)+1}",
                                "type": "date",
                                "format": fmt
                            })

        headers.append({
            "header": text,
            "type": col_type,
            **({"variables": variables} if variables else {})
        })

    return headers

async def extract_row_samples(page, grid_selector: str):
    rows = await page.locator(f"{grid_selector} [role='row']").all()
    samples = []

    for row in rows[:3]:
        cells = await row.locator("[role='cell'], td").all()
        values = []
        for cell in cells:
            try:
                txt = await cell.inner_text()
                values.append(txt.strip())
            except:
                values.append("")
        samples.append(values)

    return samples

async def matches_filter(row_data, filt, col_type="text"):
    col = filt.get("column")
    op = filt.get("operator", "").lower()
    val = filt.get("value", "")
    var = filt.get("variable", "")
    actual_val = row_data.get(col, "")
    await state.log_to_status(f"Filtering column '{col}' with op '{op}' against value '{val}' (actual: '{actual_val}')")
    try:
        # Boolean or image
        if op in ["is true", "is false"]:
            is_truthy = bool(actual_val)
            return is_truthy if op == "is true" else not is_truthy

        # Normalize for string ops
        actual_val_str = str(actual_val).strip().lower()
        val_str = str(val).strip().lower()

        if op == "contains":
            return val_str in actual_val_str
        elif op == "does not contain":
            return val_str not in actual_val_str
        elif op == "equals":
            return actual_val_str == val_str
        elif op == "does not equal":
            return actual_val_str != val_str
        elif op == "starts with":
            return actual_val_str.startswith(val_str)
        elif op == "does not start with":
            return not actual_val_str.startswith(val_str)
        elif op == "ends with":
            return actual_val_str.endswith(val_str)
        elif op == "does not end with":
            return not actual_val_str.endswith(val_str)
        elif op == "regex":
            return re.search(val, actual_val_str) is not None

        # Number/Date comparison
        ops = {
            ">": lambda a, b: a > b,
            "<": lambda a, b: a < b,
            ">=": lambda a, b: a >= b,
            "<=": lambda a, b: a <= b,
            "=": lambda a, b: a == b,
            "==": lambda a, b: a == b,
            "!=": lambda a, b: a != b,
        }

        if col_type == "date":
            actual_val = dateparser.parse(actual_val)
            val = dateparser.parse(val)
        elif col_type == "number":
            actual_val = float(actual_val)
            val = float(val)
        else:
            # fallback if type unknown
            actual_val = str(actual_val).strip().lower()
            val = str(val).strip().lower()

        return ops[op](actual_val, val) if op in ops else False

    except Exception:
        return False

