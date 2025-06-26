from pathlib import Path
import subprocess
import tempfile
from fastapi import FastAPI, WebSocket, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from recorder.recorder import record
from recorder.player import replay_flow
from common import state
from typing import Optional
from common import state
from common import selectorHelper

import logging
import os
import sys
import json
import asyncio
import httpx
# --- Global Variables ---

# --- Logging Setup ---
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

# --- FastAPI Setup ---
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
    print(f"[WEBSOCKET CONNECTED] Total connections: {len(state.connections)}")
    try:
        while True:
            await asyncio.sleep(10)  # Keeps connection alive
    except Exception as e:
        print("WebSocket disconnected:", e)
    finally:
        if websocket in state.connections:
            state.connections.remove(websocket)
            print(f"[WEBSOCKET REMOVED] Active: {len(state.connections)}")

# @app.post("/api/stream_action")
# async def stream_action(request: Request):
#     action = await request.json()
    
#     try:
#         if state.pick_mode and state.active_dom_snapshot:
#             meta = action.get("metadata", {})
#             target_text = meta.get("innerText", "")
#             target_tag = meta.get("tagName", "").lower()
#             target_classes = meta.get("classList", [])

#             # Enrich with replay-safe selector and inferred type
#             action = await selectorHelper.validate_and_enrich_selector(action)
#     except Exception as e:
#         logger.warning(f"Could not enrich action: {e}")

#     disconnected = []
#     for ws in state.connections:
#         try:
#             await ws.send_text(json.dumps(action))
#             print("[BROADCASTED ACTION]", action)
#         except Exception as e:
#             print("Failed to send:", e)
#             disconnected.append(ws)

#     for ws in disconnected:
#         state.connections.remove(ws)

#     return {"status": "ok"}

@app.post("/api/record")
async def start_recording(req: RecordRequest):
    state.is_recording = True
    state.current_url = req.url
    try:
        logger.info(f"Starting recording for: {state.current_url}")
        asyncio.create_task(record(state.current_url))
        return {"status": "started", "url": state.current_url}
    except Exception as e:
        state.is_recording = False
        state.current_url = None
        logger.exception("Failed to launch recorder")
        return {"error": str(e)}

from fastapi import Request

@app.post("/api/replay")
async def replay_by_json(request: Request):
    try:
        json_str = await request.body()
        json_str = json_str.decode("utf-8")

        asyncio.create_task(replay_flow(json_str))
        return {"status": "replaying"}
    except Exception as e:
        logger.exception("Failed to start replay from JSON string")
        return {"error": str(e)}

@app.post("/api/stop")
def stop_recording():
    try:
        stop_file = Path("recordings/stop.flag")
        stop_file.write_text("stop")
        logger.info("Stop flag created.")
        state.is_recording = False
        state.current_url = None
        return {"status": "stopping"}
    except Exception as e:
        logger.exception("Error stopping recording")
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

@app.get("/api/logs/actions")
def get_recorded_actions():
    try:
        with open("./recordings/recorded_actions.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        return JSONResponse(content=data)
    except Exception as e:
        logger.exception("Failed to load recorded actions")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/api/logs/selectors")
def get_selector_logs():
    try:
        with open("dataset/selector_logs.jsonl", "r", encoding="utf-8") as f:
            lines = [json.loads(line.strip()) for line in f if line.strip()]
        return JSONResponse(content=lines)
    except Exception as e:
        logger.exception("Failed to load selector logs")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/api/live_events")
def get_live_events():
    try:
        with open("dataset/live_events.jsonl", "r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    except Exception as e:
        logger.exception("Failed to load live events")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/api/recorded-urls")
def get_recorded_urls():
    try:
        with open("recordings/recorded_actions.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        return list(data.keys())
    except Exception as e:
        logger.exception("Failed to load recorded URLs")
        return JSONResponse(status_code=500, content={"error": str(e)})

from pathlib import Path

@app.post("/api/target-pick-mode")
async def enable_target_pick_mode(request: Request):
    try:
        state.pick_mode = True
        data = await request.json()
        mode = data.get("mode")

        if mode != "start":
            return {"status": "ignored", "message": "Unsupported mode"}

        page = getattr(state, "active_page", None)
        if not page:
            return {"error": "No active page/browser"}

        # Test if page is still open by evaluating a harmless noop
        try:
            await page.evaluate("() => true")
        except Exception:
            logger.warning("Stale page detected. Resetting active_page.")
            state.active_page = None
            return {"error": "Page is no longer available"}

        logger.info("Injecting selector helper and picker script...")

        # Inject selector helper first (if you use it)
        selector_helper_path = Path(__file__).parent / "javascript" / "selectorHelper.bundle.js"
        js_selector_helper = selector_helper_path.read_text(encoding="utf-8")
        await page.evaluate("(code) => eval(code)", js_selector_helper)

        # Inject picker script from external file
        picker_path = Path(__file__).parent / "javascript" / "gridPicker.js"
        picker_script = picker_path.read_text(encoding="utf-8")
        await page.evaluate("(script => eval(script))", picker_script)

        return {"status": "ok", "message": "Picker script injected"}

    except Exception as e:
        logger.exception("Failed to enable picker mode")
        return {"error": str(e)}

@app.post("/api/target-pick-done")
async def disable_pick_mode():
    state.pick_mode = False
    if state.active_page:
        await state.active_page.evaluate("window.__pickModeActive = false")
        await state.active_page.evaluate("window.finishPicker?.()")

        recorder_path = Path(__file__).parent / "javascript" / "recorder.bundle.js"
        js_code = recorder_path.read_text(encoding="utf-8")
        await state.active_page.evaluate("(code) => eval(code)", js_code)
        
    return { "status": "ok" }

# --- Tray App ---
if __name__ == "__main__":
    import threading
    import pystray
    from pystray import MenuItem as item
    from PIL import Image
    import winreg
    from uvicorn import Config, Server

    icon_instance = None

    lock_file = os.path.join(tempfile.gettempdir(), "botflows_settings.lock")
    if os.path.exists(lock_file):
        os.remove(lock_file)

    def start_api():
        config = Config(app=app, host="localhost", port=8000, log_level="info")
        server = Server(config=config)
        logger.info("Launching API server on http://localhost:8000")
        state.is_running = True
        server.run()
        
    def quit_app(icon, item):
        logger.info("Quitting Botflows Agent...")

        # Try to close settings window if open
        try:
            import psutil
            for proc in psutil.process_iter(attrs=["pid", "name", "cmdline"]):
                cmdline = proc.info.get("cmdline") or []
                if any("config_ui.py" in part for part in cmdline):
                    logger.info(f"Terminating config_ui.py process (PID: {proc.pid})")
                    proc.terminate()
        except Exception as e:
            logger.warning(f"Could not close settings window: {e}")

        # Always clean up lock file
        if os.path.exists(lock_file):
            os.remove(lock_file)

        icon.stop()
        state.is_running = False
        os._exit(0)

    def add_to_startup():
        exe_path = os.path.abspath(sys.argv[0])
        try:
            key = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as reg_key:
                winreg.SetValueEx(reg_key, "BotflowsAgent", 0, winreg.REG_SZ, exe_path)
            logger.info("Added to startup")
        except Exception:
            logger.exception("Failed to add to startup")

    def remove_from_startup():
        try:
            key = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_ALL_ACCESS) as reg_key:
                winreg.DeleteValue(reg_key, "BotflowsAgent")
            logger.info("Removed from startup")
        except FileNotFoundError:
            logger.warning("BotflowsAgent was not in startup.")
        except Exception:
            logger.exception("Failed to remove from startup")
            
    def on_settings_click(icon, item):
        if os.path.exists(lock_file):
            print("Settings already open.")
            return

        # Create lock file
        with open(lock_file, "w") as f:
            f.write("1")

        # Launch subprocess
        proc = subprocess.Popen([sys.executable, "ui/config_ui.py"])

        # Remove lock when done
        def clear_lock():
            if os.path.exists(lock_file):
                os.remove(lock_file)

        # Optional cleanup thread (for safety if user closes via X)
        import threading
        threading.Thread(target=lambda: (proc.wait(), clear_lock())).start()


    def tray_icon():
        icon_image = Image.new("RGB", (64, 64), color=(100, 150, 255))
        icon = pystray.Icon("BotflowsAgent", icon_image, "Botflows Agent", menu=(
            item("Start with Windows", lambda icon, _: add_to_startup()),
            item("Remove from Startup", lambda icon, _: remove_from_startup()),
            item('Settings', on_settings_click),
            item("Quit", quit_app),
        ))
        icon_instance = icon
        logger.info("Tray icon initialized.")
        icon.run()

    threading.Thread(target=start_api, daemon=True).start()
    tray_icon()
