import asyncio
from websockets.client import WebSocketClientProtocol
import logging
import json
import base64
from common import config, state
from asyncio import Lock

send_locks = {}

def get_lock(user_id, channel):
    key = f"{user_id}:{channel}"
    if key not in send_locks:
        send_locks[key] = Lock()
    return send_locks[key]

logger = logging.getLogger("agent-ws-client")

async def safe_send(user_id, channel, message):
    ws_entry = state.connections.get(user_id, {})
    ws = ws_entry.get(channel)

    if not ws:
        logger.warning(f"[WS] No WebSocket for user {user_id} on channel {channel}")
        return

    lock = get_lock(user_id, channel)
    async with lock:
        try:
            json_message = json.dumps(message)
            await ws.send(json_message)
            print(f"[WS] Sent on {channel} for {user_id}: {json_message}")
            logger.debug(f"[WS] Sent on {channel} for {user_id}")
        except asyncio.TimeoutError:
            print("[WS] Timeout waiting for server ready signal.")
        except Exception as e:
            logger.warning(f"[WS] Failed to send on {channel} for {user_id}: {e}")

import asyncio
import json
import websockets

async def start_ping_loop(ws, user_id):
    while True:
        try:
            await asyncio.sleep(20)
            await ws.send(json.dumps({"type": "ping", "userId": user_id}))
        except Exception as e:
            print(f"[Ping] Failed to send ping for {user_id}: {e}")
            break  # Exit ping loop if connection breaks

async def connect_to_dashboard_ws(channel="event"):
    server_url = config.get_api_url("/ws/connect").replace("http", "ws")
    user_id = state.user_id

    if not user_id:
        logger.error("[WS] No user id found in state.")
        return

    # Prepare connection registry
    if user_id not in state.connections:
        state.connections[user_id] = {}

    # Close previous socket on same channel, if any
    old_socket = state.connections[user_id].get(channel)
    if isinstance(old_socket, WebSocketClientProtocol) and not old_socket.closed:
        try:
            await old_socket.close()
            logger.info(f"[WS] Closed old connection on channel '{channel}' for user {user_id}")
        except Exception as ex:
            logger.warning(f"[WS] Error closing previous socket on channel '{channel}' for user {user_id}: {ex}")

    ws_url = f"{server_url}?sessionId={user_id}&type=agent-{channel}"
    logger.info(f"[WS] Connecting to dashboard broker: {ws_url} as {user_id}")

    try:
        websocket = await websockets.connect(ws_url)

        # Await initial "ready" handshake
        msg = await asyncio.wait_for(websocket.recv(), timeout=5)
        parsed = json.loads(msg)
        if parsed.get("type") == "ready":
            print("[WS] Server is ready.")

        # Save the connection
        state.connections[user_id][channel] = websocket
        logger.info(f"[WS] Connected as {user_id} on channel '{channel}'")

        # Start ping loop
        asyncio.create_task(start_ping_loop(websocket, user_id))

    except Exception as e:
        logger.warning(f"[WS] Connection failed for {user_id} ({channel}): {e}")
