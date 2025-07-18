import asyncio
import os
import shutil
import socket
import subprocess
import time
import psutil
import logging
import json
from playwright.async_api import async_playwright

from common import state

logger = logging.getLogger(__name__)

DEFAULT_PORT = 9222
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "../ui/agent_config.json")

def load_agent_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Could not load config from {CONFIG_PATH}: {e}")
        return {}

def get_default_profile_dir():
    return os.path.expanduser(r"~\AppData\Local\Google\Chrome\User Data\Default")

def find_chrome_executable():
    chrome_path = shutil.which("chrome") or shutil.which("chrome.exe")
    if chrome_path and os.path.exists(chrome_path):
        return chrome_path

    fallback_paths = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    for path in fallback_paths:
        if os.path.exists(path):
            return path

    return None

def is_chrome_debug_running(port=DEFAULT_PORT):
    for proc in psutil.process_iter(attrs=["name", "cmdline"]):
        try:
            if "chrome.exe" in proc.info["name"].lower():
                cmdline = " ".join(proc.info["cmdline"]).lower()
                if f"--remote-debugging-port={port}" in cmdline:
                    return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False

def is_port_open(host="localhost", port=DEFAULT_PORT):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        try:
            sock.connect((host, port))
            return True
        except socket.error:
            return False

def wait_for_debug_port(port=DEFAULT_PORT, timeout=10):
    logger.info(f"Waiting for Chrome CDP port {port} to become available...")
    for _ in range(timeout * 2):
        if is_port_open("localhost", port):
            logger.info("Chrome is ready for CDP connection.")
            return
        time.sleep(0.5)
    raise RuntimeError(f"Chrome did not open debugging port {port} within timeout.")

import os
import subprocess
import logging
import json
import time
import socket
import shutil
import psutil

logger = logging.getLogger(__name__)
DEFAULT_PORT = 9222
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "../agent_config.json")

def load_agent_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Could not load config from {CONFIG_PATH}: {e}")
        return {}

def get_default_profile_dir():
    return os.path.expanduser(r"~\AppData\Local\Botflows\ChromeProfile")

def find_chrome_executable():
    chrome_path = shutil.which("chrome") or shutil.which("chrome.exe")
    if chrome_path and os.path.exists(chrome_path):
        return chrome_path

    fallback_paths = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    for path in fallback_paths:
        if os.path.exists(path):
            return path

    return None

def is_port_open(host="localhost", port=DEFAULT_PORT):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        try:
            sock.connect((host, port))
            return True
        except socket.error:
            return False

def wait_for_debug_port(port=DEFAULT_PORT, timeout=10):
    logger.info(f"Waiting for Chrome CDP port {port} to become available...")
    for _ in range(timeout * 2):
        if is_port_open("localhost", port):
            logger.info("Chrome is ready for CDP connection.")
            return
        time.sleep(0.5)
    raise RuntimeError(f"Chrome did not open debugging port {port} within timeout.")

def is_chrome_debug_running(port=DEFAULT_PORT):
    for proc in psutil.process_iter(attrs=["name", "cmdline"]):
        try:
            if "chrome.exe" in proc.info["name"].lower():
                cmdline = " ".join(proc.info["cmdline"]).lower()
                if f"--remote-debugging-port={port}" in cmdline:
                    return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False

# ✅ Final unified launch method
async def launch_chrome(playwright, port=DEFAULT_PORT, user_profile_dir=None, is_recording=False):
    config = load_agent_config()
    use_bundled = config.get("use_bundled_chrome", True)

    if use_bundled:
        logger.info("Launching bundled Chromium via Playwright.")
        state.current_browser = await playwright.chromium.launch(headless=False)
        return state.current_browser

    if user_profile_dir is None:
        user_profile_dir = get_default_profile_dir()

    os.makedirs(user_profile_dir, exist_ok=True)

    if not is_chrome_debug_running(port):
        chrome_path = config.get("chrome_path") or find_chrome_executable()
        if not chrome_path or not os.path.exists(chrome_path):
            raise FileNotFoundError("Chrome executable not found in config or standard locations.")
        if is_recording:
            state.chrome_process = subprocess.Popen([
                chrome_path,
                f"--remote-debugging-port={port}",
                f"--user-data-dir={user_profile_dir}",
                "--no-first-run",
                "--no-default-browser-check",
                "--new-window",
                "about:blank"
            ])
        else:
            subprocess.Popen([
            chrome_path,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={user_profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--new-window",
            "about:blank"
        ])


        wait_for_debug_port(port)
        logger.info(f"Launched Chrome with debugging port {port} and profile: {user_profile_dir}")
    else:
        logger.info(f"Reusing existing Chrome with --remote-debugging-port={port}")

    browser = await playwright.chromium.connect_over_cdp(f"http://localhost:{port}")
    return browser


async def launch_replay_window(playwright, initial_url="about:blank", port=DEFAULT_PORT):
    logger.info("[Replay] Launching browser for replay")
    browser = await launch_chrome(playwright, port=port)

    # Case 1: Using real Chrome via connect_over_cdp
    if hasattr(browser, "new_browser_cdp_session"):
        logger.info("[Replay] Detected CDP session")

        # Try to find an existing page
        all_pages = [p for ctx in browser.contexts for p in ctx.pages]
        if all_pages:
            logger.info("[Replay] Reusing existing page")
            page = all_pages[0]
            await page.goto(initial_url)
            return browser, page

        # No pages? Create new one via CDP
        logger.info("[Replay] No existing pages, creating new window via CDP")
        cdp_session = await browser.new_browser_cdp_session()
        await cdp_session.send("Target.createTarget", {
            "url": initial_url,
            "newWindow": True
        })

        # Wait for the new window
        for _ in range(10):
            await asyncio.sleep(0.5)
            new_pages = [p for ctx in browser.contexts for p in ctx.pages]
            diff = list(set(new_pages) - set(all_pages))
            if diff:
                logger.info("[Replay] New page successfully opened.")
                return browser, diff[0]

        raise RuntimeError("Failed to open a new window for replay")

    # Case 2: Bundled Chromium fallback
    logger.info("[Replay] Using bundled Chromium — opening new context")
    context = await browser.new_context()
    page = await context.new_page()
    await page.goto(initial_url)
    return browser, page

async def launch_preview_window(playwright, initial_url="about:blank", port=DEFAULT_PORT):
    logger.info("[Replay] Launching browser for preview")
    browser = await launch_chrome(playwright, port=port)

    # Case 1: Using real Chrome via connect_over_cdp — must create new window via CDP
    if hasattr(browser, "new_browser_cdp_session"):
        logger.info("[Replay] Detected CDP session — opening new window via Target.createTarget")

        # Get current pages to detect the new one later
        existing_pages = [p for ctx in browser.contexts for p in ctx.pages]

        # Open new window using CDP
        cdp_session = await browser.new_browser_cdp_session()
        await cdp_session.send("Target.createTarget", {
            "url": initial_url,
            "newWindow": True
        })

        # Wait for the new window to register as a Playwright Page
        for _ in range(10):
            await asyncio.sleep(0.5)
            new_pages = [p for ctx in browser.contexts for p in ctx.pages]
            diff = list(set(new_pages) - set(existing_pages))
            if diff:
                logger.info("[Replay] New page successfully opened.")
                return browser, diff[0]

        raise RuntimeError("Failed to open a new window for replay")
