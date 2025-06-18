import logging
import asyncio
import json
import subprocess
import psutil
import time
import socket
from pathlib import Path
from playwright.async_api import async_playwright
import sys
import os
from ui.config_ui import load_config
from common import state
from common.browserutil import launch_chrome, wait_for_debug_port

logger = logging.getLogger(__name__)
recorded_events = []

# Resolve paths
BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent.resolve()))
script_path = BASE_DIR / "javascript" / "recorder.bundle.js"
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
    recorded_events.append(event)
    append_event(event)
    logger.debug(f"Recorded: {event}")

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
    await reinject_script(page)

async def inject_script(page):
    try:
        await page.add_init_script(script_path.read_text(encoding="utf-8"))
        await page.evaluate("window.__recorderInjected = true")
        logger.info("Recorder script injected")
    except Exception as e:
        logger.error(f"Script injection failed: {e}")

async def reinject_script(page):
    try:
        injected = await page.evaluate("() => window.__recorderInjected === true")
        if not injected:
            await page.evaluate(script_path.read_text(encoding="utf-8"))
            await page.evaluate("window.__recorderInjected = true")
            logger.info("Recorder script re-injected")
    except Exception as e:
        logger.error(f"Reinjection failed: {e}")

def deduplicate_events(events, threshold_ms=200):
    seen, deduped = [], []
    for event in events:
        if event["action"] != "click":
            deduped.append(event)
            continue
        ts = event["timestamp"]
        if any(e["action"] == "click" and abs(e["timestamp"] - ts) <= threshold_ms for e in seen):
            continue
        deduped.append(event)
        seen.append(event)
    return deduped

async def record(url: str):
    global recorded_events
    recorded_events = []
    logger.info(f"Starting recording session: {url}")

    async with async_playwright() as p:
        browser = await launch_chrome(p)  # unified method handles both modes

        context = browser.contexts[0] if browser.contexts else await browser.new_context(no_viewport=True)

        for tab in context.pages:
            if tab.url == "about:blank":
                await tab.close()

        page = await context.new_page()

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
