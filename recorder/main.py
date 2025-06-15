# main.py
import logging
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright
import sys
import os

logger = logging.getLogger(__name__)
recorded_events = []

# Resolve base path for PyInstaller or dev
BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent.resolve()))
script_path = BASE_DIR / "javascript" / "recorder.bundle.js"
log_path = BASE_DIR / "../dataset/selector_logs.jsonl"
live_events_log = BASE_DIR / "../dataset/live_events.jsonl"
output_path = BASE_DIR / "../recordings/recorded_actions.json"

# Ensure required folders
os.makedirs(log_path.parent, exist_ok=True)

recorded_actions_json = {}
if output_path.exists():
    content = output_path.read_text(encoding="utf-8").strip()
    recorded_actions_json = json.loads(content) if content else {}

def append_event(event):
    with open(live_events_log, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")

async def handle_event(source, event):
    recorded_events.append(event)
    append_event(event)
    logger.debug("Recorded:", event)

async def handle_log(source, log_data):
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            json.dump(log_data, f)
            f.write("\n")
        logger.debug("Logged selector data.")
    except Exception as e:
        logger.debug(f"Failed to log selector: {e}")

async def handle_url_change(source, new_url):
    logger.debug(f"Detected SPA URL change to: {new_url}")
    page = source._context.pages[0]
    await reinject_script(page)

async def inject_script(page):
    try:
        await page.add_init_script(script_path.read_text(encoding="utf-8"))
        await page.evaluate("window.__recorderInjected = true")
        logger.debug("Script injected")
    except Exception as e:
        logger.debug(f"Injection failed: {e}")

async def reinject_script(page):
    try:
        is_injected = await page.evaluate("() => window.__recorderInjected === true")
        if not is_injected:
            logger.debug("Reinjecting recorder after navigation...")
            await page.evaluate(script_path.read_text(encoding="utf-8"))
            await page.evaluate("window.__recorderInjected = true")
        else:
            logger.debug("Recorder already present")
    except Exception as e:
        logger.debug(f"Reinjection failed: {e}")

async def delete_stop_file():
    stop_file = Path("recordings/stop.flag")
    if stop_file.exists():
        logger.debug("Stop flag detected... deleting stop file.")
        stop_file.unlink(missing_ok=True)

async def wait_for_stop():
    stop_file = Path("recordings/stop.flag")
    logger.debug("Waiting for stop signal...")
    while not stop_file.exists():
        await asyncio.sleep(1)
    logger.debug("Stop flag detected.")
    stop_file.unlink(missing_ok=True)

def deduplicate_events(events, time_threshold_ms=200):
    seen, deduped = [], []
    for event in events:
        if event["action"] != "click":
            deduped.append(event)
            continue
        ts = event["timestamp"]
        if any(e["action"] == "click" and abs(e["timestamp"] - ts) <= time_threshold_ms for e in seen):
            continue
        deduped.append(event)
        seen.append(event)
    return deduped

# ✅ Call this from API
async def record(url: str):
    logger.debug(f"Recording URL: {url}")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()

        await context.expose_binding("sendEventToPython", handle_event)
        await context.expose_binding("sendUrlChangeToPython", handle_url_change)
        await context.expose_binding("sendLogToPython", handle_log)

        page = await context.new_page()
        await inject_script(page)
        await page.goto(url)

        try:
            await delete_stop_file()
            await wait_for_stop()
        finally:
            deduped = deduplicate_events(recorded_events)
            recorded_actions_json[url] = deduped
            output_path.write_text(json.dumps(recorded_actions_json, indent=2))
            logger.debug(f"Saved {len(deduped)} events to {output_path}")
            await browser.close()

# CLI support
# if __name__ == "__main__":
#     logger.debug("main.py executing")
#     url_arg = sys.argv[1] if len(sys.argv) > 1 else input("Enter URL: ").strip()
#     asyncio.run(start_recording(url_arg))
