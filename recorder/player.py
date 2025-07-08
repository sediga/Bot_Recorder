import asyncio
import json
import logging
from pathlib import Path
import re
from playwright.async_api import async_playwright, Page
from common import state
from common.browserutil import launch_chrome
from common.gridHelper import matches_filter
from common.selectorHelper import call_selector_recovery_api, confirm_selector_worked
import operator
from dateutil import parser as dateparser
from common.selectorRecoveryHelper import *
from math import fabs
from playwright.async_api import Locator

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
    
    # Treat all other sources as CSS selectors
    return page.locator(sel)

# async def get_smart_locator(page: Page, step: dict) -> Page:
#     selector = step.get("selector")
#     source = step.get("source", "")
#     is_smart = step.get("isSmartColumn", False)
#     column_index = step.get("columnIndex")

#     if not is_smart or column_index is None:
#         return get_locator(page, selector, source).first

#     try:
#         # Look up grid extract step via loop parent and its sourceStepId
#         steps_by_id = getattr(page.context, "_botflows_steps_by_id", {})
#         loop_step = steps_by_id.get(step.get("parentId"), {})
#         source_id = loop_step.get("source")

#         extract_step = getattr(page.context, "_botflows_extractions", {}).get(source_id)
#         if not extract_step:
#             raise Exception("No matching grid extract step found in context.")

#         grid_selector = extract_step.get("gridSelector")
#         row_selector = extract_step.get("rowSelector")

#         await page.wait_for_selector(grid_selector, timeout=3000)
#         try:
#             await page.wait_for_selector(row_selector, state="visible", timeout=3000)
#         except:
#             fallback = f"{grid_selector} tr"
#             await page.wait_for_selector(fallback, state="visible", timeout=3000)
#             logger.warning(f"[RowSelector Fallback] Switching from '{row_selector}' to '{fallback}'")
#             row_selector = fallback

#         cached = getattr(page.context, "_botflows_filtered_rows", {}).get(row_selector)
#         if not cached:
#             raise Exception("No cached grid data found for selector")

#         rows = cached.get("rows", [])
#         if not rows:
#             raise Exception("No filtered rows cached")

#         row_index = getattr(page.context, "_botflows_row_index", 0)
#         matched_row = rows[row_index] if row_index < len(rows) else rows[0]

#         fallback_selector = (
#             f"td:nth-of-type({column_index + 1}), "
#             f"[role='cell']:nth-of-type({column_index + 1}), "
#             f"div[role='gridcell']:nth-of-type({column_index + 1})"
#         )
#         row_locator = page.locator(row_selector).nth(row_index)
#         cellLocator = await row_locator.locator(fallback_selector)

#         if not cellLocator:
#             raise Exception(f"No cell found at column {column_index}")

#         # # Try to find clickable descendant inside the cell
#         # action_type = step.get("action") or step.get("smartActionType", "click")
#         # if action_type == "click":
#         #     # Search for clickable child
#         #     target = await cell.query_selector('a, button, [role="button"], [onclick]') or cell
#         # elif action_type in ["type", "change", "select"]:
#         #     # Prefer form field descendants
#         #     target = await cell.query_selector("input, select, textarea") or cell
#         # else:
#         #     target = cell  # fallback

#         return cellLocator
#     except Exception as ex:
#         logger.warning(f"[get_smart_locator] Fallback to default due to error: {ex}")
#         return get_locator(page, selector, source).first
async def get_smart_locator(page: Page, step: dict):
    selector = step.get("selector")
    source = step.get("source", "")
    is_smart = step.get("isSmartColumn", False)
    column_index = step.get("columnIndex")

    if not is_smart or column_index is None:
        return get_locator(page, selector, source).first

    try:
        # Look up grid extract step via loop parent and its sourceStepId
        steps_by_id = getattr(page.context, "_botflows_steps_by_id", {})
        loop_step = steps_by_id.get(step.get("parentId"), {})
        source_id = loop_step.get("source")

        extract_step = getattr(page.context, "_botflows_extractions", {}).get(source_id)
        if not extract_step:
            raise Exception("No matching grid extract step found in context.")

        grid_selector = extract_step.get("gridSelector")
        row_selector = extract_step.get("rowSelector")

        await page.wait_for_selector(grid_selector, timeout=3000)
        try:
            await page.wait_for_selector(row_selector, state="visible", timeout=3000)
        except:
            fallback = f"{grid_selector} tr"
            await page.wait_for_selector(fallback, state="visible", timeout=3000)
            logger.warning(f"[RowSelector Fallback] Switching from '{row_selector}' to '{fallback}'")
            row_selector = fallback

        cached = getattr(page.context, "_botflows_filtered_rows", {}).get(row_selector)
        if not cached:
            raise Exception("No cached grid data found for selector")

        rows = cached.get("rows", [])
        if not rows:
            raise Exception("No filtered rows cached")

        row_index = getattr(page.context, "_botflows_row_index", 0)
        row_locator = rows[row_index] if row_index < len(rows) else rows[0]

        fallback_selector = (
            f"td:nth-of-type({column_index + 1}), "
            f"[role='cell']:nth-of-type({column_index + 1}), "
            f"div[role='gridcell']:nth-of-type({column_index + 1})"
        )
        cell_locator = row_locator.locator(fallback_selector)

        if await cell_locator.count() == 0:
            raise Exception(f"No cell found at column {column_index}")

        action_type = step.get("action") or step.get("smartActionType", "click")

        if action_type == "click":
            target = cell_locator.locator("a, button, [role='button'], [onclick]").first
        elif action_type in ["type", "change", "select"]:
            target = cell_locator.locator("input, select, textarea").first
        else:
            target = cell_locator

        return target

    except Exception as ex:
        logger.warning(f"[get_smart_locator] Fallback to default due to error: {ex}")
        return get_locator(page, selector, source).first

# async def _perform_action(page: Page, step: dict, retries=2):
#     await asyncio.sleep(1)

#     action = step.get("action", "")
#     value = step.get("value")
#     dynamicValue = step.get("dynamicValue")
#     key = step.get("key")
#     selector = step.get("selector")
#     selectors = step.get("selectors", [])

#     async def try_action(target_page: Page, sel, source_hint=None):
#         locator = get_locator(target_page, sel, source_hint or "")

#         if action.lower() == "click":
#             await locator.first.wait_for(state="visible", timeout=5000)
#             return await locator.first.click(timeout=5000)
#         elif action.lower() == "dblclick":
#             await locator.first.wait_for(state="visible", timeout=5000)
#             return await locator.first.dblclick(timeout=5000)
#         elif action.lower() == "type":
#             await locator.first.wait_for(state="attached", timeout=5000)
#             await locator.first.focus()
#             return await locator.first.type(value or "")
#         elif action.lower() == "change":
#             await locator.first.wait_for(state="attached", timeout=5000)
#             await locator.first.focus()
#             return await locator.first.fill(value or "")
#         elif action.lower() == "press":
#             return await target_page.keyboard.press(key)
#         elif action.lower() == "select":
#             await locator.first.wait_for(state="attached", timeout=5000)
#             return await locator.first.select_option(value)
#         elif action.lower() in ["mousedown", "focus", "blur"]:
#             await locator.first.wait_for(state="attached", timeout=5000)
#             return await locator.first.dispatch_event(action)

#     # 🔁 Handle dynamic value substitution
#     raw_value = dynamicValue or value

#     if step and isinstance(dynamicValue, str) and "{{" in dynamicValue and hasattr(page.context, "_botflows_row_data"):
#         row_data = page.context._botflows_row_data
#         transform = step.get("transform")
#         transform_type = step.get("transformType")

#         for key, val in row_data.items():
#             placeholder = f"{{{{{key}}}}}"
#             if placeholder in raw_value:
#                 final_val = apply_transformations(val, transform_type, transform)
#                 raw_value = raw_value.replace(placeholder, final_val)

#         value = raw_value

#     # ✅ Pre-check: Wait for any verified selector if present
#     # if selectors:
#     #     first_verified = next((s for s in selectors if s.get("verified")), None)
#     #     if first_verified:
#     #         try:
#     #             await page.wait_for_selector(first_verified["selector"], timeout=2000)
#     #             logger.info(f"Pre-check success: {first_verified['selector']}")
#     #         except Exception as wait_ex:
#     #             logger.warning(f"Pre-check failed for {first_verified['selector']}: {wait_ex}")

#     effective_selectors = selectors if selectors else [{"selector": selector}]

#     # for attempt in range(1, retries + 1):
#     #     for sel_obj in effective_selectors:
#     #         sel = sel_obj["selector"] if isinstance(sel_obj, dict) else sel_obj
#     #         source = sel_obj.get("source", "") if isinstance(sel_obj, dict) else ""

#     #         try:
#     #             await try_action(page, sel)
#     #             logger.info(f"Action '{action}' succeeded on attempt {attempt}: {sel}")
#     #             return
#     #         except Exception as e:
#     #             logger.warning(f"Attempt {attempt} failed: {action} / {sel} => {e}")

#     #             for frame in page.frames:
#     #                 if frame == page.main_frame:
#     #                     continue
#     #                 try:
#     #                     await try_action(frame, sel)
#     #                     logger.info(f"[Frame] Success inside: {frame.url}")
#     #                     return
#     #                 except:
#     #                     continue

#     #     if attempt == retries:
#     #         fallback_sel = effective_selectors[0]["selector"] if isinstance(effective_selectors[0], dict) else effective_selectors[0]
#     #         source_hint = effective_selectors[0].get("source", "") if isinstance(effective_selectors[0], dict) else ""

#     #         try:
#     #             if source_hint == "xpath":
#     #                 tag = await page.evaluate("""(sel) => {
#     #                     const result = document.evaluate(sel, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
#     #                     const el = result.singleNodeValue;
#     #                     return el?.tagName?.toLowerCase() || '';
#     #                 }""", fallback_sel)
#     #                 el_id = await page.evaluate("""(sel) => {
#     #                     const result = document.evaluate(sel, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
#     #                     const el = result.singleNodeValue;
#     #                     return el?.id || '';
#     #                 }""", fallback_sel)
#     #                 element_text = await page.evaluate("""(sel) => {
#     #                     const result = document.evaluate(sel, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
#     #                     const el = result.singleNodeValue;
#     #                     return el?.innerText || '';
#     #                 }""", fallback_sel)
#     #             else:
#     #                 tag = await page.evaluate("(sel) => { const el = document.querySelector(sel); return el?.tagName?.toLowerCase() || ''; }", fallback_sel)
#     #                 el_id = await page.evaluate("(sel) => { const el = document.querySelector(sel); return el?.id || ''; }", fallback_sel)
#     #                 element_text = await page.evaluate("(sel) => { const el = document.querySelector(sel); return el?.innerText || ''; }", fallback_sel)
#     #         except Exception as ex:
#     #             logger.warning(f"[safe_evaluate failed] {ex}")
#     #             tag = el_id = element_text = ""

#     #         try:
#     #             new_selector = await call_selector_recovery_api(
#     #                 url=page.url,
#     #                 failed_selector=fallback_sel,
#     #                 tag=tag,
#     #                 text=element_text,
#     #                 el_id=el_id
#     #             )
#     #             if new_selector:
#     #                 logger.info(f"Recovered selector from API: {new_selector}")
#     #                 await try_action(page, new_selector)
#     #                 await confirm_selector_worked(url=page.url, original_selector=fallback_sel)
#     #                 return
#     #         except Exception as api_ex:
#     #             logger.warning(f"[Recovery API] Failed: {api_ex}")

#     #     await asyncio.sleep(1)

#     # Only attempt first selector once, keep full selector list for reference
#     sel_obj = effective_selectors[0] if isinstance(effective_selectors[0], dict) else {"selector": effective_selectors[0], "source": ""}
#     sel = sel_obj["selector"]
#     source = sel_obj.get("source", "")

#     try:
#         await try_action(page, sel)
#         logger.info(f"Action '{action}' succeeded: {sel}")
#         return
#     except Exception as e:
#         logger.warning(f"Initial attempt failed: {action} / {sel} => {e}")

#         # Try in child frames
#         for frame in page.frames:
#             if frame == page.main_frame:
#                 continue
#             try:
#                 await try_action(frame, sel)
#                 logger.info(f"[Frame] Success inside: {frame.url}")
#                 return
#             except:
#                 continue

#     # Recovery logic — active
#     try:
#         if source == "xpath":
#             tag = await page.evaluate("""(sel) => {
#                 const result = document.evaluate(sel, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
#                 const el = result.singleNodeValue;
#                 return el?.tagName?.toLowerCase() || '';
#             }""", sel)
#             el_id = await page.evaluate("""(sel) => {
#                 const result = document.evaluate(sel, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
#                 const el = result.singleNodeValue;
#                 return el?.id || '';
#             }""", sel)
#             element_text = await page.evaluate("""(sel) => {
#                 const result = document.evaluate(sel, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
#                 const el = result.singleNodeValue;
#                 return el?.innerText || '';
#             }""", sel)
#         else:
#             tag = await page.evaluate("(sel) => { const el = document.querySelector(sel); return el?.tagName?.toLowerCase() || ''; }", sel)
#             el_id = await page.evaluate("(sel) => { const el = document.querySelector(sel); return el?.id || ''; }", sel)
#             element_text = await page.evaluate("(sel) => { const el = document.querySelector(sel); return el?.innerText || ''; }", sel)
#     except Exception as ex:
#         logger.warning(f"[safe_evaluate failed] {ex}")
#         # tag = el_id = element_text = ""

#     try:
#         new_selector = await call_selector_recovery_api(
#             url=page.url,
#             failed_selector=sel,
#             tag=step.get("tagName"),
#             text=step.get("elementText"),
#             el_id=""
#         )
#         if new_selector:
#             logger.info(f"Recovered selector from API: {new_selector}")
#             await try_action(page, new_selector)
#             await confirm_selector_worked(url=page.url, original_selector=sel)
#             return
#     except Exception as api_ex:
#         logger.warning(f"[Recovery API] Failed: {api_ex}")

#     # --- Retry logic removed for now ---
#     # for attempt in range(1, retries + 1):
#     #     ...
#     # -----------------------------------

#     raise Exception(f"All attempts failed for action '{action}' on selector: {selector}")

async def _perform_action(page, step, retries=2):
    await asyncio.sleep(1)

    action = step.get("action", "")
    value = step.get("value")
    dynamicValue = step.get("dynamicValue")
    key = step.get("key")
    selector = step.get("selector")
    selectors = step.get("selectors", [])

    def bbox_mismatch(box1, box2, tolerance=100):
        if not box1 or not box2:
            return True
        return any(fabs(box1.get(k, 0) - box2.get(k, 0)) > tolerance for k in ["x", "y", "width", "height"])
    
    async def can_perform_action_with_retries(locator: Locator, retries=3, delay=1.0) -> bool:
        for attempt in range(retries):
            try:
                # Avoid calling .first on something that is already a single locator
                target = locator
                if hasattr(locator, "_first"):  # dirty hack, but Playwright exposes this
                    target = locator
                else:
                    target = locator.first

                if await target.count() == 0:
                    logger.debug(f"[RETRY {attempt+1}] Locator not found")
                    await asyncio.sleep(delay)
                    continue

                if not await target.is_visible():
                    logger.debug(f"[RETRY {attempt+1}] Locator not visible")
                    await asyncio.sleep(delay)
                    continue

                element = await target.element_handle()
                if not element:
                    logger.debug(f"[RETRY {attempt+1}] No element handle")
                    await asyncio.sleep(delay)
                    continue

                if await element.get_attribute("disabled") is not None:
                    logger.debug(f"[RETRY {attempt+1}] Element disabled")
                    await asyncio.sleep(delay)
                    continue

                logger.info(f"[REPLAY] Locator is ready for action")
                return True

            except Exception as e:
                logger.warning(f"[RETRY {attempt+1}] Error checking locator: {str(e)}")
                await asyncio.sleep(delay)

        logger.warning(f"[REPLAY] Locator not ready after {retries} retries")
        return False
    
    async def try_action(target_page, sel, step, source_hint=None):
        time_out = 5000
        action = step.get("action", "").lower()
        if step.get("isSmartColumn"):
            matchedLocator = await get_smart_locator(target_page, step)
        else:
            locator = get_locator(target_page, sel, source_hint or "")
            matchedLocator = locator.first
            numberOfmatches = await locator.count()
            logger.info(f"#########################################")
            logger.info(f"Number of matches found {numberOfmatches}")
            logger.info(f"#########################################")

            if numberOfmatches == 0:
                raise Exception(f"no matches found on selector {selector}")
            
            if numberOfmatches > 1 :
                validated = await generate_recovery_selectors(page, step)
                if len(validated) > 1:
                    matchedSelObj = validated[0]
                    index = matchedSelObj.get("matchIndex", None)
                    if index is not None and isinstance(index, int):
                        matchedLocator = locator.nth(index)

            original_bbox = step.get("boundingBox")

            # Validate bounding box
            if original_bbox:
                try:
                    box = await matchedLocator.bounding_box()
                    if bbox_mismatch(original_bbox, box):
                        logger.warning("Bounding box mismatch — trying fallback selectors.")
                        validated = await generate_recovery_selectors(page, step)
                        if validated:
                            sel_obj = validated[0]
                            matchedLocator = get_locator(target_page, sel_obj["selector"], sel_obj.get("source", "")).first
                            logger.info(f"Using fallback selector: {sel_obj['selector']} from {sel_obj.get('source')}")

                except Exception as bbox_ex:
                    logger.warning(f"Bounding box validation failed: {bbox_ex}")

        if not await can_perform_action_with_retries(matchedLocator, 2):
            raise Exception(f"Action can not be performed on selector {selector}")

        if action.lower() == "click":
            await matchedLocator.scroll_into_view_if_needed()
            await matchedLocator.wait_for(state="attached")  
            await matchedLocator.wait_for(state="visible", timeout=time_out)
            async with page.expect_navigation(wait_until="load"):
                return await matchedLocator.click(timeout=time_out)
            
        elif action.lower() == "dblclick":
            await matchedLocator.wait_for(state="visible", timeout=time_out)
            return await matchedLocator.dblclick(timeout=time_out)
        elif action.lower() == "type":
            await matchedLocator.wait_for(state="attached", timeout=time_out)
            await matchedLocator.focus()
            return await matchedLocator.type(value or "")
        elif action.lower() == "change":
            await matchedLocator.wait_for(state="attached", timeout=time_out)
            await matchedLocator.focus()
            return await matchedLocator.fill(value or "")
        elif action.lower() == "press":
            return await target_page.keyboard.press(key)
        elif action.lower() == "select":
            await matchedLocator.wait_for(state="attached", timeout=5000)
            return await matchedLocator.select_option(value)
        elif action.lower() in ["mousedown", "focus", "blur"]:
            await matchedLocator.wait_for(state="attached", timeout=5000)
            return await matchedLocator.dispatch_event(action)

    raw_value = dynamicValue or value

    if step and isinstance(dynamicValue, str) and "{{" in dynamicValue and hasattr(page.context, "_botflows_row_data"):
        row_data = page.context._botflows_row_data
        transform = step.get("transform")
        transform_type = step.get("transformType")

        for key, val in row_data.items():
            placeholder = f"{{{{{key}}}}}"
            if placeholder in raw_value:
                final_val = apply_transformations(val, transform_type, transform)
                raw_value = raw_value.replace(placeholder, final_val)

        value = raw_value

    effective_selectors = selectors if selectors else [{"selector": selector}]

    sel_obj = effective_selectors[0] if isinstance(effective_selectors[0], dict) else {"selector": effective_selectors[0], "source": ""}
    sel = sel_obj["selector"] or selector
    source = sel_obj.get("source", "")

    try:
        await try_action(page, sel, step, source)
        logger.info(f"Action '{action}' succeeded: {sel}")
        return
    except Exception as e:
        logger.warning(f"Initial attempt failed: {action} / {sel} => {e}")
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            try:
                await try_action(frame, sel, step, source)
                logger.info(f"[Frame] Success inside: {frame.url}")
                return
            except:
                continue

    try:
        selector_candidates = await generate_recovery_selectors(page, step)

        for candidate in selector_candidates:
            candidate_selector = candidate.get("selector")
            candidate_source = candidate.get("source", "")
            try:
                await try_action(page, candidate_selector, step, candidate_source)
                logger.info(f"Recovered selector worked: {candidate_selector}")
                # await confirm_selector_worked(url=page.url, original_selector=sel)
                return
            except Exception as attempt_ex:
                logger.warning(f"[Recovery attempt failed] {candidate_selector}: {attempt_ex}")
                continue
    except Exception as recovery_ex:
        logger.warning(f"[Recovery Logic] Failed: {recovery_ex}")

    raise Exception(f"All attempts failed for action '{action}' on selector: {selector}")

def apply_transformations(value: str, transform_type: str, transform: str) -> str:
    if not transform_type or not transform or not value:
        return value

    try:
        if transform_type == "regex":
            pattern = transform
            re_obj = re.compile(pattern)
            match = re_obj.search(value)
            if match:
                logger.info(f"[Transform Apply] Regex match with pattern: {pattern}")
                return match.group(1) if match.lastindex else match.group(0)
            else:
                logger.info("[Transform Apply] No match found")
                return "(no match)"

        elif transform_type == "js":
            logger.info(f"[Transform Apply] JS simulation with: value{transform}")
            # Simulate only safe JS-like methods
            return apply_js_like_transform(value, transform)
        else:
            logger.info(f"[Transform Apply] Unknown transform type: {transform_type}")
    except Exception as e:
        logger.warning(f"[Transform Apply Error] {e}")
        return "(error)"

    return value

def apply_js_like_transform(value: str, transform: str) -> str:
    try:
        if transform == "value.trim()":
            return value.strip()
        elif transform == "value.toLowerCase()":
            return value.lower()
        elif transform == "value.toUpperCase()":
            return value.upper()
        elif transform.startswith("value.slice(") and transform.endswith(")"):
            args = transform[12:-1]
            parts = [int(p.strip()) for p in args.split(",")]
            if len(parts) == 1:
                return value[parts[0]:]
            elif len(parts) == 2:
                return value[parts[0]:parts[1]]
        elif ".replace(" in transform:
            pattern_match = re.search(r"\.replace\(/(.*)/\$\s*,\s*'([^']*)'\)", transform)
            if pattern_match:
                pattern = pattern_match.group(1).replace("\\\\", "\\")
                replacement = pattern_match.group(2)
                value = re.sub(pattern, replacement, value)
            if ".trim()" in transform:
                value = value.strip()
            return value
    except Exception as e:
        logger.warning(f"[Transform JS Sim Error] {e}")
    return value

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
            page,
            grid_selector=source_step.get("gridSelector"),
            row_selector=source_step.get("rowSelector"),
            column_mappings=source_step.get("columnMappings", []),
            filters=source_step.get("filters", [])
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
async def extract_grid_data(page, grid_selector, row_selector, column_mappings, filters=None):
    """Extracts structured row data from a grid using mappings and optional filters."""
    filters = filters or []
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

            passed_filters = all(
                matches_filter(row_data, f, type_map.get(f.get("column"), "text"))
                for f in filters
            )

            if passed_filters:
                extracted_rows.append(row_data)
                filtered_row_locators.append(row)

        # ✅ Cache result for use in get_smart_locator
        if not hasattr(page.context, "_botflows_filtered_rows"):
            page.context._botflows_filtered_rows = {}

        page.context._botflows_filtered_rows[row_selector] = {
            "rows": filtered_row_locators,  # Locators, not ElementHandles
            "data": extracted_rows,
            "columnMappings": column_mappings
        }

        return extracted_rows

    except Exception as ex:
        logger.error(f"[extract_grid_data] Error extracting rows: {ex}")
        return []

async def replay_flow(json_str: str):
    state.is_replaying = True
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

        steps_by_id = {step["id"]: step for step in flow}
        page.context._botflows_steps_by_id = steps_by_id

        for step in top_level_steps:
            await handle_step(step, page)

        logger.info("Replay complete.")
        await browser.close()
        if state.active_page:
            await state.active_page.evaluate("""() => {
            window.__botflows_replaying__ = false;
            const div = document.getElementById('botflows-replay-overlay');
            if (div) div.remove();
            }""")
        state.is_replaying = False
