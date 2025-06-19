import asyncio
import json
import logging
import os
from pathlib import Path
from typing import List, Union
from playwright.async_api import async_playwright, Page
from common import state
from common.browserutil import launch_chrome

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
            text_hint = None
            if ":has-text(" in selector:
                try:
                    text_hint = selector.split(":has-text(")[1].split(")")[0].strip('"').strip("'")
                except:
                    pass

            # Try fallback with get_by_text
            if action == "click" and text_hint:
                try:
                    await page.get_by_text(text_hint, exact=True).click(timeout=3000)
                    logger.info(f"[Fallback] Used get_by_text: {text_hint}")
                    return
                except Exception as ge:
                    logger.debug(f"[Fallback] get_by_text failed: {ge}")

                try:
                    await page.get_by_role("button", name=text_hint).click(timeout=3000)
                    logger.info(f"[Fallback] Used get_by_role: {text_hint}")
                    return
                except Exception as ge2:
                    logger.debug(f"[Fallback] get_by_role failed: {ge2}")

                # Try common tags with text match
                for tag in ["a", "button", "div", "span"]:
                    try:
                        candidate = page.locator(f"{tag}:has-text('{text_hint}')")
                        if await candidate.count() == 1:
                            await candidate.first.click(timeout=3000)
                            logger.info(f"[Fallback] Used {tag}:has-text('{text_hint}')")
                            return
                    except Exception as se:
                        logger.debug(f"[Fallback] {tag} tag failed: {se}")

            # Try in frames
            for frame in page.frames:
                try:
                    await try_action(frame)
                    logger.debug(f"Success inside frame: {frame.url}")
                    return
                except:
                    continue

            # Last resort: force click
            if action == "click" and attempt == retries:
                try:
                    await page.click(selector, force=True, timeout=3000)
                    logger.info(f"[Force Click] Fallback succeeded: {selector}")
                    return
                except Exception as fe:
                    logger.error(f"[Force Click] Failed: {fe}")

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
        browser = await launch_chrome(p)  # use unified method
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = await context.new_page()

        for step in flow:
            await handle_step(step, page)

        logger.info("Replay complete.")
        await browser.close()
        state.is_replaying = False


# Example usage for wiring later:
# asyncio.run(replay_flow(Path("recordings/final_flow.json").read_text()))
