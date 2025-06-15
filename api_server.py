from pathlib import Path
from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import subprocess
import os
import signal
from fastapi.responses import JSONResponse
import json
import glob

app = FastAPI()

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Use ["http://localhost:3000"] in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state to track the running process
recorder_proc = None
current_url = None

class RecordRequest(BaseModel):
    url: str

@app.post("/api/record")
def start_recording(req: RecordRequest):
    global recorder_proc, current_url

    if recorder_proc and recorder_proc.poll() is None:
        return {"status": "already_running", "url": current_url}

    recorder_script = os.path.abspath("recorder.py")
    recorder_proc = subprocess.Popen(["python", recorder_script, req.url])
    current_url = req.url
    return {"status": "started", "url": current_url}

@app.post("/api/stop")
def stop_recording():
    stop_file = Path("recordings/stop.flag")
    stop_file.write_text("stop")
    return {"status": "stopping"}

@app.get("/api/status")
def get_status():
    running = recorder_proc and recorder_proc.poll() is None
    return {"running": running, "url": current_url if running else None}

@app.get("/api/logs/actions")
def get_recorded_actions():
    try:
        with open("./recordings/recorded_actions.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        return JSONResponse(content=data)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    
@app.get("/api/logs/selectors")
def get_selector_logs():
    try:
        with open("dataset/selector_logs.jsonl", "r", encoding="utf-8") as f:
            lines = [json.loads(line.strip()) for line in f if line.strip()]
        return JSONResponse(content=lines)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/api/live_events")
def get_live_events():
    try:
        with open("dataset/live_events.jsonl", "r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

import glob

@app.get("/api/recorded-urls")
def get_recorded_urls():
    try:
        with open("recordings/recorded_actions.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        return list(data.keys())
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/replay")
def replay_by_url(payload: dict):
    url = payload.get("url")
    print(f"Replaying actions for URL: {url}")
    if not url:
        return {"error": "URL required"}

    # Save only that session temporarily for playback
    try:
        with open("recordings/recorded_actions.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            print("Loaded recorded actions from file.")

        if url not in data:
            return {"error": "URL not found"}

        temp_path = "recordings/_replay_temp.json"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump({url: data[url]}, f, indent=2)
            print(f"Temporary replay file created at {temp_path}")

        subprocess.Popen(["python", "player.py", temp_path])
        return {"status": "replaying", "url": url}
    except Exception as e:
        return {"error": str(e)}
