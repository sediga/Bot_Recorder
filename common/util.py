from fastapi import logger
from common import state
from common.config import AUTH_TYPE, API_KEY

def get_auth_headers():
    if AUTH_TYPE == "jwt":
        if not state.user_token:
            raise Exception("JWT token not set in agent state.")
        return {
            "Authorization": state.user_token,
            "Content-Type": "application/json"
        }
    elif AUTH_TYPE == "api_key":
        if not API_KEY:
            raise Exception("API Key not configured.")
        return {
            "x-api-key": API_KEY,
            "Content-Type": "application/json"
        }
    else:
        raise Exception(f"Unknown auth type: {AUTH_TYPE}")

async def send_to_user(user_id: str, message: str):
    for uid, ws in state.connections:
        if uid == user_id:
            try:
                await ws.send_text(message)
            except Exception as e:
                logger.warning(f"[WS] Failed to send to {user_id}: {e}")
