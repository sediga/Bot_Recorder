import asyncio
import json
import logging
from pathlib import Path
from playwright.async_api import async_playwright, Page
from common import state
from common.browserutil import launch_chrome
from common.selectorHelper import call_selector_recovery_api, confirm_selector_worked
import operator

ops = {
    ">": operator.gt,
    "<": operator.lt,
    ">=": operator.ge,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
    "contains": lambda a, b: b.lower() in a.lower() if isinstance(a, str) else False
}

logger = logging.getLogger("botflows-player")
logging.basicConfig(level=logging.INFO)

steps_by_parent = {}

async def _perform_action(page: Page, action: str, selector=None, value=None, key=None, retries=3):
    await asyncio.sleep(1)

    async def try_action(target_page: Page, sel):
        locator = target_page.locator(sel)

        if action == "click":
            await target_page.wait_for_selector(sel, state="visible", timeout=5000)
            return await target_page.click(sel, timeout=5000)
        if action == "dblclick":
            await target_page.wait_for_selector(sel, state="visible", timeout=5000)
            return await target_page.dblclick(sel, timeout=5000)
        elif action == "type":
            await locator.first.wait_for(state="attached", timeout=5000)
            await locator.first.focus()
            return await locator.first.type(value or "")
        elif action == "change":
            await locator.first.wait_for(state="attached", timeout=5000)
            await locator.first.focus()
            return await locator.first.fill(value or "")
        elif action == "press":
            return await target_page.keyboard.press(key)
        elif action == "select":
            await locator.first.wait_for(state="attached", timeout=5000)
            return await locator.first.select_option(value)
        elif action in ["mousedown", "focus", "blur"]:
            await locator.first.wait_for(state="attached", timeout=5000)
            return await locator.first.dispatch_event(action)

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
                try:
                    try:
                        locator = page.locator(selector).first
                        element_text = await locator.evaluate("el => el?.innerText || ''")
                        tag = await locator.evaluate("el => el?.tagName?.toLowerCase() || ''")
                        el_id = await locator.evaluate("el => el?.id || ''")
                    except Exception as ex:
                        logger.warning(f"[Locator evaluate failed] {ex}")
                        element_text = tag = el_id = ""
                    tag = await page.evaluate("(sel) => { const el = document.querySelector(sel); return el?.tagName?.toLowerCase() || ''; }", selector)
                    el_id = await page.evaluate("(sel) => { const el = document.querySelector(sel); return el?.id || ''; }", selector)

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
    step_type = step.get("type")
    label = step.get("label")
    if label:
        logger.info(f"Step: {label}")

    if step_type == "navigate":
        await page.goto(step["url"])
        await asyncio.sleep(1)

    elif step_type == "uiAction":
        selector = step.get("selector")
        improved = step.get("improvedSelector")
        devToolsSelector = step.get("devToolsSelector")
        action = step.get("action")
        value = step.get("value")
        key = step.get("key")

        try:
            await _perform_action(page, action=action, selector=devToolsSelector, value=value, key=key, retries=2)
        except Exception as e:
            logger.warning(f"[Primary selector failed] {devToolsSelector} => {e}")
            if improved and improved != devToolsSelector:
                try:
                    logger.info(f"Trying improvedSelector: {improved}")
                    await _perform_action(page, action=action, selector=improved, value=value, key=key, retries=1)
                except Exception as e2:
                    logger.error(f"[Improved selector failed] {improved} => {e2}")
                    if improved != selector:
                        try:
                            logger.info(f"Trying normal selector: {selector}")
                            await _perform_action(page, action=action, selector=selector, value=value, key=key, retries=1)
                        except Exception as e3:
                            logger.error(f"[Dev Tool Selector Failed] {selector}")
            elif selector and devToolsSelector != selector :
                try:
                    logger.info(f"Teying dev tool selector: {selector}")
                    await _perform_action(page, action=action, selector=selector, value=value, key=key, retries=1)
                except Exception as e3:
                    logger.error(f"[Dev Tool Selector Failed] {selector}")
            else:
                raise e

    elif step_type == "smartExtract":
        if not hasattr(page.context, "_botflows_extractions"):
            page.context._botflows_extractions = {}
        page.context._botflows_extractions[step["id"]] = step
        logger.info(f"[smartExtract] Registered extract step: {step['name']}")

    elif step_type == "loop":
        # unchanged
        pass

    elif step_type == "counterloop" and step.get("action") == "counterloop":
        # unchanged
        pass

    elif step_type == "dataLoop":
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
            await page.wait_for_selector(row_selector, state="visible", timeout=5000)
            rows = await page.query_selector_all(row_selector)
            logger.info(f"Found {len(rows)} rows in grid")

            if filters:
                filtered_rows = []
                for row in rows:
                    row_text = await row.inner_text()
                    row_data = {}

                    for col in column_mappings:
                        header = col.get("header")
                        col_selector = col.get("selector")
                        cell = await row.query_selector(col_selector)
                        text = await cell.inner_text() if cell else ""
                        row_data[header] = text

                    passed_filters = True
                    for filt in filters:
                        col = filt.get("column")
                        op = filt.get("operator")
                        val = filt.get("value")
                        actual_val = row_data.get(col)

                        try:
                            if op in [">", "<", ">=", "<=", "==", "!="]:
                                passed = ops[op](float(actual_val), float(val))
                            elif op == "contains":
                                passed = ops[op](str(actual_val), str(val))
                            else:
                                passed = False
                        except Exception:
                            passed = False

                        if not passed:
                            passed_filters = False
                            break

                    if passed_filters:
                        filtered_rows.append(row)

                rows = filtered_rows
                logger.info(f"{len(rows)} rows remain after filtering")

            for idx, row in enumerate(rows):
                logger.info(f"[dataLoop] Row {idx + 1}")
                for action in steps_by_parent.get(step["id"], []):
                    sel = action.get("devToolsSelector") or action.get("selector") or action.get("improvedSelector")
                    act = action.get("action")
                    await _perform_action(page, act, sel)
        except Exception as ex:
            logger.error(f"Error during dataLoop playback: {ex}")

    elif step_type == "gridLoop":
        # unchanged
        pass

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
