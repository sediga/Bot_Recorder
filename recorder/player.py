import sys, os
import logging
import asyncio
import sys
import json
from pathlib import Path
from playwright.async_api import async_playwright

# Handle PyInstaller _MEIPASS path

logger = logging.getLogger(__name__)

def load_actions(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)

async def replay_actions(url, actions):
    logger.debug(f"Replaying actions for: {url}")
    async with async_playwright() as p:
        logger.debug("Launching browser...")
        browser = await p.chromium.launch(headless=False)
        logger.debug("Creating new browser context...")
        context = await browser.new_context()
        logger.debug("Creating new page...")
        page = await context.new_page()
        logger.debug(f"Navigating to {url}...")
        await page.goto(url)

        for action in actions:
            logger.debug(f"Performing action: {action}")
            act = action["action"]
            selector = action.get("selector")
            value = action.get("value")
            key = action.get("key")

            try:
                await _perform_action(act, page, selector=selector, value=value, key=key)
            except Exception as e:
                logger.debug(f"Unexpected error on {act} / {selector}: {e}")

        logger.debug("Replay complete.")
        await browser.close()

async def _perform_action(action, page, selector=None, value=None, key=None, retries=3):
    await asyncio.sleep(1)
    logger = logging.getLogger("botflows-agent")

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
            await try_in_frame(page, action, selector, value, key)
            return
        except Exception as e:
            logger.debug(f"Attempt {attempt} failed on main page for {action} on {selector}: {e}")
            for frame in page.frames:
                try:
                    await try_in_frame(frame, action, selector, value, key)
                    logger.debug(f"Success inside frame: {frame.url}")
                    return
                except:
                    continue

            if action == "click" and attempt == retries:
                try:
                    await page.wait_for_selector(selector, state="attached", timeout=3000)
                    await page.click(selector, force=True, timeout=3000)
                    logger.debug(f"Force click succeeded on main page: {selector}")
                    return
                except Exception as fe:
                    logger.error(f"Force click failed: {fe}")
            await asyncio.sleep(2)

# ✅ Call this from your API
async def start_replay(path_to_json: str):
    path = Path(path_to_json)
    if not path.exists():
        raise FileNotFoundError(f"Replay file not found: {path}")

    data = load_actions(path)
    url = list(data.keys())[0]
    actions = data[url]
    await replay_actions(url, actions)

# CLI support
# if __name__ == "__main__":
#     logger.debug("player.py executing")
#     if len(sys.argv) < 2:
#         logger.debug("Usage: player.py <path_to_json>")
#         sys.exit(1)

#     asyncio.run(start_replay(sys.argv[1]))
