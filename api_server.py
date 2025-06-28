from pathlib import Path
import subprocess
import tempfile
from fastapi import FastAPI, WebSocket, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from recorder.recorder import record
from recorder.player import replay_flow
from common import state
from common import selectorHelper
from typing import Optional
import logging
import os
import sys
import json
import asyncio

# --- Logging ---
log_path = Path(__file__).parent / "botflows_agent.log"
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_path, mode='a', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("botflows-agent")

# --- FastAPI App ---
app = FastAPI()
state.connections = []

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class RecordRequest(BaseModel):
    url: str

@app.websocket("/ws/actions")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    state.connections.append(websocket)
    logger.info(f"[WS] Connected clients: {len(state.connections)}")
    try:
        while True:
            await asyncio.sleep(10)
    except Exception as e:
        logger.warning(f"[WS] Disconnected: {e}")
    finally:
        state.connections.remove(websocket)

@app.post("/api/record")
async def start_recording(req: RecordRequest):
    state.is_recording = True
    state.current_url = req.url
    try:
        logger.info(f"Starting recording for: {req.url}")
        asyncio.create_task(record(req.url))
        return {"status": "started", "url": req.url}
    except Exception as e:
        state.is_recording = False
        state.current_url = None
        logger.exception("Recorder launch failed")
        return {"error": str(e)}

@app.post("/api/replay")
async def replay_by_json(request: Request):
    try:
        json_str = (await request.body()).decode("utf-8")
        asyncio.create_task(replay_flow(json_str))
        return {"status": "replaying"}
    except Exception as e:
        logger.exception("Replay failed")
        return {"error": str(e)}

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

@app.get("/api/status")
def get_status():
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
        picker_path = Path(__file__).parent / "javascript" / "gridPicker.js"

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
async def start_loop_recording(req: StartLoopRequest):
    try:
        # state.active_loop_index = req.loopIndex
        state.active_loop_name = req.loopName
        await state.current_page.evaluate(f'window.__botflows_loopName__ = {json.dumps(req.loopName)}')
        loop_script_path = Path(__file__).parent / "javascript" / "loopBanner.js"
        await state.current_page.add_init_script(path=loop_script_path)
        await state.current_page.evaluate("() => {}")
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "details": str(e)}

@app.post("/api/end-loop-recording")
async def end_loop_recording():
    try:
        await state.current_page.evaluate("window.__botflows_loopName__ = null")
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "details": str(e)}

# === Tray Launcher ===
if __name__ == "__main__":
    import threading
    import pystray
    from pystray import MenuItem as item
    from PIL import Image
    import winreg
    from uvicorn import Config, Server

    lock_file = os.path.join(tempfile.gettempdir(), "botflows_settings.lock")
    if os.path.exists(lock_file):
        os.remove(lock_file)

    def start_api():
        config = Config(app=app, host="localhost", port=8000, log_level="info")
        server = Server(config=config)
        logger.info("API server started at http://localhost:8000")
        state.is_running = True
        server.run()

    def quit_app(icon, item):
        logger.info("Botflows Agent exiting...")
        try:
            import psutil
            for proc in psutil.process_iter(attrs=["pid", "name", "cmdline"]):
                if any("config_ui.py" in part for part in proc.info.get("cmdline", [])):
                    proc.terminate()
        except Exception as e:
            logger.warning(f"Settings cleanup failed: {e}")

        if os.path.exists(lock_file):
            os.remove(lock_file)

        icon.stop()
        state.is_running = False
        os._exit(0)

    def on_settings_click(icon, item):
        if os.path.exists(lock_file):
            return
        with open(lock_file, "w") as f:
            f.write("1")
        proc = subprocess.Popen([sys.executable, "ui/config_ui.py"])
        threading.Thread(target=lambda: (proc.wait(), os.remove(lock_file)), daemon=True).start()

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
