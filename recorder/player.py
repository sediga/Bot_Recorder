import asyncio
import json
import logging
import os
from pathlib import Path
from typing import List, Union
from playwright.async_api import async_playwright, Page
from common import state

logger = logging.getLogger("botflows-player")
logging.basicConfig(level=logging.DEBUG)


async def _perform_action(page: Page, action: str, selector=None, value=None, key=None, retries=3):
    await asyncio.sleep(1)

    async def try_action(target_page):
        if action == "click":
            await target_page.wait_for_selector(selector, state="visible", timeout=5000)
            return await target_page.click(selector, timeout=5000)
        elif action == "type":
            await target_page.wait_for_selector(selector, state="attached", timeout=5000)
            return await target_page.fill(selector, value)
        elif action == "press":
            return await target_page.keyboard.press(key)
        elif action == "select":
            await target_page.wait_for_selector(selector, state="attached", timeout=5000)
            return await target_page.select_option(selector, value)
        elif action in ["mousedown", "focus", "blur"]:
            await target_page.wait_for_selector(selector, state="attached", timeout=5000)
            return await target_page.dispatch_event(selector, action)

    for attempt in range(1, retries + 1):
        try:
            await try_action(page)
            return
        except Exception as e:
            logger.warning(f"Attempt {attempt} failed on main page: {action} / {selector} => {e}")
            for frame in page.frames:
                try:
                    await try_action(frame)
                    logger.debug(f"Success inside frame: {frame.url}")
                    return
                except:
                    continue
            if action == "click" and attempt == retries:
                try:
                    await page.click(selector, force=True, timeout=3000)
                    logger.info(f"Force click succeeded: {selector}")
                    return
                except Exception as fe:
                    logger.error(f"Force click failed: {fe}")
            await asyncio.sleep(1)


async def handle_step(step: dict, page: Page):
    if step["type"] == "uiAction":
        await _perform_action(
            page,
            step.get("action"),
            step.get("selector"),
            step.get("value"),
            step.get("key")
        )
    elif step["type"] == "navigate":
        await page.goto(step["url"])
        await asyncio.sleep(1)
    elif step["type"] == "counterloop" and step.get("action") == "counterloop":
        count = step.get("criteria", {}).get("count", 1)
        logger.info(f"⟳ Starting loop '{step.get('source')}' for {count} iterations")
        for i in range(count):
            logger.info(f"→ Loop iteration {i + 1}/{count}")
            for sub_step in step.get("steps", []):
                await handle_step(sub_step, page)


async def replay_flow(json_str: str):
    state.is_replaying = True
    flow = json.loads(json_str)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, channel="chrome")  # Real Chrome
        context = await browser.new_context()
        page = await context.new_page()

        for step in flow:
            await handle_step(step, page)

        logger.info("✅ Replay complete.")
        await browser.close()
        state.is_replaying = False


# Example usage for wiring later:
# asyncio.run(replay_flow(Path("recordings/final_flow.json").read_text()))
