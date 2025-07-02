import asyncio
import json
import logging
from pathlib import Path
from playwright.async_api import async_playwright, Page
from common import state
from common.browserutil import launch_chrome
from common.gridHelper import matches_filter
from common.selectorHelper import call_selector_recovery_api, confirm_selector_worked
import operator
from dateutil import parser as dateparser

ops = {
    ">": operator.gt,
    "<": operator.lt,
    ">=": operator.ge,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
    "contains": lambda a, b: b.lower() in a.lower() if isinstance(a, str) else False,
    "does not contain": lambda a, b: b.lower() not in a.lower() if isinstance(a, str) else True,
    "equals": lambda a, b: a.lower() == b.lower() if isinstance(a, str) else False,
    "does not equal": lambda a, b: a.lower() != b.lower() if isinstance(a, str) else False,
    "is true": lambda a, _: str(a).strip().lower() in ["true", "yes", "1"],
    "is false": lambda a, _: str(a).strip().lower() in ["false", "no", "0"],
}

logger = logging.getLogger("botflows-player")
logging.basicConfig(level=logging.INFO)

steps_by_parent = {}

def get_locator(page: Page, sel: str, source: str):
    if source == "xpath":
        return page.locator(f"xpath={sel}")
    elif source == "css" or source == "dom-path":
        return page.locator(sel)
    elif source == "id" and sel.startswith("#"):
        return page.locator(sel)
    else:
        return page.locator(sel)

async def _perform_action(page: Page, action: str, selector=None, value=None, key=None, selectors=None, retries=3):
    await asyncio.sleep(1)

    async def try_action(target_page: Page, sel, source_hint=None):
        locator = get_locator(target_page, sel, source_hint or "")

        if action.lower() == "click":
            await locator.first.wait_for(state="visible", timeout=5000)
            return await locator.first.click(timeout=5000)
        elif action.lower() == "dblclick":
            await locator.first.wait_for(state="visible", timeout=5000)
            return await locator.first.dblclick(timeout=5000)
        elif action.lower() == "type":
            await locator.first.wait_for(state="attached", timeout=5000)
            await locator.first.focus()
            return await locator.first.type(value or "")
        elif action.lower() == "change":
            await locator.first.wait_for(state="attached", timeout=5000)
            await locator.first.focus()
            return await locator.first.fill(value or "")
        elif action.lower() == "press":
            return await target_page.keyboard.press(key)
        elif action.lower() == "select":
            await locator.first.wait_for(state="attached", timeout=5000)
            return await locator.first.select_option(value)
        elif action.lower() in ["mousedown", "focus", "blur"]:
            await locator.first.wait_for(state="attached", timeout=5000)
            return await locator.first.dispatch_event(action)

    # 🔍 Log available input fields for debug
    try:
        inputs = await page.query_selector_all("input")
        for i, el in enumerate(inputs):
            id_ = await el.get_attribute("id")
            type_ = await el.get_attribute("type")
            cls = await el.get_attribute("class")
            logger.info(f"[Input #{i}] id={id_}, type={type_}, class={cls}")
    except Exception as scan_err:
        logger.warning(f"[Input scan error] {scan_err}")

    # ✅ Pre-check: Wait for any verified selector if present
    if selectors:
        first_verified = next((s for s in selectors if s.get("verified")), None)
        if first_verified:
            try:
                await page.wait_for_selector(first_verified["selector"], timeout=10000)
                logger.info(f"Pre-check success: {first_verified['selector']}")
            except Exception as wait_ex:
                logger.warning(f"Pre-check failed for {first_verified['selector']}: {wait_ex}")

    for attempt in range(1, retries + 1):
        try:
            await try_action(page, selector)
            logger.info(f"Action '{action}' succeeded on attempt {attempt}: {selector}")
            return
        except Exception as e:
            logger.warning(f"Attempt {attempt} failed: {action} / {selector} => {e}")

            for frame in page.frames:
                if frame == page.main_frame:
                    continue
                try:
                    await try_action(frame, selector)
                    logger.info(f"[Frame] Success inside: {frame.url}")
                    return
                except:
                    continue

            if attempt == retries:
                if selectors:
                    for sel in selectors:
                        alt_sel = sel["selector"] if isinstance(sel, dict) else sel
                        source = sel.get("source") if isinstance(sel, dict) else ""
                        try:
                            logger.info(f"[Trying fallback selector] {alt_sel} (source: {source})")
                            await try_action(page, alt_sel, source)
                            logger.info(f"[Fallback Success] {alt_sel}")
                            return
                        except Exception as fe:
                            logger.warning(f"[Fallback selector failed] {alt_sel} => {fe}")

                # Final fallback: Recovery API
                try:
                    source_hint = ""
                    if selectors:
                        # Find best-matching selector from list for source hint
                        for sel in selectors:
                            if sel.get("selector") == selector:
                                source_hint = sel.get("source", "")
                                break

                    try:
                        if source_hint == "xpath":
                            tag = await page.evaluate("""
                                (sel) => {
                                    const result = document.evaluate(sel, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
                                    const el = result.singleNodeValue;
                                    return el?.tagName?.toLowerCase() || '';
                                }
                            """, selector)
                            el_id = await page.evaluate("""
                                (sel) => {
                                    const result = document.evaluate(sel, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
                                    const el = result.singleNodeValue;
                                    return el?.id || '';
                                }
                            """, selector)
                            element_text = await page.evaluate("""
                                (sel) => {
                                    const result = document.evaluate(sel, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
                                    const el = result.singleNodeValue;
                                    return el?.innerText || '';
                                }
                            """, selector)
                        else:
                            tag = await page.evaluate("(sel) => { const el = document.querySelector(sel); return el?.tagName?.toLowerCase() || ''; }", selector)
                            el_id = await page.evaluate("(sel) => { const el = document.querySelector(sel); return el?.id || ''; }", selector)
                            element_text = await page.evaluate("(sel) => { const el = document.querySelector(sel); return el?.innerText || ''; }", selector)
                    except Exception as ex:
                        logger.warning(f"[safe_evaluate failed] {ex}")
                        tag = el_id = element_text = ""

                    new_selector = await call_selector_recovery_api(
                        url=page.url,
                        failed_selector=selector,
                        tag=tag,
                        text=element_text,
                        el_id=el_id
                    )
                    if new_selector:
                        logger.info(f"Recovered selector from API: {new_selector}")
                        await try_action(page, new_selector)
                        await confirm_selector_worked(url=page.url, original_selector=selector)
                        return
                except Exception as api_ex:
                    logger.warning(f"[Recovery API] Failed: {api_ex}")

        await asyncio.sleep(1)

    raise Exception(f"All attempts failed for action '{action}' on selector: {selector}")

async def handle_step(step: dict, page: Page):
    step_type = step.get("type", "").lower()
    step_id = step.get("id")

    label = step.get("label")
    if label:
        logger.info(f"Step: {label}")

    if step_type == "navigate":
        await page.goto(step["url"])
        await asyncio.sleep(1)

    elif step_type == "uiaction":
        selector = step.get("selector")
        selectors = step.get("selectors", [])
        action = step.get("action")
        value = step.get("value")
        key = step.get("key")

        tried = set()

        def should_try(sel):
            return sel and sel not in tried

        try:
            if should_try(selector):
                tried.add(selector)
                await _perform_action(page, action=action, selector=selector, value=value, key=key, selectors=selectors, retries=1)
                return
        except Exception as e:
            logger.warning(f"[Primary selector failed] {selector} => {e}")

        for alt in selectors:
            if isinstance(alt, dict):
                alt_selector = alt.get("selector")
                source = alt.get("source", "")
            else:
                alt_selector = alt
                source = ""

            try:
                if should_try(alt_selector):
                    tried.add(alt_selector)
                    logger.info(f"[Trying fallback selector] {alt_selector} (source: {source})")
                    await _perform_action(page, action=action, selector=alt_selector, value=value, key=key, selectors=selectors, retries=1)
                    return
            except Exception as e:
                logger.warning(f"[Fallback selector failed] {alt_selector} => {e}")

        raise Exception(f"All selectors failed for action: {action}")

    # all other step types remain unchanged...

    elif step_type == "gridextract":
        if not hasattr(page.context, "_botflows_extractions"):
            page.context._botflows_extractions = {}
        page.context._botflows_extractions[step["id"]] = step
        logger.info(f"[gridExtract] Registered extract step: {step['name']}")

    elif step_type == "loop":
        for child in steps_by_parent.get(step_id, []):
            await handle_step(child, page)

    elif step_type == "counterloop":
        loop_count = step.get("count", 1)
        for i in range(loop_count):
            logger.info(f"[counterLoop] Iteration {i + 1}")
            for child in steps_by_parent.get(step_id, []):
                await handle_step(child, page)

    elif step_type == "dataloop":
        source_id = step.get("source")
        extract = getattr(page.context, "_botflows_extractions", {}).get(source_id)
        if not extract:
            logger.warning(f"[dataLoop] Extract step '{source_id}' not found.")
            return

        grid_selector = extract.get("gridSelector")
        row_selector = extract.get("rowSelector")
        column_mappings = extract.get("columnMappings", [])
        filters = extract.get("filters", [])

        logger.info(f"Starting dataLoop on grid: {grid_selector}")
        try:
            await page.wait_for_selector(grid_selector, state="visible", timeout=5000)
            try:
                await page.wait_for_selector(row_selector, state="visible", timeout=3000)
            except:
                fallback = f"{grid_selector} tr"
                try:
                    await page.wait_for_selector(fallback, state="visible", timeout=3000)
                    logger.warning(f"[RowSelector Fallback] Switching from '{row_selector}' to '{fallback}'")
                    row_selector = fallback
                except:
                    raise Exception(f"Row selector failed: {row_selector}")
            rows = await page.query_selector_all(row_selector)
            logger.info(f"Found {len(rows)} rows in grid")

            if filters:
                filtered_rows = []
                for row in rows:
                    row_data = {}
                    # html = await row.inner_html()
                    # print("\n======= ROW HTML =======\n", html)
                    for col in column_mappings:
                        header_obj = col.get("header", {})
                        header_text = header_obj.get("header", f"col_{col.get('columnIndex')}")
                        header_type = header_obj.get("type", "text")
                        col_selector = col.get("selector")

                        # Try selector first if available
                        cell = await row.query_selector(col_selector) if col_selector else None

                        # Fallback to nth-child if needed
                        if not cell and "columnIndex" in col:
                            index = col["columnIndex"]
                            fallback_selector = f'td:nth-child({index + 1})'
                            cell = await row.query_selector(fallback_selector)

                        if cell:
                            if header_type == "img":
                                img = await cell.query_selector("img")
                                row_data[header_text] = img is not None
                            else:
                                text = await cell.inner_text()
                                row_data[header_text] = text
                        else:
                            row_data[header_text] = None

                    passed_filters = True
                    for filt in filters:
                        if not matches_filter(row_data, filt):
                            passed_filters = False
                            break

                    if passed_filters:
                        filtered_rows.append(row)

                rows = filtered_rows
                logger.info(f"{len(rows)} rows remain after filtering")

            for idx, row in enumerate(rows):
                logger.info(f"[dataLoop] Row {idx + 1}")
                for child in steps_by_parent.get(step_id, []):
                    await handle_step(child, page)
        except Exception as ex:
            logger.error(f"Error during dataLoop playback: {ex}")

    elif step_type == "gridloop":
        grid_selector = step.get("gridSelector")
        row_selector = step.get("rowSelector")
        filters = step.get("filters", [])
        logger.info(f"Starting gridLoop on grid: {grid_selector}")
        try:
            await page.wait_for_selector(grid_selector, state="visible", timeout=5000)
            await page.wait_for_selector(row_selector, state="visible", timeout=5000)
            rows = await page.query_selector_all(row_selector)
            logger.info(f"Found {len(rows)} rows in grid")

            for idx, row in enumerate(rows):
                logger.info(f"[gridLoop] Row {idx + 1}")
                for child in steps_by_parent.get(step_id, []):
                    await handle_step(child, page)
        except Exception as ex:
            logger.error(f"Error during gridLoop playback: {ex}")

async def replay_flow(json_str: str):
    state.is_replaying = True
    flow = json.loads(json_str)

    global steps_by_parent
    steps_by_parent = {}
    for step in flow:
        pid = step.get("parentId")
        if pid:
            steps_by_parent.setdefault(pid, []).append(step)

    for children in steps_by_parent.values():
        children.sort(key=lambda x: x.get("timestamp", 0))

    async with async_playwright() as p:
        browser = await launch_chrome(p)
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = await context.new_page()

        top_level_steps = [s for s in flow if not s.get("parentId")]
        for step in top_level_steps:
            await handle_step(step, page)

        logger.info("Replay complete.")
        await browser.close()
        state.is_replaying = False
