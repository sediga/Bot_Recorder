# common/state.py
import json
from fastapi import logger
import jwt
from collections import defaultdict, deque
from common.logger import get_logger
from common.ws_client import safe_send

logger = get_logger(__name__)

user_states = defaultdict(lambda: {
    "is_running": False,
    "is_recording": False,
    "is_replaying": False,
    "current_url": None,
    "logs": deque(maxlen=50)
})
chrome_process = None  # Holds the subprocess.Popen object for Chrome   
is_recording = False
is_running = False
is_replaying = False
current_url = None
active_page = None
current_browser = None
active_dom_snapshot = None
# Already has: is_running, is_recording, is_replaying, etc.
pick_mode = False
connections = {}
worker_task = None  # Holds the worker task during recording
current_loop = {
    "loopId": None,
    "loopName": None,
    "sourceStep": None  # the full gridExtract step
}

# common/state.py

user_token: str = None  # Holds the current user's JWT
user_id: str = None     # Optional: Parsed from token for folder scoping

def get_user_state(user_id):
    return user_states[user_id]

async def log_to_status(message: str, level="info"):
    print(f"[{user_id}] {message}")
    user_state = get_user_state(user_id)
    user_state["logs"].append(message)

    ws = connections.get(user_id)
    if ws:
        try:
            structured_message = {
                "type": "log",
                "userId": user_id,
                "sessionId": user_id,  # or real session ID if available
                "payload": {
                    "level": level,
                    "message": message
                }
            }
            await safe_send(user_id, "event", structured_message)
        except Exception as e:
            print(f"[Log] Failed to send to dashboard WS: {e}")

def set_user_token(token: str):
    global user_token, user_id
    user_token = token
    user_id = extract_user_id(token)

def clear_user_token():
    global user_token, user_id
    user_token = None
    user_id = None

def extract_user_id(token):
    try:
        payload = jwt.decode(token.replace("Bearer ", ""), options={"verify_signature": False})
        rawId = payload.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/nameidentifier")

        if isinstance(rawId, list):
            rawId = rawId[0]

        userId = int(rawId) if rawId else 0
        return userId

    except Exception as ex:
        logger.warning(f"Failed to extract user ID from token: {ex}")
        return None
