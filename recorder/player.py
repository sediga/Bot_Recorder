import asyncio
import json
import logging
import operator
import re
import logging
from pathlib import Path
from urllib.parse import urlparse
from matplotlib.pyplot import step
from playwright.async_api import async_playwright, Page
from common import state
from common.browserutil import close_chrome, launch_chrome, launch_preview_window, launch_replay_window
from common.gridHelper import matches_filter
from dateutil import parser as dateparser
from common.selectorRecoveryHelper import *
from math import fabs
from playwright.async_api import Locator
from common.logger import get_logger
from common.commonUtilities import *
from common import state
from common.selectorHelper import call_selector_recovery_api, confirm_selector_worked

logger = get_logger(__name__)

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

steps_by_parent = {}

async def _perform_action(page, step, retries=2):
    await asyncio.sleep(1)

    action = step.get("action", "")
    selector = step.get("selector")
    selectors = step.get("selectors", [])
    label = step.get("label", "")
    dynamicValue = step.get("dynamicValue")
    if step and isinstance(dynamicValue, str):
        label += f" (Dynamic Value: {dynamicValue[:20]}...)"
    await state.log_to_status(f"Performing action: {label}")

    if step:
        frame_url = step.get("frameUrl")
        if frame_url:
            if page.url != frame_url:
                await state.log_to_status(f"Switching to frame: {frame_url}")
                frame = await wait_for_frame_url(page, frame_url)
                if frame and not frame.is_detached():
                    await frame.wait_for_selector("body", state="attached", timeout=5000)
                    logger.info(f"Scoping to iframe: {frame.url}")
                    page = frame
                else:
                    await state.log_to_status(f"Could not access frame: {frame_url}")
                    logger.warning(f"Could not access frame: {frame_url}")

    effective_selectors = selectors if selectors else [{"selector": selector}]

    sel_obj = effective_selectors[0] if isinstance(effective_selectors[0], dict) else {"selector": effective_selectors[0], "source": ""}
    sel = sel_obj["selector"] or selector
    source = sel_obj.get("source", "")

    try:
        await try_action(page, sel, step, source)
        logger.info(f"Action '{action}' succeeded: {sel}")
        return
    except Exception as e:
        await state.log_to_status(f"Initial attempt failed: {label} => {e}")
        logger.warning(f"Initial attempt failed: {action} / {sel} => {e}")
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            try:
                await state.log_to_status(f"Trying inside iframe: {frame.url}")
                await try_action(frame, sel, step, source)
                logger.info(f"[Frame] Success inside: {frame.url}")
                return
            except:
                await state.log_to_status(f"Failed inside iframe: {frame.url}")
                continue

    try:
        await state.log_to_status(f"Attempting recovery for action: {label}")
        selector_candidates = await generate_recovery_selectors(page, step)

        for candidate in selector_candidates:
            candidate_selector = candidate.get("selector")
            candidate_source = candidate.get("source", "")
            try:
                await state.log_to_status(f"Trying recovery selector: {candidate_selector} (source: {candidate_source})")
                await try_action(page, candidate_selector, step, candidate_source)
                logger.info(f"Recovered selector worked: {candidate_selector} (source: {candidate_source})")
                # await confirm_selector_worked(url=page.url, original_selector=sel)
                return
            except Exception as attempt_ex:
                await state.log_to_status(f"Recovery attempt failed: {candidate_selector} => {attempt_ex}")
                logger.warning(f"[Recovery attempt failed] {candidate_selector}: {attempt_ex}")
                continue
    except Exception as recovery_ex:
        logger.warning(f"[Recovery Logic] Failed: {recovery_ex}")
    await state.log_to_status(f"All recovery attempts failed for action: {label}")
    # ask api to help
    try:
        await state.log_to_status(f"Requesting API assistance for action: {label}")
        new_selectors = await call_selector_recovery_api(step)
        await state.log_to_status(f"API returned {len(new_selectors)} new selectors")
        for idx, sel_obj in enumerate(new_selectors):
            new_selector = sel_obj["selector"]
            logger.info(f"Trying recovered selector from API: {new_selector}")
            await state.log_to_status(f"Trying API recovered selector {idx + 1}: {new_selector}")
            
            await try_action(page, new_selector, step)
            await confirm_selector_worked(url=page.url, original_selector=sel)
            return
    except Exception as api_ex:
        await state.log_to_status(f"API recovery attempt failed for {idx + 1}: {api_ex}")
        logger.warning(f"[Recovery API] Failed: {api_ex}")

    raise Exception(f"All attempts failed for action '{action}' on selector: {sel}")

async def handle_step(step: dict, page: Page):
    step_type = step.get("type", "").lower()
    step_id = step.get("id")
    
    label = step.get("label", step.get("name", ""))

    await state.log_to_status(f"Handling step: {step_type} - {label or step_id}")
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
                await _perform_action(page, step)
                return
        except Exception as e:
            logger.warning(f"[Primary selector failed] {selector} => {e}")

        # for alt in selectors:
        #     if isinstance(alt, dict):
        #         alt_selector = alt.get("selector")
        #         source = alt.get("source", "")
        #     else:
        #         alt_selector = alt
        #         source = ""

        #     try:
        #         if should_try(alt_selector):
        #             tried.add(alt_selector)
        #             logger.info(f"[Trying fallback selector] {alt_selector} (source: {source})")
        #             step["selector"] = alt_selector  # temporarily override
        #             await _perform_action(page, step)
        #             return
        #     except Exception as e:
        #         logger.warning(f"[Fallback selector failed] {alt_selector} => {e}")

        logger.warning(f"All selectors failed for action: {action}")

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

    elif step_type == "dataloop" or step_type == "gridloop":
        source_id = step.get("source")
        extract = getattr(page.context, "_botflows_extractions", {}).get(source_id)
        if not extract:
            logger.warning(f"[dataLoop] Extract step '{source_id}' not found.")
            return

        try:
            extracted_rows = await extract_data_by_type(extract, page)

            logger.info(f"[dataLoop] {len(extracted_rows)} rows after filtering")

            for idx, row_data in enumerate(extracted_rows):
                logger.info(f"[dataLoop] Row {idx + 1}")
                page.context._botflows_row_data = row_data  # Optional: make it available for {{column}} replacement
                page.context._botflows_row_index = idx

                for child in steps_by_parent.get(step_id, []):
                    try:
                        await handle_step(child, page)
                    except Exception as ex:
                        logger.error(f"Error during dataLoop playback: {ex}")
                        break
        except Exception as ex:
            logger.error(f"Error during dataLoop playback: {ex}")

    # elif step_type == "gridloop":
    #     grid_selector = step.get("gridSelector")
    #     row_selector = step.get("rowSelector")
    #     filters = step.get("filters", [])
    #     logger.info(f"Starting gridLoop on grid: {grid_selector}")
    #     try:
    #         await page.wait_for_selector(grid_selector, state="visible", timeout=5000)
    #         await page.wait_for_selector(row_selector, state="visible", timeout=5000)
    #         rows = await page.query_selector_all(row_selector)
    #         logger.info(f"Found {len(rows)} rows in grid")

    #         for idx, row in enumerate(rows):
    #             logger.info(f"[gridLoop] Row {idx + 1}")
    #             for child in steps_by_parent.get(step_id, []):
    #                 await handle_step(child, page)
    #     except Exception as ex:
    #         logger.error(f"Error during gridLoop playback: {ex}")

def render_datatable(rows):
    if not rows:
        return "No data extracted."

    headers = list(rows[0].keys())
    col_widths = {h: max(len(h), *(len(str(r.get(h, ''))) for r in rows)) for h in headers}

    def format_row(row):
        return " | ".join(f"{str(row.get(h, '')).ljust(col_widths[h])}" for h in headers)

    divider = "-+-".join("-" * col_widths[h] for h in headers)

    lines = [
        format_row({h: h for h in headers}),  # Header row
        divider,
    ] + [format_row(row) for row in rows]

    return "\n".join(lines)

async def extract_data_by_type(source_step, page):
    extract_type = source_step.get("type")
    
    if extract_type == "gridExtract":
        return await extract_grid_data(
            page, source_step
        )
    
    elif extract_type == "apiExtract":
        # Placeholder for future logic
        logger.warning("[extract_data_by_type] API extract not implemented yet")
        return []

    elif extract_type == "excelExtract":
        # Placeholder for Excel sheet parsing
        logger.warning("[extract_data_by_type] Excel extract not implemented yet")
        return []

    else:
        logger.warning(f"[extract_data_by_type] Unknown extract type: {extract_type}")
        return []

# async def extract_grid_data(page, grid_selector, row_selector, column_mappings, filters=None):
#     """Extracts structured row data from a grid using mappings and optional filters."""
#     filters = filters or []
#     extracted_rows = []
#     filtered_row_elements = []

#     try:
#         await page.wait_for_selector(grid_selector, state="visible", timeout=5000)
#         try:
#             await page.wait_for_selector(row_selector, state="visible", timeout=3000)
#         except:
#             fallback = f"{grid_selector} tr"
#             await page.wait_for_selector(fallback, state="visible", timeout=3000)
#             logger.warning(f"[RowSelector Fallback] Switching from '{row_selector}' to '{fallback}'")
#             row_selector = fallback

#         rows = await page.query_selector_all(row_selector)
#         logger.info(f"[extract_grid_data] Found {len(rows)} rows in grid")

#         type_map = {
#             col.get("header", {}).get("header"): col.get("header", {}).get("type", "text")
#             for col in column_mappings
#         }

#         for row in rows:
#             row_data = {}
#             for col in column_mappings:
#                 header_obj = col.get("header", {})
#                 header_text = header_obj.get("header", f"col_{col.get('columnIndex')}")
#                 header_type = header_obj.get("type", "text")
#                 col_selector = col.get("selector")

#                 cell = await row.query_selector(col_selector) if col_selector else None

#                 # Fallback
#                 if not cell and "columnIndex" in col:
#                     index = col["columnIndex"]
#                     fallback_selector = f'td:nth-of-type({index + 1})'
#                     cell = await row.query_selector(fallback_selector)

#                 if cell:
#                     if header_type == "img":
#                         img = await cell.query_selector("img")
#                         row_data[header_text] = img is not None
#                     else:
#                         try:
#                             text = await cell.inner_text()
#                             row_data[header_text] = text.strip()
#                         except:
#                             row_data[header_text] = None
#                 else:
#                     row_data[header_text] = None

#             # ✅ Skip row if all values are None or empty strings
#             if all(v in [None, ""] for v in row_data.values()):
#                 continue

#             # Filter rows if needed
#             passed_filters = all(
#                 matches_filter(row_data, f, type_map.get(f.get("column"), "text"))
#                 for f in filters
#             )

#             if passed_filters:
#                 extracted_rows.append(row_data)
#                 filtered_row_elements.append(row)

#         # ✅ Cache result for use in get_smart_locator
#         if not hasattr(page.context, "_botflows_filtered_rows"):
#             page.context._botflows_filtered_rows = {}

#         page.context._botflows_filtered_rows[row_selector] = {
#             "rows": filtered_row_elements,
#             "data": extracted_rows,
#             "columnMappings": column_mappings
#         }

#         return extracted_rows

#     except Exception as ex:
#         logger.error(f"[extract_grid_data] Error extracting rows: {ex}")
#         return []
async def extract_grid_data(page, source_step: dict):
    """Extracts structured row data from a grid using mappings and optional filters."""
    grid_selector = source_step.get("gridSelector")
    row_selector = source_step.get("rowSelector")
    column_mappings = source_step.get("columnMappings", [])
    filters = source_step.get("filters", [])
    name = source_step.get("name", "Unnamed Extract")
    await state.log_to_status(f"Extracting grid data from: {name} ")
    extracted_rows = []
    filtered_row_locators = []

    try:
        await page.wait_for_selector(grid_selector, state="visible", timeout=5000)
        try:
            await page.wait_for_selector(row_selector, state="visible", timeout=3000)
        except:
            fallback = f"{grid_selector} tr"
            await page.wait_for_selector(fallback, state="visible", timeout=3000)
            logger.warning(f"[RowSelector Fallback] Switching from '{row_selector}' to '{fallback}'")
            row_selector = fallback

        row_locators = page.locator(row_selector)
        row_count = await row_locators.count()
        logger.info(f"[extract_grid_data] Found {row_count} rows in grid")

        type_map = {
            col.get("header", {}).get("header"): col.get("header", {}).get("type", "text")
            for col in column_mappings
        }

        for i in range(row_count):
            row = row_locators.nth(i)
            row_data = {}
            for col in column_mappings:
                header_obj = col.get("header", {})
                header_text = header_obj.get("header", f"col_{col.get('columnIndex')}")
                header_type = header_obj.get("type", "text")
                col_selector = col.get("selector")

                cell_locator = row.locator(col_selector) if col_selector else None

                # Fallback
                if not cell_locator or await cell_locator.count() == 0:
                    if "columnIndex" in col:
                        index = col["columnIndex"]
                        fallback_selector = f'td:nth-of-type({index + 1})'
                        cell_locator = row.locator(fallback_selector)

                text_value = None
                if cell_locator and await cell_locator.count() > 0:
                    if header_type == "img":
                        img_locator = cell_locator.locator("img")
                        row_data[header_text] = await img_locator.count() > 0
                    else:
                        try:
                            cell = await cell_locator.element_handle()
                            text = await cell.inner_text() if cell else ""
                            row_data[header_text] = text.strip()
                        except:
                            row_data[header_text] = None
                else:
                    row_data[header_text] = None

            if all(v in [None, ""] for v in row_data.values()):
                continue

            passed_filters = True
            for f in filters:
                result = await matches_filter(row_data, f, type_map.get(f.get("column"), "text"))
                if not result:
                    passed_filters = False
                    break

            if passed_filters:
                await state.log_to_status(f"Filter passed for row {i + 1}: {row_data}")
                extracted_rows.append(row_data)
                filtered_row_locators.append(row)
        await state.log_to_status(f"[total rows found] {row_count}")        
        await state.log_to_status(f"[extract_grid_data] {len(extracted_rows)} rows after filtering")
        # ✅ Cache result for use in get_smart_locator
        if not hasattr(page.context, "_botflows_filtered_rows"):
            page.context._botflows_filtered_rows = {}
        
        source_step_id = source_step.get("id")  # Or however you're identifying the extract step

        page.context._botflows_filtered_rows[source_step_id] = {
            "rows": filtered_row_locators,  # Locators, not ElementHandles
            "data": extracted_rows,
            "columnMappings": column_mappings
        }
        logger.debug(f"[Cache] Stored filtered rows under source ID: {source_step_id}")
        
        return extracted_rows

    except Exception as ex:
        logger.error(f"[extract_grid_data] Error extracting rows: {ex}")
        return []

async def replay_flow(json_str: str, is_preview: bool = False):
    if is_preview:
        state.is_previewing = True
        if state.active_page:
            await state.active_page.evaluate("""() => {
            window.__botflows_replaying__ = true;
            if (!document.getElementById('botflows-replay-overlay')) {
                const div = document.createElement('div');
                div.id = 'botflows-replay-overlay';
                div.innerText = 'Preview in progress...';
                div.style.position = 'fixed';
                div.style.top = 0;
                div.style.left = 0;
                div.style.right = 0;
                div.style.bottom = 0;
                div.style.backgroundColor = 'rgba(0,0,0,0.5)';
                div.style.color = 'white';
                div.style.fontSize = '2rem';
                div.style.display = 'flex';
                div.style.alignItems = 'center';
                div.style.justifyContent = 'center';
                div.style.zIndex = 9999;
                document.body.appendChild(div);
            }
            }""")
    else:
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
        # Extract the first navigate step URL
        top_level_steps = [s for s in flow if not s.get("parentId")]
        navigate_step = next((s for s in top_level_steps if s.get("type") == "navigate" and s.get("url")), None)
        initial_url = navigate_step["url"] if navigate_step else "about:blank"
        await state.log_to_status(f"Launching browser for replay to: {initial_url}")
        if is_preview:
            browser, page = await launch_preview_window(p, initial_url=initial_url)
        else:
            browser, page = await launch_replay_window(p, initial_url=initial_url)

        steps_by_id = {step["id"]: step for step in flow}
        page.context._botflows_steps_by_id = steps_by_id

        for step in top_level_steps:
            # Skip the navigate step since we already opened the URL
            if step.get("type") == "navigate" and step.get("url") == initial_url:
                continue
            await handle_step(step, page)
        if is_preview:
            await state.log_to_status(f"Preview replay finished, you can continue recording now...")
        else:
            await state.log_to_status(f"Replay finished.")
        logger.info("Replay complete.")
        await asyncio.sleep(2)
        await close_chrome()
        if is_preview:
            if state.active_page:
                await state.active_page.evaluate("""() => {
                    window.__botflows_replaying__ = false;
                    const div = document.getElementById('botflows-replay-overlay');
                    if (div) div.remove();
                }""")
            state.is_previewing = False
        else:
            state.is_replaying = False
