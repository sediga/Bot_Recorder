from common import state
from common.logger import get_logger

logger = get_logger(__name__)

from playwright.async_api import TimeoutError

async def simulate_action_in_sandbox(selector: str, action="click", value=None, key=None) -> bool:
    try:
        # sandbox_page = state.sandbox_page
        # await sandbox_page.set_content(dom_html, wait_until="domcontentloaded")
        
        locator = state.sandbox_page.locator(selector)
        await locator.scroll_into_view_if_needed()
        await locator.wait_for(state="attached", timeout=2000)
        await locator.wait_for(state="visible", timeout=2000)

        if action.lower() == "click":
            await locator.click(trial=True)
        elif action.lower() == "dblclick":
            await locator.dblclick(trial=True)
        elif action.lower() == "type":
            await locator.fill(value or "Test")
        elif action.lower() == "press":
            await state.sandbox_page.keyboard.press(key)
        elif action.lower() == "select":
            await locator.select_option(value)
        elif action.lower() in ["mousedown", "focus", "blur"]:
            await locator.dispatch_event(action)
        else:
            return False

        return True

    except TimeoutError:
        logger.warning(f"[Sandbox] Timeout waiting for selector: {selector}")
        return False
    except Exception as e:
        logger.warning(f"[Sandbox] Simulated action failed on {selector}: {e}")
        return False

async def load_page_in_sandbox(dom_html: str) -> bool:
    await state.sandbox_page.set_content(dom_html, wait_until="domcontentloaded")

