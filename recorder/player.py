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
        if action == "click":
            await target_page.wait_for_selector(sel, state="visible", timeout=5000)
            return await target_page.click(sel, timeout=5000)
        elif action == "type":
            await target_page.wait_for_selector(sel, state="attached", timeout=5000)
            await target_page.focus(sel)
            return await target_page.type(sel, value or "")
        elif action == "change":
            await target_page.wait_for_selector(sel, state="attached", timeout=5000)
            await target_page.focus(sel)
            return await target_page.fill(sel, value or "")
        elif action == "press":
            return await target_page.keyboard.press(key)
        elif action == "select":
            await target_page.wait_for_selector(sel, state="attached", timeout=5000)
            return await target_page.select_option(sel, value)
        elif action in ["mousedown", "focus", "blur"]:
            await target_page.wait_for_selector(sel, state="attached", timeout=5000)
            return await target_page.dispatch_event(sel, action)

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
                    element_text = await page.evaluate(f"""() => {{
                        const el = document.querySelector("{selector}");
                        return el?.innerText || "";
                    }}""")
                    tag = await page.evaluate(f"""() => {{
                        const el = document.querySelector("{selector}");
                        return el?.tagName?.toLowerCase() || "";
                    }}""")
                    el_id = await page.evaluate(f"""() => {{
                        const el = document.querySelector("{selector}");
                        return el?.id || "";
                    }}""")

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
    selector = step.get("improvedSelector") or step.get("selector")

    if step_type == "uiAction":
        await _perform_action(
            page,
            action=step.get("action"),
            selector=selector,
            value=step.get("value"),
            key=step.get("key")
        )
    elif step_type == "navigate":
        await page.goto(step["url"])
        await asyncio.sleep(1)
    elif step_type == "counterloop" and step.get("action") == "counterloop":
        count = step.get("criteria", {}).get("count", 1)
        logger.info(f"Starting loop '{step.get('source')}' for {count} iterations")
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

        logger.info(f"Starting dataLoop on grid: {grid_selector}")

        try:
            await page.wait_for_selector(grid_selector, state="visible", timeout=5000)
            grid_handle = await page.query_selector(grid_selector)
            if not grid_handle:
                logger.error(f"Grid container not found for selector: {grid_selector}")
                return
            await page.wait_for_selector(row_selector, state="visible", timeout=5000)
            rows = await page.query_selector_all(row_selector)
            logger.info(f"Found {len(rows)} rows in grid.")

            if filters:
                filtered_rows = []
                for row in rows:
                    row_text = await row.inner_text()
                    if all(filt.lower() in row_text.lower() for filt in filters):
                        filtered_rows.append(row)
                rows = filtered_rows
                logger.info(f"{len(rows)} rows remain after filtering.")

            temp_table = []

            for idx, row in enumerate(rows):
                logger.info(f"Processing row {idx + 1}/{len(rows)}")

                # This dict will hold the column-value pairs for this row
                row_data = {}

                for action in actions_per_row:
                    action_type = action.get("action")
                    relative_selector = action.get("selector", "")

                    # Compose full selector relative to this row
                    full_selector = relative_selector
                    if relative_selector:
                        try:
                            full_selector = f"{row_selector}:nth-child({idx + 1}) {relative_selector}"
                        except Exception:
                            full_selector = relative_selector

                    if action_type == "extract":
                        cell_texts = []
                        for col in column_mappings:
                            col_selector = col.get("selector")
                            cell = await row.query_selector(col_selector)
                            text = await cell.inner_text() if cell else ""
                            cell_texts.append({col.get("header"): text})
                            
                            # Add to row_data using header as key
                            row_data[col.get("header")] = text

                        logger.info(f"Extracted data from row {idx + 1}: {cell_texts}")
                    else:
                        # For other actions like click/open, perform the action on relative selector
                        await _perform_action(page, action_type, full_selector)
                
                # Append row_data dict to temp_table after processing all columns for this row
                if row_data:
                    temp_table.append(row_data)
            print(f"Final extracted table data: {temp_table}")
            # Now temp_table is a list of dicts like:
            # [
            #   {'Name': 'John', 'Age': '30', ...},
            #   {'Name': 'Jane', 'Age': '25', ...},
            #    ...
            # ]

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
