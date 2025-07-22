import os
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"  # ✅ must come before any Playwright imports

import httpx
import requests
import atexit
import logging
import sys
import json
import asyncio
import subprocess
import tempfile
import jwt
import psutil
import pathlib
import tkinter as tk
import time
from tkinter import ttk, filedialog, messagebox
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path
from fastapi import FastAPI, HTTPException, Header, Query, WebSocket, Request, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from common.browserutil import close_chrome
from recorder.recorder import record
from recorder.player import replay_flow
from common import state
from common.logger import get_logger
from common.config import AUTH_TYPE
from common.state import extract_user_id
from common import state
from common.ws_client import connect_to_dashboard_ws
from ui.config_ui import open_config_ui
from common.config import get_agent_config, get_api_url, get_headers

config = get_agent_config()
use_bundled = config.get("use_bundled_chrome", True)
chrome_path_from_config = config.get("chrome_path")
UPDATE_URL = config.get("UPDATE_MANIFEST_URL")
AGENT_VERSION = config.get("AGENT_VERSION")

logger = logging.getLogger(__name__)

logger = get_logger(__name__)
SETTINGS_LOCK_FILE = os.path.join(tempfile.gettempdir(), "botflows_settings.lock")

# --- FastAPI App ---
app = FastAPI()
state.connections = {}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class RecordRequest(BaseModel):
    url: str

@app.post("/api/record")
async def start_recording(req: RecordRequest, authorization: str = Header(None)):
    state.is_recording = True
    state.current_url = req.url
    try:
        if not authorization:
            raise HTTPException(status_code=401, detail="Missing Authorization header")

        state.set_user_token(authorization)
        logger.info(f"[Agent] Recording started for user: {state.user_id}")
        # Inside start_recording or replay_flow
        # if state.user_id not in state.connections:
        await asyncio.gather(
            connect_to_dashboard_ws("event"),
            connect_to_dashboard_ws("log")
        )

        logger.info(f"Starting recording for: {req.url}")
        await close_chrome(True)            
        await record(req.url)
        return {"status": "started", "url": req.url}
    except Exception as e:
        state.is_recording = False
        state.current_url = None
        logger.exception("Recorder launch failed")
        return {"error": str(e)}

@app.post("/api/replay")
async def replay_by_json(request: Request, authorization: str = Header(None)):
    try:
        if not authorization:
            raise HTTPException(status_code=401, detail="Missing Authorization header")

        state.set_user_token(authorization)
        await asyncio.gather(
            connect_to_dashboard_ws("event"),
            connect_to_dashboard_ws("log")
        )

        await state.log_to_status(f"🎬 Starting replay...")

        json_str = (await request.body()).decode("utf-8")
        await replay_flow(json_str)
        return {"status": "replaying"}
    except Exception as e:
        logger.exception("Replay failed")
        return {"error": str(e)}

@app.post("/api/preview-replay")
async def preview_replay(req: Request, authorization: str = Header(None)):
    try:
        if not state.is_recording:
            await state.log_to_status(f"🧪 Preview replay can only be started during recording.")
            raise HTTPException(status_code=400, detail="Not recording")
        await state.log_to_status(f"⏯️ Starting preview replay, Recording will be paused till replay is finished... Replay will not stop even browser is closed. so, wait for the replay to finish...")
        if not authorization:
            raise HTTPException(status_code=401, detail="Missing Authorization header")

        state.set_user_token(authorization)
        # await asyncio.gather(
        #     connect_to_dashboard_ws("event"),
        #     connect_to_dashboard_ws("log")
        # )

        json_str = await req.body()
        await replay_flow(json_str.decode("utf-8"), is_preview=True)
        return {"status": "ok"}
    except Exception as e:
        if state.active_page:
            await state.active_page.evaluate("""() => {
                window.__botflows_replaying__ = false;
                const div = document.getElementById('botflows-replay-overlay');
                if (div) div.remove();
            }""")
        state.is_previewing = False
        return {"status": "error", "details": str(e)}

@app.post("/api/stop")
async def stop_recording():
    try:
        state.is_recording = False
        state.current_url = None

        # Close browser and context if running
        await close_chrome(True)
        state.current_browser = None
        state.active_page = None

        return {"status": "stopped"}
    except Exception as e:
        logger.exception("Stop failed")
        return {"error": str(e)}
    finally:
        logger.info(f"[Agent] Stopping session for user: {state.user_id}")
        state.clear_user_token()

from fastapi import Request, HTTPException

@app.get("/api/status")
def get_status(request: Request):
    return {
        "running": state.is_running,
        "recording": state.is_recording,
        "replaying": state.is_replaying,
        "stopped": not (state.is_running or state.is_recording or state.is_replaying),
        "url": state.current_url if state.is_recording else None
    }

@app.post("/api/target-pick-mode")
async def enable_target_pick_mode(request: Request):
    try:
        await state.log_to_status(f"🎯 Select the grid you want to record in the target webpage...")
        state.pick_mode = True
        data = await request.json()
        if data.get("mode") != "start":
            return {"status": "ignored"}

        page = state.active_page
        if not page:
            return {"error": "No active page"}

        try:
            await page.evaluate("() => true")
        except Exception:
            state.active_page = None
            return {"error": "Stale page"}

        selector_path = Path(__file__).parent / "javascript" / "selectorHelper.bundle.js"
        picker_path = Path(__file__).parent / "javascript" / "gridPicker.bundle.js"

        await page.evaluate("(code) => eval(code)", selector_path.read_text("utf-8"))
        await page.evaluate("(code) => eval(code)", picker_path.read_text("utf-8"))

        return {"status": "ok", "message": "Picker script injected"}
    except Exception as e:
        logger.exception("Pick mode injection failed")
        return {"error": str(e)}

@app.post("/api/target-pick-done")
async def disable_pick_mode():
    await state.log_to_status(f"📍 Target picked.")
    state.pick_mode = False
    try:
        if state.active_page:
            await state.active_page.evaluate("window.__pickModeActive = false")
            await state.active_page.evaluate("window.finishPicker?.()")
            recorder_path = Path(__file__).parent / "javascript" / "recorder.bundle.js"
            await state.active_page.evaluate("(code) => eval(code)", recorder_path.read_text("utf-8"))
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "details": str(e)}

class StartLoopRequest(BaseModel):
    loopIndex: int
    loopName: str

@app.post("/api/start-loop-recording")
async def start_loop_recording(request: Request):
    data = await request.json()
    await state.log_to_status(f"🔁 recording in a loop, please continue recording and click finish loop when done....")
    state.current_loop = {
        "active": True,
        "loopId": data.get("loopId"),
        "loopName": data.get("loopName"),
        "sourceStep": data.get("sourceStep"),  # entire extract step
    }
    await state.active_page.evaluate(
        """(loop) => { window.loopContext = loop; }""",
        state.current_loop
    )
    
    return { "status": "ok" }

@app.post("/api/end-loop-recording")
async def start_loop_recording(request: Request):
    await state.log_to_status(f"✅ loop recording finished, please continue recording the rest of the flow....")
    state.current_loop = {
        "active": False,
        "loopId": None,
        "loopName": None,
        "sourceStep": None
    }
    await state.active_page.evaluate("""() => {
        delete window.loopContext;
    }""")
    return { "status": "loop recording stopped" }

LOCK_PATH = os.path.join(tempfile.gettempdir(), "botflows_agent.lock")
def ensure_single_instance():
    if os.path.exists(LOCK_PATH):
        try:
            with open(LOCK_PATH, "r") as f:
                old_pid = int(f.read().strip())
            if psutil.pid_exists(old_pid):
                print(f"Agent is already running (PID {old_pid})")
                sys.exit(0)
        except Exception:
            pass  # If unreadable or invalid, we'll overwrite

    with open(LOCK_PATH, "w") as f:
        f.write(str(os.getpid()))

def kill_existing_chrome_debug_instances():
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if "chrome.exe" in proc.info['name'].lower() and any("--remote-debugging-port" in arg for arg in proc.info['cmdline']):
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        
def cleanup_lock():
    if os.path.exists(LOCK_PATH):
        try:
            os.remove(LOCK_PATH)
        except Exception as e:
            print(f"Failed to remove lock file: {e}")

# === Tray Launcher ===
if __name__ == "__main__" and "config_ui.py" not in sys.argv[0]:
    ensure_single_instance()
    import threading
    import pystray
    from pystray import MenuItem as item
    from PIL import Image
    import winreg
    from uvicorn import Config, Server
    import os
    import tempfile
    from win10toast import ToastNotifier
    
    APP_DIR = os.path.join(os.getenv("LOCALAPPDATA"), "BotflowsAgent")
    VERSION_FILE = os.path.join(APP_DIR, "version.txt")

    # Ensure folder exists
    os.makedirs(APP_DIR, exist_ok=True)

    # Save version.txt
    with open(VERSION_FILE, "w") as f:
        f.write(AGENT_VERSION)

    print(jwt.__file__)

    def is_newer(latest, current):
        def parse(v): return tuple(map(int, v.split(".")))
        return parse(latest) > parse(current)

    def check_for_updates():
        try:
            res = requests.get(get_api_url(UPDATE_URL), headers=get_headers(), timeout=5)
            if res.status_code != 200:
                print("[Updater] Failed to fetch version info.")
                return None

            data = {k.lower(): v for k, v in res.json().items()}
            latest = data.get("latest")
            if latest and is_newer(latest, AGENT_VERSION):
                print(f"[Updater] New version available: {latest}")
                return data  # send version info back
            else:
                print("[Updater] Agent is up-to-date.")
                return None
        except Exception as e:
            print("[Updater] Update check failed:", e)
            return None

    toaster = ToastNotifier()

    def show_notification(title, msg, duration=5):
        try:
            toaster.show_toast(title, msg, duration=duration, threaded=True)
        except Exception as e:
            print(f"[Notifier] Failed to show notification: {e}")

    def download_and_install(url):
        try:
            show_notification("Botflows Agent", "Downloading update...")
            print(f"[Updater] Downloading installer from {url}")
            response = requests.get(url, stream=True)
            if response.status_code == 200:
                temp_path = os.path.join(tempfile.gettempdir(), "BotflowsAgentInstaller.exe")
                with open(temp_path, "wb") as f:
                    for chunk in response.iter_content(1024 * 1024):
                        f.write(chunk)
                print(f"[Updater] Installer saved to {temp_path}")

                show_notification("Botflows Agent", "Installing update now...")

                subprocess.Popen([temp_path, "/S"])  # Silent install
                time.sleep(2)
                show_notification("Botflows Agent", "Update installed. Restarting...")
                # os._exit(0)
            else:
                show_notification("Botflows Agent", "Failed to download update.")
                print(f"[Updater] Failed to download: status {response.status_code}")
        except Exception as e:
            show_notification("Botflows Agent", f"Update error: {str(e)}")
            print("[Updater] Exception during install:", e)

    class SuppressStatusLogs(logging.Filter):
        def filter(self, record):
            return "/api/status" not in record.getMessage()

    logging.getLogger("uvicorn.access").addFilter(SuppressStatusLogs())

    lock_file = os.path.join(tempfile.gettempdir(), "botflows_settings.lock")
    if os.path.exists(lock_file):
        os.remove(lock_file)

    def start_api():
        config = Config(app=app, host="localhost", port=8000, log_level="info")
        server = Server(config=config)
        logger.info("API server started at http://localhost:8000")
        state.is_running = True
        server.run()
        # asyncio.create_task(connect_to_dashboard_ws())

    def quit_app(icon, item):
        logger.info("Botflows Agent exiting...")
        try:
             for proc in psutil.process_iter(attrs=["pid", "name", "cmdline"]):
                if any("config_ui.py" in part for part in proc.info.get("cmdline", [])):
                    proc.terminate()
        except Exception as e:
            logger.warning(f"Settings cleanup failed: {e}")

        if os.path.exists(lock_file):
            os.remove(lock_file)

        icon.stop()
        state.is_running = False
        cleanup_lock()
        os._exit(0)

    def on_settings_click(icon, item):
        open_config_ui()

    def add_to_startup():
        exe_path = os.path.abspath(sys.argv[0])
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE) as reg_key:
                winreg.SetValueEx(reg_key, "BotflowsAgent", 0, winreg.REG_SZ, exe_path)
        except Exception:
            logger.exception("Add to startup failed")

    def remove_from_startup():
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_ALL_ACCESS) as reg_key:
                winreg.DeleteValue(reg_key, "BotflowsAgent")
        except FileNotFoundError:
            logger.warning("BotflowsAgent not in startup.")
        except Exception:
            logger.exception("Remove from startup failed")

    def tray_icon():
        icon_image = Image.new("RGB", (64, 64), color=(100, 150, 255))
        icon = pystray.Icon("BotflowsAgent", icon_image, "Botflows Agent", menu=(
            item("Start with Windows", lambda icon, _: add_to_startup()),
            item("Remove from Startup", lambda icon, _: remove_from_startup()),
            item("Check for update", lambda icon, _: threading.Thread(target=run_update_check).start()),
            item("Settings", on_settings_click),
            item("Quit", quit_app),
        ))
        logger.info("Tray icon ready.")
        icon.run()

    threading.Thread(target=start_api, daemon=True).start()

    def run_update_check():
        update_info = check_for_updates()
        if update_info:
            download_and_install(update_info["downloadurl"])

    threading.Thread(target=run_update_check, daemon=True).start()

    tray_icon()

    def kill_config_ui_on_exit():
        for proc in psutil.process_iter(["name", "exe", "cmdline"]):
            try:
                name = proc.info["name"] or ""
                cmdline = " ".join(proc.info["cmdline"] or [])

                if "config_ui.exe" in name.lower() or "config_ui.exe" in cmdline.lower():
                    print("Killing leftover config_ui.exe...")
                    proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    atexit.register(kill_config_ui_on_exit)