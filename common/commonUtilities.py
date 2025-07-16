import asyncio

from urllib.parse import urlparse
from playwright.async_api import Page, Frame
from common.selectorRecoveryHelper import *
from math import fabs
from playwright.async_api import Locator
from common.logger import get_logger

logger = get_logger(__name__)

async def wait_for_frame_url(page, target_url, timeout=10000):
    deadline = page.context._loop.time() + timeout / 1000
    while page.context._loop.time() < deadline:
        for frame in page.frames:
            try:
                if frame.url.startswith(target_url) or target_url in frame.url:
                    return frame
            except Exception:
                continue
        await asyncio.sleep(0.2)
    raise TimeoutError(f"Timeout waiting for frame with URL: {target_url}")

def url_base(url: str) -> str:
    """Extract base URL (scheme + netloc + path) for consistent frame comparison."""
    parts = urlparse(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"

async def resolve_frame_from_url(page: Page, frame_url: str) -> Frame:
    """Tries to resolve the best-matching frame based on normalized frame_url."""
    base_target = url_base(frame_url)

    # Try exact match
    for frame in page.frames:
        if url_base(frame.url) == base_target:
            return frame

    # Try partial match fallback (e.g., in SPA apps or embed links)
    for frame in page.frames:
        if base_target in frame.url:
            return frame

    return page.main_frame  # fallback

def bbox_mismatch(box1, box2, tolerance=100):
    if not box1 or not box2:
        return True
    return any(fabs(box1.get(k, 0) - box2.get(k, 0)) > tolerance for k in ["x", "y", "width", "height"])

async def can_perform_action_with_retries(locator: Locator, retries=3, delay=1.0) -> bool:
    for attempt in range(retries):
        try:
            # Check how many elements match before calling .first
            count = await locator.count()
            if count == 0:
                logger.debug(f"[RETRY {attempt+1}] Locator not found")
                await asyncio.sleep(delay)
                continue

            target = locator.first

            if not await target.is_visible():
                logger.debug(f"[RETRY {attempt+1}] Locator not visible")
                await asyncio.sleep(delay)
                continue

            element = await target.element_handle()
            if not element:
                logger.debug(f"[RETRY {attempt+1}] No element handle")
                await asyncio.sleep(delay)
                continue

            disabled = await element.get_attribute("disabled")
            if disabled is not None:
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
    
async def get_best_locator(page: Page, step: dict, validated: list) -> Locator:
    """
    Given a step and validated selectors, return the best available Locator to perform the action.
    """

    # Sort validated selectors by score descending
    validated.sort(key=lambda s: s.get("score", 0), reverse=True)

    # First preference: unique match
    for sel in validated:
        if sel.get("verified") and sel.get("replayable") and sel.get("matchFailureReason") == "maybe-ok":
            logger.info(f"[Recovery] Using unique verified selector: {sel['selector']}")
            tempLocator = page.locator(sel["selector"])
            if await tempLocator.count() > 0:
                return tempLocator.first

    # Second: multiple-match resolved via bounding box
    for sel in validated:
        if sel.get("verified") and sel.get("replayable") and sel.get("matchFailureReason") == "multiple-match-resolved":
            index = sel.get("matchIndex")
            if isinstance(index, int):
                logger.info(f"[Recovery] Using resolved multiple-match selector: {sel['selector']} [index: {index}]")
                tempLocator = page.locator(sel["selector"])
                if await tempLocator.count() > 0:
                    return tempLocator.nth(index)
            
async def get_locator(page: Page, sel: str, source: str):
    if source == "xpath":
        return page.locator(f"xpath={sel}")
    
    # Treat all other sources as CSS selectors
    return page.locator(sel)

async def get_smart_locator(page: Page, step: dict):
    selector = step.get("selector")
    source = step.get("source", "")
    is_smart = step.get("isSmartColumn", False)
    column_index = step.get("columnIndex")

    if not is_smart or column_index is None:
        return await get_locator(page, selector, source).first

    try:
        # Look up grid extract step via loop parent and its sourceStepId
        steps_by_id = getattr(page.context, "_botflows_steps_by_id", {})
        loop_step = steps_by_id.get(step.get("parentId"), {})
        source_id = loop_step.get("source")

        extract_step = getattr(page.context, "_botflows_extractions", {}).get(source_id)
        if not extract_step:
            raise Exception("No matching grid extract step found in context.")

        # ✅ Get cached filtered rows using sourceId
        cached = getattr(page.context, "_botflows_filtered_rows", {}).get(source_id)
        if not cached:
            raise Exception(f"No cached grid data found for source ID: {source_id}")

        rows = cached.get("rows", [])
        if not rows:
            raise Exception("No filtered rows cached")

        row_index = getattr(page.context, "_botflows_row_index", 0)
        row_locator = rows[row_index] if row_index < len(rows) else rows[0]

        # Smart column fallback targeting
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
        return await get_locator(page, selector, source).first

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

async def try_action(page, sel, step, source_hint=None):
    action = step.get("action", "")
    value = step.get("value")
    dynamicValue = step.get("dynamicValue")
    key = step.get("key")
    time_out = 5000

    action = step.get("action", "").lower()
    if step.get("isSmartColumn"):
        matchedLocator = await get_smart_locator(page, step)
    else:
        locator = await get_locator(page, sel, source_hint or "")
        numberOfmatches = await locator.count()
        logger.info(f"#########################################")
        logger.info(f"Number of matches found {numberOfmatches}")
        logger.info(f"#########################################")

        if numberOfmatches == 0:
            raise Exception(f"no matches found on selector {sel}")
        
        if numberOfmatches > 1 :
            validated = await generate_recovery_selectors(page, step)
            if len(validated) > 1:
                matchedLocator = await get_best_locator(page, step, validated)
        else:
            matchedLocator = locator.first

        # original_bbox = step.get("boundingBox")

        # # Validate bounding box
        # if original_bbox:
        #     try:
        #         box = await matchedLocator.bounding_box()
        #         if bbox_mismatch(original_bbox, box):
        #             logger.warning("Bounding box mismatch — trying fallback selectors.")
        #             validated = await generate_recovery_selectors(page, step)
        #             if validated:
        #                 matchedLocator = await get_best_locator(page, step, validated)

        #     except Exception as bbox_ex:
        #         logger.warning(f"Bounding box validation failed: {bbox_ex}")

    if not await can_perform_action_with_retries(matchedLocator, 2):
        raise Exception(f"Action can not be performed on selector {sel}")

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
        return await page.keyboard.press(key)
    elif action.lower() == "select":
        await matchedLocator.wait_for(state="attached", timeout=5000)
        return await matchedLocator.select_option(value)
    elif action.lower() in ["mousedown", "focus", "blur"]:
        await matchedLocator.wait_for(state="attached", timeout=5000)
        return await matchedLocator.dispatch_event(action)
