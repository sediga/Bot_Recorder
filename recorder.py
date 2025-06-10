import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

recorded_events = []
output_path = Path("recorded_actions.json")
recorded_actions_json = {}
with open(output_path, "r") as f:
    content = f.read().strip()
    if not content:
        print("⚠️ recorded_actions.json is empty.")
        recorded_actions_json = {}
    else:
        recorded_actions_json = json.loads(content)

async def handle_event(source, event):
    recorded_events.append(event)
    print("Recorded:", event)

async def run():
    script_path = Path("./javascript/recorder.js")

    if not script_path.exists():
        print("Missing recorder.js file")
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=50)
        context = await browser.new_context()
        page = await context.new_page()

        # Bind JS to Python
        await context.expose_binding("sendEventToPython", handle_event)

        # Inject the JS recorder
        await context.add_init_script(script_path.read_text(encoding="utf-8"))

        print("please enter url : ")
        url = input().strip()
        # Go to the target site
        await page.goto(url)  # Replace with your target

        try:
            print("Recording... Press ENTER to stop.")
            input()
            await browser.close()
        except KeyboardInterrupt:
            print("Recording interrupted.")
        finally:
            recorded_actions_json[url] = recorded_events
            output_path.write_text(json.dumps(recorded_actions_json, indent=2))
            # with open(output_path, "w") as f:
            #     json.dump(recorded_events, f, indent=2)
            print(f"Saved {len(recorded_events)} events to {output_path}")
            await browser.close()
            print("Recording session ended.")

        # # Save the results
 

if __name__ == "__main__":
    asyncio.run(run())
