import asyncio
import json
import logging
from pathlib import Path
from playwright.async_api import async_playwright, Page
from common import state
from common.browserutil import launch_chrome

logger = logging.getLogger("botflows-player")
logging.basicConfig(level=logging.INFO)


async def _perform_action(page: Page, action: str, selector=None, value=None, key=None, retries=3):
    await asyncio.sleep(1)

    async def try_action(target_page: Page, sel):
        if action == "click":
            await target_page.wait_for_selector(sel, state="visible", timeout=5000)
            return await target_page.click(sel, timeout=5000)
        elif action == "type":
            await target_page.wait_for_selector(sel, state="attached", timeout=5000)
            await target_page.focus(sel)
            return await target_page.fill(sel, value or "")
        elif action == "press":
            return await target_page.keyboard.press(key)
        elif action == "select":
            await target_page.wait_for_selector(sel, state="attached", timeout=5000)
            return await target_page.select_option(sel, value)
        elif action in ["mousedown", "focus", "blur"]:
            await target_page.wait_for_selector(sel, state="attached", timeout=5000)
            return await target_page.dispatch_event(sel, action)

    for attempt in range(1, retries + 1):
        try:
            await try_action(page, selector)
            logger.info(f"✅ Action '{action}' succeeded on attempt {attempt}: {selector}")
            return
        except Exception as e:
            logger.warning(f"⚠️ Attempt {attempt} failed: {action} / {selector} => {e}")

            text_hint = None
            if ":has-text(" in selector:
                try:
                    text_hint = selector.split(":has-text(")[1].split(")")[0].strip('"').strip("'")
                except:
                    pass

            if action == "click" and text_hint:
                for fallback in [
                    lambda p: p.get_by_text(text_hint, exact=True),
                    lambda p: p.get_by_role("button", name=text_hint),
                    lambda p: p.locator(f"a:has-text('{text_hint}')"),
                    lambda p: p.locator(f"div:has-text('{text_hint}')"),
                    lambda p: p.locator(f"span:has-text('{text_hint}')"),
                ]:
                    try:
                        candidate = fallback(page)
                        await candidate.first.click(timeout=3000)
                        logger.info(f"[Fallback] Click worked using text match: {text_hint}")
                        return
                    except Exception:
                        continue

            for frame in page.frames:
                if frame == page.main_frame:
                    continue
                try:
                    await try_action(frame, selector)
                    logger.info(f"[Frame] Success inside: {frame.url}")
                    return
                except:
                    continue

            if action == "click" and attempt == retries:
                try:
                    await page.click(selector, force=True, timeout=3000)
                    logger.info(f"[Force Click] Succeeded: {selector}")
                    return
                except Exception as fe:
                    logger.error(f"[Force Click] Failed: {fe}")

            await asyncio.sleep(1)


async def handle_step(step: dict, page: Page):
    step_type = step.get("type")
    selector = step.get("improvedSelector") or step.get("selector")

    if step_type == "uiAction":
        await _perform_action(
            page,
            action=step.get("action"),
            selector=selector,
            value=step.get("value"),
            key=step.get("key")
        )
    elif step_type == "navigate":
        await page.goto(step["url"])
        await asyncio.sleep(1)
    elif step_type == "counterloop" and step.get("action") == "counterloop":
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
        browser = await launch_chrome(p)
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = await context.new_page()

        for step in flow:
            await handle_step(step, page)

        logger.info("🎉 Replay complete.")
        await browser.close()
        state.is_replaying = False


# Example usage:
# asyncio.run(replay_flow(Path("recordings/final_flow.json").read_text()))
