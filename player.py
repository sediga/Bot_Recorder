import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

async def run():
    # Load recorded actions
    file_path = Path("recorded_actions.json")
    if not file_path.exists():
        print("⚠️ recorded_actions.json not found.")
        return

    with open(file_path, "r") as f:
        recordings = json.load(f)

    # Pick a URL to replay
    urls = list(recordings.keys())
    if not urls:
        print("⚠️ No recordings found in JSON.")
        return

    print("Available recordings:")
    for idx, url in enumerate(urls):
        print(f"{idx + 1}. {url}")

    selection = input("Enter number to replay (default 1): ").strip()
    selected_index = int(selection) - 1 if selection else 0
    selected_url = urls[selected_index]
    actions = recordings[selected_url]

    # Start browser and go to URL
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=100)
        context = await browser.new_context()
        page = await context.new_page()

        print(f"🔁 Replaying actions for {selected_url}")
        await page.goto(selected_url)

        for action in actions:
            act = action["action"]
            selector = action.get("selector")
            value = action.get("value")
            key = action.get("key")

            try:
                await _perform_action(act, page, selector=selector, value=value, key=key)
                # Add more cases as needed (e.g., submit)
            except Exception as e:
                # await page.wait_for_selector(selector)
                # await _perform_action(act, page, selector=selector, value=value, key=key)
                print(f"❌ Failed {act} on {selector}: {e}")

        print("✅ Replay finished.")
        input()
        await browser.close()

async def _perform_action(action, page, selector=None, value=None, key=None):
    await asyncio.sleep(1)  # Small delay to mimic human interaction
    if action == "click":
        if selector:
            return await page.click(selector)
    elif action == "type":
        if selector and value:
            return await page.fill(selector, value)
    elif action == "press":
        if key:
            return await page.keyboard.press(key)
    elif action == "select":
        if selector and value:
            return await page.select_option(selector, value)
    # Add more actions as needed
    # raise ValueError(f"Unknown action: {action}")

if __name__ == "__main__":
    asyncio.run(run())
