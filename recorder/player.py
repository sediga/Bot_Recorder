import asyncio
import json
import logging
from pathlib import Path
from playwright.async_api import async_playwright, Page
from common import state
from common.browserutil import launch_chrome
from common.selectorHelper import call_selector_recovery_api, confirm_selector_worked

logger = logging.getLogger("botflows-player")
logging.basicConfig(level=logging.INFO)


async def _perform_action(page: Page, action: str, selector=None, value=None, key=None, retries=3):
    await asyncio.sleep(1)

    async def try_action(target_page: Page, sel):
        locator = target_page.locator(sel)

        if action == "click":
           await target_page.wait_for_selector(sel, state="visible", timeout=5000)
           return await target_page.click(sel, timeout=5000)
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

            # Try inside iframes
            for frame in page.frames:
                if frame == page.main_frame:
                    continue
                try:
                    await try_action(frame, selector)
                    logger.info(f"[Frame] Success inside: {frame.url}")
                    return
                except:
                    continue

            # Recovery API fallback (only on final failure)
            if attempt == retries:
                try:
                    element_text = await page.evaluate("(sel) => { const el = document.querySelector(sel); return el?.innerText || ''; }", selector)
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


async def handle_step(step: dict, page: Page):
    step_type = step.get("type")
    label = step.get("label")
    if label:
        logger.info(f"▶ Step: {label}")

    if step_type == "navigate":
        await page.goto(step["url"])
        await asyncio.sleep(1)

    elif step_type == "uiAction":
        selector = step.get("selector")
        improved = step.get("improvedSelector")
        action = step.get("action")
        value = step.get("value")
        key = step.get("key")

        # Try the main selector first
        try:
            await _perform_action(page, action=action, selector=selector, value=value, key=key)
        except Exception as e:
            logger.warning(f"[Primary selector failed] {selector} => {e}")
            if improved and improved != selector:
                try:
                    logger.info(f"🔁 Trying improvedSelector: {improved}")
                    await _perform_action(page, action=action, selector=improved, value=value, key=key)
                except Exception as e2:
                    logger.error(f"[Improved selector failed] {improved} => {e2}")
                    raise e2
            else:
                raise e

    elif step_type == "counterloop" and step.get("action") == "counterloop":
        count = step.get("criteria", {}).get("count", 1)
        logger.info(f"🔄 Counter loop '{step.get('source')}' for {count} iterations")
        for i in range(count):
            logger.info(f"→ Loop iteration {i + 1}/{count}")
            for sub_step in step.get("steps", []):
                await handle_step(sub_step, page)

    elif step_type == "dataLoop":
        grid_selector = step.get("gridSelector")
        row_selector = step.get("rowSelector", "tr")
        column_mappings = step.get("columnMappings", [])
        actions_per_row = step.get("actionsPerRow", [])
        filters = step.get("filters", [])

        logger.info(f"🔁 Starting dataLoop on grid: {grid_selector}")
        try:
            await page.wait_for_selector(grid_selector, state="visible", timeout=5000)
            grid_handle = await page.query_selector(grid_selector)
            if not grid_handle:
                logger.error(f"Grid container not found: {grid_selector}")
                return

            await page.wait_for_selector(row_selector, state="visible", timeout=5000)
            rows = await page.query_selector_all(row_selector)
            logger.info(f"Found {len(rows)} rows in grid")

            if filters:
                filtered_rows = []
                for row in rows:
                    row_text = await row.inner_text()
                    if all(filt.lower() in row_text.lower() for filt in filters):
                        filtered_rows.append(row)
                rows = filtered_rows
                logger.info(f"{len(rows)} rows remain after filtering")

            temp_table = []

            for idx, row in enumerate(rows):
                logger.info(f"Processing row {idx + 1}/{len(rows)}")
                row_data = {}

                for action in actions_per_row:
                    action_type = action.get("action")
                    relative_selector = action.get("selector", "")
                    full_selector = f"{row_selector}:nth-child({idx + 1}) {relative_selector}" if relative_selector else row_selector

                    if action_type == "extract":
                        cell_texts = []
                        for col in column_mappings:
                            col_selector = col.get("selector")
                            cell = await row.query_selector(col_selector)
                            text = await cell.inner_text() if cell else ""
                            cell_texts.append({col.get("header"): text})
                            row_data[col.get("header")] = text

                        logger.info(f"Extracted data: {cell_texts}")
                    else:
                        await _perform_action(page, action_type, full_selector)

                if row_data:
                    temp_table.append(row_data)

            print(f"Final extracted table: {temp_table}")

        except Exception as ex:
            logger.error(f"Error during dataLoop playback: {ex}")

async def replay_flow(json_str: str):
    state.is_replaying = True
    flow = json.loads(json_str)

    async with async_playwright() as p:
        browser = await launch_chrome(p)
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = await context.new_page()

        for step in flow:
            await handle_step(step, page)

        logger.info("Replay complete.")
        await browser.close()
        state.is_replaying = False


# Example usage:
# asyncio.run(replay_flow(Path("recordings/final_flow.json").read_text()))
