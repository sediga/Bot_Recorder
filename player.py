import asyncio
import sys
import json
from pathlib import Path
from playwright.async_api import async_playwright

async def run(args=None):
    if args is None:
        args = sys.argv[1:]
    # Load recorded actions
    file_path = Path("recordings/_replay_temp.json")
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

    # selection = input("Enter number to replay (default 1): ").strip()
    # selected_index = int(selection) - 1 if selection else 0
    selected_url = urls[0]
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
            except Exception as e:
                print(f"❌ Unexpected error on {act} / {selector}: {e}")

        print("✅ Replay finished.")
        input()
        await browser.close()

async def _perform_action(action, page, selector=None, value=None, key=None, retries=3):
    await asyncio.sleep(1)

    async def try_in_frame(frame, action, selector, value, key):
        if action == "click":
            await frame.wait_for_selector(selector, state="visible", timeout=5000)
            return await frame.click(selector, timeout=5000)
        elif action == "type":
            await frame.wait_for_selector(selector, state="attached", timeout=5000)
            return await frame.fill(selector, value)
        elif action == "press":
            return await frame.keyboard.press(key)
        elif action == "select":
            await frame.wait_for_selector(selector, state="attached", timeout=5000)
            return await frame.select_option(selector, value)

    for attempt in range(1, retries + 1):
        try:
            # Try on main page
            await try_in_frame(page, action, selector, value, key)
            return
        except Exception as e:
            print(f"⏳ Attempt {attempt} failed on main page for {action} on {selector}: {e}")

            # Try inside all frames
            for frame in page.frames:
                try:
                    await try_in_frame(frame, action, selector, value, key)
                    print(f"✅ Success inside frame: {frame.url}")
                    return
                except:
                    continue  # Try next frame

            # Final fallback: force click if it's a click action
            if action == "click" and attempt == retries:
                try:
                    await page.wait_for_selector(selector, state="attached", timeout=3000)
                    await page.click(selector, force=True, timeout=3000)
                    print(f"✅ Force click succeeded on main page: {selector}")
                    return
                except Exception as fe:
                    print(f"❌ Force click failed: {fe}")

            await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(run())
