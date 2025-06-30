import logging
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright
import sys
import os
from common import state
from common.browserutil import launch_chrome
from common.dom_snapshot import upload_snapshot_to_api
from common import selectorHelper

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
        await handle_picker_event(page, event)
    else:
        await handle_standard_event(page, event)

async def handle_standard_event(page, event):
    raw_selectors = event.get("selectors", [])
    if not raw_selectors:
        logger.warning("No selectors found in event")
        return

    validated = await validate_selectors(page, raw_selectors)

    if validated:
        event["selector"] = validated[0]["selector"]
        event["selectors"] = validated
        logger.info(f"[Selector Validation] Primary set to: {validated[0]['selector']}")
    else:
        logger.warning("[Selector Validation] No valid selectors found, keeping original")

    recorded_events.append(event)
    try:
        await page.evaluate("window.hideValidationOverlay()")
        await page.evaluate("window.__pendingValidation = false")
    except Exception as e:
        logger.warning(f"Failed to clear pendingValidation: {e}")

    await broadcast_to_clients(event)

async def handle_picker_event(page, event):
    metadata = event.get("metadata", {})
    original_selector = metadata.get("gridSelector")
    row_selector = metadata.get("rowSelector")  # optional override
    validated_grid_selector = None

    if not original_selector:
        logger.warning("[Picker] No gridSelector found in metadata")
        return

    # Try validating multiple variants of the grid selector
    grid_selector_candidates = [
        original_selector,
        f"{original_selector} [role='grid']",
        f"{original_selector} .MuiDataGrid-root",
        f"{original_selector} table",
        "[role='grid']",
        ".MuiDataGrid-root",
        "table"
    ]

    for candidate in grid_selector_candidates:
        try:
            await page.wait_for_selector(candidate, timeout=1500)
            validated_grid_selector = candidate
            logger.info(f"[Picker] Grid selector validated: {candidate}")
            break
        except:
            continue

    if not validated_grid_selector:
        logger.warning("[Picker] Failed to validate any grid selector")
        await page.evaluate("window.__pendingValidation = false")
        return

    # Try row selectors
    possible_rows = []
    if row_selector:
        possible_rows.append(row_selector)
    possible_rows += [
        f"{validated_grid_selector} tr",
        f"{validated_grid_selector} div[role='row']",
        f"{validated_grid_selector} tbody > tr"
    ]

    validated_row_selector = None
    for candidate in possible_rows:
        try:
            await page.wait_for_selector(candidate, timeout=1000)
            validated_row_selector = candidate
            logger.info(f"[Picker] Row selector validated: {candidate}")
            break
        except:
            continue

    if not validated_row_selector:
        logger.warning("[Picker] No valid row selector found")
        await page.evaluate("window.__pendingValidation = false")
        return

    # Update metadata with validated selectors
    metadata["gridSelector"] = validated_grid_selector
    metadata["rowSelector"] = validated_row_selector

    response = {
        "type": "targetPicked",
        "metadata": metadata,
        "timestamp": event.get("timestamp")
    }

    try:
        await page.evaluate("window.__pendingValidation = false")
    except Exception as e:
        logger.warning(f"Failed to clear pendingValidation (picker): {e}")

    await broadcast_to_clients(response)


async def validate_selectors(page, selectors):
    validated = []
    for sel in selectors:
        try:
            await page.wait_for_selector(sel["selector"], timeout=1500)
            sel["score"] = sel.get("score", 50) + 20
            sel["verified"] = True
            validated.append(sel)
        except:
            sel["verified"] = False
    return sorted(validated, key=lambda x: x.get("score", 0), reverse=True)

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

    async with async_playwright() as p:
        browser = await launch_chrome(p)
        context = browser.contexts[0] if browser.contexts else await browser.new_context(no_viewport=True)

        for tab in context.pages:
            if tab.url == "about:blank":
                await tab.close()

        page = await context.new_page()
        state.active_page = page

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
                logger.info("Tab closed, recording stopped")

        async def wait_for_stop_flag():
            while state.is_recording:
                await asyncio.sleep(1)
            if not state.pick_mode:
                logger.info("Recording manually stopped")

        try:
            await asyncio.wait([
                asyncio.create_task(wait_for_tab_close()),
                asyncio.create_task(wait_for_stop_flag())
            ], return_when=asyncio.FIRST_COMPLETED)
        finally:
            await browser.close()
            logger.info(f"[Recorder] Session complete. {len(recorded_events)} events captured.")
