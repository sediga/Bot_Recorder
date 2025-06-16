from pathlib import Path
from fastapi import FastAPI, WebSocket, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from recorder.main import record
from recorder.player import start_replay
from common import state
import logging
import os
import sys
import json
import asyncio
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
connections = []

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



class RecordRequest(BaseModel):
    url: str

import asyncio

@app.websocket("/ws/actions")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connections.append(websocket)
    print(f"[WEBSOCKET CONNECTED] Total connections: {len(connections)}")
    try:
        while True:
            await asyncio.sleep(10)  # Keeps connection alive
    except Exception as e:
        print("❌ WebSocket disconnected:", e)
    finally:
        if websocket in connections:
            connections.remove(websocket)
            print(f"[WEBSOCKET REMOVED] Active: {len(connections)}")

@app.post("/api/stream_action")
async def stream_action(request: Request):
    action = await request.json()
    print("[RECEIVED ACTION]", action)

    disconnected = []
    for ws in connections:
        try:
            await ws.send_text(json.dumps(action))
            print("[BROADCASTED ACTION]", action)
        except Exception as e:
            print("❌ Failed to send:", e)
            disconnected.append(ws)

    for ws in disconnected:
        connections.remove(ws)

    return {"status": "ok"}

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

@app.post("/api/replay")
async def replay_by_url(payload: dict):
    url = payload.get("url")
    logger.info(f"Replaying actions for URL: {url}")
    if not url:
        return {"error": "URL required"}

    try:
        with open("recordings/recorded_actions.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            logger.debug("Loaded recorded actions from file.")

        if url not in data:
            logger.warning(f"No recorded actions for URL: {url}")
            return {"error": "URL not found"}

        temp_path = "recordings/_replay_temp.json"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump({url: data[url]}, f, indent=2)
            logger.info(f"Temporary replay file created at {temp_path}")

        asyncio.create_task(start_replay(temp_path))
        return {"status": "replaying", "url": url}
    except Exception as e:
        logger.exception("Failed during replay")
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
        "running": state.is_recording,
        "replaying": state.is_replaying,
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

# --- Tray App ---
if __name__ == "__main__":
    import threading
    import pystray
    from pystray import MenuItem as item
    from PIL import Image
    import winreg
    from uvicorn import Config, Server

    icon_instance = None

    def start_api():
        config = Config(app=app, host="localhost", port=8000, log_level="info")
        server = Server(config=config)
        logger.info("Launching API server on http://localhost:8000")
        server.run()
        
    def quit_app(icon, item):
        logger.info("Quitting Botflows Agent...")
        icon.stop()
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

    def tray_icon():
        icon_image = Image.new("RGB", (64, 64), color=(100, 150, 255))
        icon = pystray.Icon("BotflowsAgent", icon_image, "Botflows Agent", menu=(
            item("Start with Windows", lambda icon, _: add_to_startup()),
            item("Remove from Startup", lambda icon, _: remove_from_startup()),
            item("Quit", quit_app),
        ))
        icon_instance = icon
        logger.info("Tray icon initialized.")
        icon.run()

    threading.Thread(target=start_api, daemon=True).start()
    tray_icon()
