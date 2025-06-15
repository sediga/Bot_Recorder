from pathlib import Path
from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from recorder.main import record
from recorder.player import start_replay
import logging
import os
import sys
import json
import shutil

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

recorder_proc = None
current_url = None

class RecordRequest(BaseModel):
    url: str

@app.post("/api/record")
async def start_recording(req: RecordRequest):
    global recorder_proc, current_url
    recorder_script_path = os.path.join(os.path.dirname(__file__), "recorder", "main.py")

    if not os.path.exists(recorder_script_path):
        logger.error(f"main.py not found at {recorder_script_path}")
        return {"error": f"main.py not found at {recorder_script_path}"}

    try:
        logger.info(f"Starting recording for: {req.url}")
        await record(req.url)
        current_url = req.url
        return {"status": "started", "url": current_url}
    except Exception as e:
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

        await start_replay(temp_path)
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
        return {"status": "stopping"}
    except Exception as e:
        logger.exception("Error stopping recording")
        return {"error": str(e)}

@app.get("/api/status")
def get_status():
    running = recorder_proc and recorder_proc.poll() is None
    logger.debug(f"Status check: running={running}")
    return {"running": running, "url": current_url if running else None}

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
    import uvicorn
    import pystray
    from pystray import MenuItem as item
    from PIL import Image
    import winreg

    icon_instance = None

    def start_api():
        try:
            logger.info("Launching API server on http://127.0.0.1:8000")
            uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
        except Exception as e:
            logger.exception("API server failed to start")

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
        global icon_instance
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
