import asyncio
import websockets
import logging
import json
import base64
from common import config, state

logger = logging.getLogger("agent-ws-client")

async def connect_to_dashboard_ws():
    server_url = config.get_api_url("/ws/connect").replace("http", "ws")

    if not state.user_id:
        logger.error("[WS] No user id found in state.")
        return

    ws_url = f"{server_url}?userId={state.user_id}&type=agent"
    logger.info(f"[WS] Connecting to dashboard broker: {ws_url} as {state.user_id}")

    while True:
        try:
            async with websockets.connect(ws_url) as websocket:
                state.connections[state.user_id] = websocket
                logger.info(f"[WS] Connected as {state.user_id}")

                while True:
                    await asyncio.sleep(20)
                    await websocket.send(json.dumps({"type": "ping"}))
        except Exception as e:
            logger.warning(f"[WS] Disconnected: {e} — retrying in 5s")
            state.connections[state.user_id] = None
            await asyncio.sleep(5)
