import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

recorded_events = []
output_path = Path("recorded_actions.json")
script_path = Path("./javascript/recorder.bundle.js")

# Load existing recordings
recorded_actions_json = {}
if output_path.exists():
    content = output_path.read_text().strip()
    recorded_actions_json = json.loads(content) if content else {}

async def handle_event(source, event):
    recorded_events.append(event)
    print("Recorded:", event)

async def handle_url_change(source, new_url):
    print(f"🔄 Detected SPA URL change to: {new_url}")
    page = source._context.pages[0]
    await reinject_script(page)

async def inject_script(page):
    try:
        await page.add_init_script(script_path.read_text(encoding="utf-8"))
        await page.evaluate("window.__recorderInjected = true")
        print("✅ Script injected")
    except Exception as e:
        print(f"⚠️ Injection failed: {e}")

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

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=50)
        context = await browser.new_context()

        await context.expose_binding("sendEventToPython", handle_event)
        await context.expose_binding("sendUrlChangeToPython", handle_url_change)

        page = await context.new_page()
        await inject_script(page)

        url = input("Please enter URL: ").strip()
        await page.goto(url)

        try:
            print("Recording... Press ENTER to stop.")
            await asyncio.to_thread(input)
        finally:
            deduped = deduplicate_events(recorded_events)
            recorded_actions_json[url] = deduped
            output_path.write_text(json.dumps(recorded_actions_json, indent=2))
            print(f"✅ Saved {len(deduped)} events to {output_path}")
            await browser.close()

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