import logging
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright
import sys
import re
from common import state
from common.browserutil import launch_chrome
from common.dom_snapshot import upload_snapshot_to_api
from common import selectorHelper
# selector_builder.py
from common.selectorHelper import get_devtools_like_selector
from common.gridHelper import *
import asyncio

logger = logging.getLogger(__name__)
recorded_events = []

# Resolve paths
BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent.resolve()))
selector_script_path = BASE_DIR / "../javascript" / "selectorHelper.bundle.js"
recorder_script_path = BASE_DIR / "../javascript" / "recorder.bundle.js"
blocker_script_path = BASE_DIR / "../javascript" / "blocker.js"
preview_script_path = BASE_DIR / "../javascript" / "pickerPreview.bundle.js"  # NEW

overlay_script = """
(() => {
  const overlay = document.createElement('div');
  overlay.id = '__botflows_overlay';
  Object.assign(overlay.style, {
    position: 'fixed',
    top: 0,
    left: 0,
    width: '100vw',
    height: '100vh',
    backgroundColor: 'rgba(255,255,255,0.85)',
    zIndex: 999999,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: '20px',
    fontFamily: 'sans-serif'
  });
  overlay.textContent = 'Analyzing page... Please wait.';
  document.body.appendChild(overlay);
})();
"""

remove_overlay_script = """
(() => {
  const el = document.getElementById('__botflows_overlay');
  if (el) el.remove();
})();
"""

remove_validation_overlay_script = """
(() => {
  const el = document.getElementById('__botflows_validation_overlay');
  if (el) el.remove();
})();
"""
analyzing_grid_overlay_script = """
(() => {
  const overlay = document.createElement('div');
  overlay.id = '__botflows_grid_analysis';
  Object.assign(overlay.style, {
    position: 'fixed',
    top: 0,
    left: 0,
    width: '100vw',
    height: '100vh',
    backgroundColor: 'rgba(0,0,0,0.5)',
    color: 'white',
    fontSize: '22px',
    fontFamily: 'sans-serif',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 9999999
  });
  overlay.textContent = 'Analyzing grid... This might take a moment.';
  document.body.appendChild(overlay);
})();
"""

remove_grid_overlay_script = """
(() => {
  const overlay = document.getElementById('__botflows_grid_analysis');
  if (overlay) overlay.remove();
})();
"""

standard_event_queue = asyncio.Queue()

async def standard_event_worker():
    while True:
        page, event = await standard_event_queue.get()
        try:
            await handle_standard_event(page, event)
        except Exception as e:
            logger.error(f"[Event Worker] Error processing event: {e}")
        standard_event_queue.task_done()

def flush_standard_event_queue():
    global standard_event_queue
    standard_event_queue = asyncio.Queue()
    logger.info("[Queue] Standard event queue flushed.")

async def inject_scripts(page):
    try:
        await page.add_init_script(selector_script_path.read_text("utf-8"))
        await page.add_init_script(recorder_script_path.read_text("utf-8"))
        await page.evaluate("window.__recorderInjected = true")
        logger.info("Recorder script injected")
    except Exception as e:
        logger.error(f"Script injection failed: {e}")

async def reinject_scripts_if_needed(page):
    try:
        injected = await page.evaluate("() => window.__recorderInjected === true")
        if not injected:
            await inject_scripts(page)
            logger.info("Recorder script re-injected")
    except Exception as e:
        logger.error(f"Reinjection failed: {e}")

async def handle_event(source, event):
    page = state.active_page
    type = event.get("type")
    if type == "targetPicked":
        await handle_target_picked(page, event)
    else:
        await standard_event_queue.put((page, event))

async def handle_standard_event(page, event):
    meta = {
        "tagName": event.get("tagName", ""),
        "id": event.get("id", ""),
        "name": event.get("name", ""),
        "classList": event.get("classList", []),
        "attributes": event.get("attributes", {}),
        "innerText": event.get("innerText", ""),
        "outerHTML": event.get("outerHTML", ""),
        "domPath": event.get("domPath", ""),
        "xpath": event.get("xpath", "")
    }

    # Extract dynamic parameter mapping if present
    attrs = event.get("attributes", {})

    if "data-dynamic-value" in attrs:
        event["dynamicValue"] = attrs["data-dynamic-value"]

    if "data-transform-type" in attrs and "data-transform" in attrs:
        transform_type = attrs["data-transform-type"]
        transform_value = attrs["data-transform"]

        event["transformType"] = transform_type
        event["transform"] = transform_value

        logger.info(f"[Transform Detected] {transform_type}: {transform_value}")
    else:
        logger.info("[Transform Detected] No transform type or value found.")

    if "data-botflows-mapped" in attrs:
        event["mappedScope"] = attrs["data-botflows-mapped"]

    # best_selector, selector_list = await generate_and_validate_selectors(meta, page, event, True)

    # Use best_selector in event["selector"]
    # Store selector_list in event["selectors"]


    # if best_selector:
    #     event["selector"] = best_selector
    # if selector_list and len(selector_list) > 0:
    #     event["selectors"] = selector_list
    #     logger.info(f"[Selector Validation] Primary set to: {best_selector}")
    #     await page.evaluate("window.postMessage({ type: 'validationComplete' }, '*')")
    # else:
    #     logger.warning("[Selector Validation] No valid selectors found, keeping original")

    recorded_events.append(event)
    try:
        await page.evaluate("window.hideValidationOverlay()")
        await page.evaluate("window.__pendingValidation = false")
    except Exception as e:
        logger.warning(f"Failed to clear pendingValidation: {e}")

    await broadcast_to_clients(event)

# async def handle_picker_event(page, event):
#     metadata = event.get("metadata", {})
#     original_selector = metadata.get("gridSelector")
#     row_selector = metadata.get("rowSelector")  # optional override
#     validated_grid_selector = None

#     if not original_selector:
#         logger.warning("[Picker] No gridSelector found in metadata")
#         return

#     # Try validating multiple variants of the grid selector
#     grid_selector_candidates = [
#         original_selector,
#         f"{original_selector} [role='grid']",
#         f"{original_selector} .MuiDataGrid-root",
#         f"{original_selector} table",
#         "[role='grid']",
#         ".MuiDataGrid-root",
#         "table"
#     ]

#     for candidate in grid_selector_candidates:
#         try:
#             await page.wait_for_selector(candidate, timeout=1500)
#             validated_grid_selector = candidate
#             logger.info(f"[Picker] Grid selector validated: {candidate}")
#             break
#         except:
#             continue

#     if not validated_grid_selector:
#         logger.warning("[Picker] Failed to validate any grid selector")
#         await page.evaluate("window.__pendingValidation = false")
#         return

#     # Try row selectors
#     possible_rows = []
#     if row_selector:
#         possible_rows.append(row_selector)
#     possible_rows += [
#         f"{validated_grid_selector} tr",
#         f"{validated_grid_selector} div[role='row']",
#         f"{validated_grid_selector} tbody > tr"
#     ]

#     validated_row_selector = None
#     for candidate in possible_rows:
#         try:
#             await page.wait_for_selector(candidate, timeout=1000)
#             validated_row_selector = candidate
#             logger.info(f"[Picker] Row selector validated: {candidate}")
#             break
#         except:
#             continue

#     if not validated_row_selector:
#         logger.warning("[Picker] No valid row selector found")
#         await page.evaluate("window.__pendingValidation = false")
#         return

#     # Update metadata with validated selectors
#     metadata["gridSelector"] = validated_grid_selector
#     metadata["rowSelector"] = validated_row_selector

#     response = {
#         "type": "targetPicked",
#         "metadata": metadata,
#         "timestamp": event.get("timestamp")
#     }

#     try:
#         await page.evaluate("window.__pendingValidation = false")
#     except Exception as e:
#         logger.warning(f"Failed to clear pendingValidation (picker): {e}")

#     await broadcast_to_clients(response)

async def handle_target_picked(page, event):
    try:
        await page.evaluate(analyzing_grid_overlay_script)

        metadata = event.get("metadata", {})
        outer_html = metadata.get("outerHTML")
        bounding_box = metadata.get("boundingBox")
        grid_selector = metadata.get("gridSelector")
        column_headers = metadata.get("columnHeaders", [])

        if not outer_html or not bounding_box or not grid_selector or not column_headers:
            logger.warning(f"outer_html or bounding_box or grid_selector or column_headers are empty")
            await page.evaluate("window.finishPicker && window.finishPicker()")
            await broadcast_to_clients({
                "type": "targetPicked",
                "metadata": {},
                "timestamp": event.get("timestamp")
            })
            return

        row_selector = f"{grid_selector} [role='row'], {grid_selector} tr"
        if not await validate_selector(page, row_selector):
            logger.warning(f"Row selector failed: {row_selector}")
            await page.evaluate("window.finishPicker && window.finishPicker()")
            await broadcast_to_clients({
                "type": "targetPicked",
                "metadata": {},
                "timestamp": event.get("timestamp")
            })
            return

        row_locator = page.locator(row_selector)
        row_count = await row_locator.count()
        sample_index = 1 if row_count > 1 else 0  # skip header row if possible
        sample_row = row_locator.nth(sample_index)

        successful_selectors = []
        column_mappings = []

        for idx, header in enumerate(column_headers):
            reusable = [s for s in successful_selectors if f"colindex='{idx}'" in s or f"nth-child({idx + 1})" in s]
            sel_patterns = reusable + [
                f"div[role='gridcell'][data-colindex='{idx}']",
                f"[role='cell']:nth-child({idx + 1})",
                f"td:nth-of-type({idx + 1})",
                f"td:nth-of-type({idx + 1}) input",
                f"td:nth-of-type({idx + 1}) div",
                f"td:nth-of-type({idx + 1}) *"
            ]
            matched_selector = None

            for sel in sel_patterns:
                try:
                    cell = sample_row.locator(sel)
                    await cell.wait_for(state="attached", timeout=800)
                    await cell.wait_for(state="visible", timeout=800)
                    txt = await cell.inner_text()
                    if txt.strip():
                        matched_selector = sel
                        if sel not in successful_selectors:
                            successful_selectors.append(sel)
                        break
                except:
                    continue

            column_mappings.append({
                "header": header,
                "columnIndex": idx,
                "selector": matched_selector or "",
                "extractable": bool(matched_selector),
                "preview": txt or ""
            })

        await broadcast_to_clients({
            "type": "targetPicked",
            "metadata": {
                "gridSelector": grid_selector,
                "boundingBox": bounding_box,
                "rowSelector": row_selector,
                "columnHeaders": column_headers,
                "columnMappings": column_mappings
            },
            "timestamp": event.get("timestamp")
        })

    finally:
        await page.evaluate(remove_grid_overlay_script)

async def find_clickable_ancestor(page, el_handle):
    return await page.evaluate_handle("""
        (el) => {
            function isClickable(e) {
                if (!e || e === document.body) return false;
                const style = window.getComputedStyle(e);
                return (
                    e.onclick ||
                    e.hasAttribute("data-test-id") ||
                    style.cursor === "pointer" ||
                    ["A", "BUTTON", "SUMMARY"].includes(e.tagName) ||
                    e.className.includes("clickable") ||
                    e.getAttribute("role") === "button"
                );
            }

            let current = el;
            while (current && current !== document.body) {
                if (isClickable(current)) return current;
                current = current.parentElement;
            }
            return el;  // fallback
        }
    """, el_handle)

async def try_scope_selector(page, selector: str, el_handle):
    """Attempts to scope a generic selector under a parent with ID or stable class."""
    try:
        parent = el_handle
        for _ in range(3):  # Go up to 3 levels up
            parent = await parent.evaluate_handle("el => el.parentElement")
            if not parent:
                break

            id_attr = await parent.evaluate("el => el.id")
            class_attr = await parent.evaluate("el => el.className")

            if id_attr:
                scoped = f"#{id_attr} {selector}"
                count = await page.eval_on_selector_all(scoped, "els => els.length")
                if count == 1:
                    return scoped

            if class_attr:
                first_class = class_attr.strip().split()[0]
                if first_class:
                    scoped = f".{first_class} {selector}"
                    count = await page.eval_on_selector_all(scoped, "els => els.length")
                    if count == 1:
                        return scoped
    except Exception as ex:
        print(f"[scoping failed] {ex}")
    return None

async def generate_and_validate_selectors(meta: dict, page, event, strict: bool = False):
    candidates = []
    action = event.get("action")
    value = event.get("value")
    if not action:
        raise Exception("action is null")

    el_handle = meta.get("elementHandle")
    if el_handle and action in ["click", "dblclick"]:
        try:
            better_handle = await find_clickable_ancestor(page, el_handle)
            if better_handle:
                meta["elementHandle"] = better_handle
        except Exception as ex:
            print(f"[Ancestor climb failed] {ex}")

    el_id = meta.get("id") or meta.get("attributes", {}).get("id")
    if el_id:
        is_generated = re.match(r"^(mat|cdk|ng)-", el_id)
        candidates.append({
            "selector": f"#{el_id}",
            "source": "id",
            "score": 70 if is_generated else 100
        })

    class_list = meta.get("classList", [])
    tag = meta.get("tagName", "").lower() or meta.get("tag", "").lower()

    # 🔧 Remove volatile classes
    stable_classes = [c for c in class_list if not re.match(r"^(cdk|ng|mat-legacy)-", c)]

    if tag and stable_classes:
        class_selector = f"{tag}." + ".".join(stable_classes)
        candidates.append({
            "selector": class_selector,
            "source": "class",
            "score": 70
        })

    inner_text = meta.get("innerText") or meta.get("elementText") or ""
    if tag and inner_text.strip():
        candidates.append({
            "selector": f'{tag}:has-text("{inner_text.strip()}")',
            "source": "has-text",
            "score": 60
        })

        prominent_class = next((c for c in stable_classes if len(c) > 5), None)
        if prominent_class:
            candidates.append({
                "selector": f'{tag}.{prominent_class}:has-text("{inner_text.strip()}")',
                "source": "has-text-combo",
                "score": 85
            })

    dom_path = meta.get("domPath") or meta.get("selector")
    if dom_path:
        candidates.append({
            "selector": dom_path,
            "source": "dom-path",
            "score": 50
        })

    xpath = meta.get("xpath")
    if xpath:
        candidates.append({
            "selector": xpath,
            "source": "xpath",
            "score": 40
        })

    if not candidates and "elementHandle" in meta:
        devtools_selector = await get_devtools_like_selector(meta["elementHandle"])
        if devtools_selector:
            candidates.append({
                "selector": devtools_selector,
                "source": "devtools",
                "score": 40
            })

    # Deduplicate
    seen = set()
    unique_candidates = []
    for c in candidates:
        if c["selector"] not in seen:
            unique_candidates.append(c)
            seen.add(c["selector"])

    validated = []
    for sel in unique_candidates:
        try:
            if sel["source"] == "xpath":
                count = await page.evaluate(f"""
                    () => document.evaluate("{sel['selector']}", document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null).snapshotLength
                """)
            else:
                count = await page.evaluate(f'document.querySelectorAll("{sel["selector"]}").length')

            sel["matchCount"] = count

            if count == 1:
                sel["verified"] = True
                sel["score"] += 30
            elif count > 1:
                scoped = await try_scope_selector(page, sel["selector"], meta["elementHandle"])
                if scoped:
                    sel["selector"] = scoped
                    sel["score"] += 10
                    sel["matchCount"] = 1
                    sel["verified"] = True
            else:
                sel["verified"] = False

            sel["replayable"] = False
            if strict and sel["verified"]:
                locator = page.locator(sel["selector"])
                if action == "click":
                    await locator.first.wait_for(state="visible", timeout=3000)
                    await locator.first.hover()
                    await locator.first.click(timeout=2000, trial=True)
                elif action in ["type", "change"]:
                    await locator.first.wait_for(state="attached", timeout=3000)
                    await locator.first.fill(value or "", timeout=2000)
                elif action == "select":
                    await locator.first.wait_for(state="attached", timeout=3000)
                    await locator.first.select_option("option1", timeout=2000)

                sel["replayable"] = True

        except Exception:
            sel["verified"] = False
            sel["replayable"] = False
            sel["score"] -= 25
            sel["matchCount"] = 0

        validated.append(sel)

    validated.sort(key=lambda x: (x.get("replayable", False), x["score"]), reverse=True)
    best_selector = validated[0]["selector"] if validated else None

    return best_selector, validated

async def broadcast_to_clients(message):
    for ws in state.connections:
        try:
            await ws.send_text(json.dumps(message))
            logger.debug(f"[WS] Broadcasted: {message}")
        except Exception as e:
            logger.warning(f"WebSocket broadcast failed: {e}")

async def handle_url_change(source, new_url):
    logger.info(f"SPA navigation detected: {new_url}")
    page = state.active_page
    await page.evaluate(overlay_script)
    state.active_dom_snapshot = await page.content()
    await page.evaluate(remove_overlay_script)
    await upload_snapshot_to_api(new_url, state.active_dom_snapshot)
    await reinject_scripts_if_needed(page)

async def record(url: str):
    global recorded_events
    recorded_events = []
    logger.info(f"[Recorder] Starting session: {url}")
    flush_standard_event_queue()
    state.is_replaying = False
    if state.worker_task:
        state.worker_task.cancel()
        try:
            await state.worker_task
        except asyncio.CancelledError:
            logger.info("[Recorder] Event worker cancelled.")
        state.worker_task = None

    # Start the event worker
    if not state.worker_task or state.worker_task.done():
        state.worker_task = asyncio.create_task(standard_event_worker())

    async with async_playwright() as p:
        browser = await launch_chrome(p)
        context = browser.contexts[0] if browser.contexts else await browser.new_context(no_viewport=True)

        for tab in context.pages:
            if tab.url == "about:blank":
                await tab.close()

        page = await context.new_page()
        state.active_page = page

        await state.active_page.evaluate("""() => {
        window.__botflows_replaying__ = false;
        const div = document.getElementById('botflows-replay-overlay');
        if (div) div.remove();
        }""")

        await context.expose_binding("sendEventToPython", handle_event)
        await context.expose_binding("sendUrlChangeToPython", handle_url_change)

        await page.add_init_script(selector_script_path.read_text("utf-8"))
        await page.add_init_script(recorder_script_path.read_text("utf-8"))

        if state.pick_mode:
            await page.add_init_script("window.__pickModeActive = true")
            await page.add_init_script(preview_script_path.read_text("utf-8"))  # ✅ NEW

        await page.goto("about:blank")
        await page.evaluate(overlay_script)

        await page.goto(url)
        await page.wait_for_load_state("networkidle")

        state.active_dom_snapshot = await page.content()
        await page.evaluate(remove_overlay_script)
        await upload_snapshot_to_api(url, state.active_dom_snapshot)

        async def reinject_on_spa_change(new_url):
            logger.info(f"[Recorder] SPA navigation: {new_url}")
            await page.evaluate(overlay_script)
            await asyncio.sleep(0.5)
            await page.evaluate(remove_overlay_script)
            await page.add_init_script(selector_script_path.read_text("utf-8"))
            await page.add_init_script(recorder_script_path.read_text("utf-8"))
            await reinject_scripts_if_needed(page)
            if state.pick_mode:
                await page.evaluate("window.__pickModeActive = true")
                await page.add_init_script(preview_script_path.read_text("utf-8"))  # ✅ NEW
            snapshot = await page.content()
            state.active_dom_snapshot = snapshot
            await upload_snapshot_to_api(new_url, snapshot)

        page.on("framenavigated", lambda frame: asyncio.create_task(reinject_on_spa_change(frame.url)))

        async def wait_for_tab_close():
            while not page.is_closed():
                await asyncio.sleep(1)
            if not state.pick_mode:
                state.is_recording = False
                state.worker_task = None
                logger.info("Tab closed, recording stopped")

        async def wait_for_stop_flag():
            while state.is_recording:
                await asyncio.sleep(1)
            if not state.pick_mode:
                state.worker_task = None
                logger.info("Recording manually stopped")

        try:
            await asyncio.wait([
                asyncio.create_task(wait_for_tab_close()),
                asyncio.create_task(wait_for_stop_flag())
            ], return_when=asyncio.FIRST_COMPLETED)
        finally:
            await browser.close()
            logger.info(f"[Recorder] Session complete. {len(recorded_events)} events captured.")
