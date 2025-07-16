import atexit
import logging
import os
import sys
import json
import asyncio
import subprocess
import tempfile
import jwt
import psutil
import pathlib

from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, HTTPException, Header, Query, WebSocket, Request, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from recorder.recorder import record
from recorder.player import replay_flow
from common import state
from common.logger import get_logger
from common.config import AUTH_TYPE
from common.state import extract_user_id
from common import state
from common.ws_client import connect_to_dashboard_ws

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
        if state.user_id not in state.connections:
            asyncio.create_task(connect_to_dashboard_ws())

        logger.info(f"Starting recording for: {req.url}")
        if state.current_browser:
            try:
                for ctx in state.current_browser.contexts:
                    await ctx.close()
                    logger.info("[Recorder] Closed browser context.")
            except Exception as e:
                logger.warning(f"[Recorder] Failed closing context: {e}")

            try:
                await state.current_browser.close()
                logger.info("[Recorder] Closed browser.")
            except Exception as e:
                logger.warning(f"[Recorder] Failed closing browser: {e}")

            state.current_browser = None
            state.current_page = None
            
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
        if state.user_id not in state.connections:
            asyncio.create_task(connect_to_dashboard_ws())

        json_str = (await request.body()).decode("utf-8")
        await replay_flow(json_str)
        return {"status": "replaying"}
    except Exception as e:
        logger.exception("Replay failed")
        return {"error": str(e)}

@app.post("/api/preview-replay")
async def preview_replay(req: Request, authorization: str = Header(None)):
    try:
        if not authorization:
            raise HTTPException(status_code=401, detail="Missing Authorization header")

        state.set_user_token(authorization)
        if state.user_id not in state.connections:
            asyncio.create_task(connect_to_dashboard_ws())

        json_str = await req.body()
        await replay_flow(json_str.decode("utf-8"), is_preview=True)
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "details": str(e)}

@app.post("/api/stop")
def stop_recording():
    try:
        Path("recordings/stop.flag").write_text("stop")
        state.is_recording = False
        state.current_url = None
        return {"status": "stopping"}
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

    print(jwt.__file__)
    
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
        asyncio.create_task(connect_to_dashboard_ws())
        state.log_to_status("Starting Botflows agent.")

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
        state.log_to_status("Botflows Agent exited.")
        os._exit(0)

    def on_settings_click(icon, item):
        state.log_to_status("Opening settings...")
        if os.path.exists(SETTINGS_LOCK_FILE):
            print("Settings already open.")
            return

        with open(SETTINGS_LOCK_FILE, "w") as f:
            f.write("1")

        base_dir = os.path.dirname(os.path.abspath(__file__))
        settings_exe = os.path.join(base_dir, "ui", "config_ui.exe")
        proc = None

        if os.path.exists(settings_exe):
            try:
                proc = subprocess.Popen([settings_exe])
            except Exception as e:
                print(f"Error launching settings: {e}")
        else:
            print(f"Settings executable not found at {settings_exe}")

        def clear_lock():
            if os.path.exists(SETTINGS_LOCK_FILE):
                os.remove(SETTINGS_LOCK_FILE)

        if proc:
            threading.Thread(target=lambda: (proc.wait(), clear_lock()), daemon=True).start()
        else:
            clear_lock()


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
            item("Settings", on_settings_click),
            item("Quit", quit_app),
        ))
        logger.info("Tray icon ready.")
        icon.run()

    threading.Thread(target=start_api, daemon=True).start()
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