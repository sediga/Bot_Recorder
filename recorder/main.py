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
from common import state

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

def is_chrome_running_with_debug(port=9222):
    for proc in psutil.process_iter(attrs=["name", "cmdline"]):
        try:
            if "chrome.exe" in proc.info["name"].lower():
                if f"--remote-debugging-port={port}" in " ".join(proc.info["cmdline"]).lower():
                    return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False

def is_port_open(host="localhost", port=9222):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        try:
            sock.connect((host, port))
            return True
        except socket.error:
            return False

def launch_chrome_debug(port=9222):
    user_profile_dir = "C:\\Users\\sreen\\AppData\\Local\\Botflows\\ChromeProfile"
    os.makedirs(user_profile_dir, exist_ok=True)

    if not is_chrome_running_with_debug(port):
        subprocess.Popen([
            "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={user_profile_dir}",
            "--no-first-run",
            "--no-default-browser-check"
        ])
        logger.info("Launched Chrome with debugging port and user profile")
    else:
        logger.info("Chrome already running with required debugging port")

def wait_until_chrome_ready(timeout=10):
    logger.info("Waiting for Chrome CDP port to be available...")
    for _ in range(timeout * 2):
        if is_port_open("localhost", 9222):
            logger.info("Chrome is ready")
            return
        time.sleep(0.5)
    raise RuntimeError("Chrome with --remote-debugging-port=9222 not responding")

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

    launch_chrome_debug()
    wait_until_chrome_ready()

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:9222")
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
            logger.info("Tab closed")

        async def wait_for_stop_flag():
            while state.is_recording:
                await asyncio.sleep(1)
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
