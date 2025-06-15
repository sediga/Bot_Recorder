import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright
import os
import sys

recorded_events = []
output_path = Path("./recordings/recorded_actions.json")
script_path = Path("./javascript/recorder.bundle.js")
log_path = Path("dataset/selector_logs.jsonl")

live_events_log = Path("dataset/live_events.jsonl")

def append_event(event):
    with open(live_events_log, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")

os.makedirs(log_path.parent, exist_ok=True)

# Load existing recordings
recorded_actions_json = {}
if output_path.exists():
    content = output_path.read_text().strip()
    recorded_actions_json = json.loads(content) if content else {}

# Handle recorded user action (e.g., click with selector)
async def handle_event(source, event):
    recorded_events.append(event)
    append_event(event=event)  # Append to live events log
    print("🎯 Recorded:", event)

# Handle structured selector log for AI training
async def handle_log(source, log_data):
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            json.dump(log_data, f)
            f.write("\n")
        print("📝 Logged selector data.")
    except Exception as e:
        print(f"❌ Failed to log selector: {e}")

# SPA or navigation-triggered reinjection
async def handle_url_change(source, new_url):
    print(f"🔄 Detected SPA URL change to: {new_url}")
    page = source._context.pages[0]
    await reinject_script(page)

# One-time script injection
async def inject_script(page):
    try:
        await page.add_init_script(script_path.read_text(encoding="utf-8"))
        await page.evaluate("window.__recorderInjected = true")
        print("✅ Script injected")
    except Exception as e:
        print(f"⚠️ Injection failed: {e}")

# On URL change, re-inject only if needed
async def reinject_script(page):
    try:
        is_injected = await page.evaluate("() => window.__recorderInjected === true")
        if not is_injected:
            print("🔁 Reinjecting recorder after navigation...")
            await page.evaluate(script_path.read_text(encoding="utf-8"))
            await page.evaluate("window.__recorderInjected = true")
        else:
            print("✅ Recorder already present")
    except Exception as e:
        print(f"⚠️ Reinjection failed: {e}")

# Main entry point
async def run(args=None):
    if args is None:
        args = sys.argv[1:]
    url = sys.argv[1] if len(sys.argv) > 1 else input("Enter URL: ").strip()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=50)
        context = await browser.new_context()

        await context.expose_binding("sendEventToPython", handle_event)
        await context.expose_binding("sendUrlChangeToPython", handle_url_change)
        await context.expose_binding("sendLogToPython", handle_log)  # ✅ New binding

        page = await context.new_page()
        await inject_script(page)

        # url = input("Please enter URL: ").strip()
        await page.goto(url)

        try:
            print("Recording... Press ENTER to stop.")
            await wait_for_stop()
        finally:
            deduped = deduplicate_events(recorded_events)
            recorded_actions_json[url] = deduped
            output_path.write_text(json.dumps(recorded_actions_json, indent=2))
            print(f"✅ Saved {len(deduped)} events to {output_path}")
            await browser.close()

async def wait_for_stop():
    stop_file = Path("recordings/stop.flag")
    print("⏺ Waiting for stop signal...")

    while not stop_file.exists():
        await asyncio.sleep(1)

    print("⏹ Stop flag detected.")
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

if __name__ == "__main__":
    asyncio.run(run())
