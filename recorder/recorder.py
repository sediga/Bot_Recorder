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
log_path = BASE_DIR / "../dataset/selector_logs.jsonl"
live_events_log = BASE_DIR / "../dataset/live_events.jsonl"
output_path = BASE_DIR / "../recordings/recorded_actions.json"

os.makedirs(log_path.parent, exist_ok=True)

recorded_actions_json = {}
if output_path.exists():
    content = output_path.read_text(encoding="utf-8").strip()
    recorded_actions_json = json.loads(content) if content else {}

def append_event(event):
    with open(live_events_log, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")

async def handle_event(source, event):
    append_event(event)
    recorded_events.append(event)

    try:
        if state.pick_mode and state.is_recording:
            event = await selectorHelper.validate_and_enrich_selector(event)
    except Exception as e:
        logger.warning(f"Failed to enrich selector: {e}")

    for ws in state.connections:
        try:
            await ws.send_text(json.dumps(event))
            logger.debug(f"[WS] Broadcasted event: {event}")
        except Exception as e:
            logger.warning(f"WebSocket broadcast failed: {e}")

async def handle_log(source, log_data):
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            json.dump(log_data, f)
            f.write("\n")
    except Exception as e:
        logger.warning(f"Failed to log selector: {e}")

async def handle_url_change(source, new_url):
    logger.info(f"SPA navigation detected: {new_url}")
    page = source._context.pages[0]
    await page.evaluate(overlay_script)
    state.active_dom_snapshot = await page.content()
    await page.evaluate(remove_overlay_script)
    await upload_snapshot_to_api(new_url, state.active_dom_snapshot)
    await reinject_script(page)

async def inject_script(page):
    try:
        await page.add_init_script(selector_script_path.read_text(encoding="utf-8"))
        await page.add_init_script(recorder_script_path.read_text(encoding="utf-8"))
        await page.evaluate("window.__recorderInjected = true")
        logger.info("Recorder script injected")
    except Exception as e:
        logger.error(f"Script injection failed: {e}")

async def reinject_script(page):
    try:
        injected = await page.evaluate("() => window.__recorderInjected === true")
        if not injected:
            await page.add_init_script(selector_script_path.read_text(encoding="utf-8"))
            await page.add_init_script(recorder_script_path.read_text(encoding="utf-8"))
            await page.evaluate("window.__recorderInjected = true")
            logger.info("Recorder script re-injected")
    except Exception as e:
        logger.error(f"Reinjection failed: {e}")

def deduplicate_events(events, threshold_ms=200):
    seen, deduped = [], []
    for event in events:
        action = event.get("action")  # use .get() to avoid KeyError
        if action != "click":
            deduped.append(event)
            continue
        ts = event.get("timestamp", 0)
        if any(e.get("action") == "click" and abs(e.get("timestamp", 0) - ts) <= threshold_ms for e in seen):
            continue
        deduped.append(event)
        seen.append(event)
    return deduped


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

async def record(url: str):
    global recorded_events
    recorded_events = []
    logger.info(f"Starting recording session: {url}")

    async with async_playwright() as p:
        browser = await launch_chrome(p)

        context = browser.contexts[0] if browser.contexts else await browser.new_context(no_viewport=True)

        for tab in context.pages:
            if tab.url == "about:blank":
                await tab.close()

        page = await context.new_page()

        await page.goto("about:blank")
        await page.evaluate(overlay_script)

        await context.expose_binding("sendEventToPython", handle_event)
        await context.expose_binding("sendUrlChangeToPython", handle_url_change)
        await context.expose_binding("sendLogToPython", handle_log)

        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
        """)

        await inject_script(page)
        await page.goto(url)
        await page.wait_for_load_state("networkidle")
        state.active_page = page
        state.active_dom_snapshot = await page.content()
        await page.evaluate(remove_overlay_script)
        await upload_snapshot_to_api(url, state.active_dom_snapshot)

        async def wait_for_tab_close():
            while not page.is_closed():
                await asyncio.sleep(1)
            state.is_recording = False
            logger.info("Tab closed")

        async def wait_for_stop_flag():
            while state.is_recording:
                await asyncio.sleep(1)
            state.is_recording = False
            logger.info("Recording manually stopped")

        try:
            await asyncio.wait([
                asyncio.create_task(wait_for_tab_close()),
                asyncio.create_task(wait_for_stop_flag())
            ], return_when=asyncio.FIRST_COMPLETED)
        finally:
            deduped = deduplicate_events(recorded_events)
            recorded_actions_json[url] = deduped
            output_path.write_text(json.dumps(recorded_actions_json, indent=2))
            await browser.close()
            logger.info(f"Saved {len(deduped)} actions to {output_path}")
