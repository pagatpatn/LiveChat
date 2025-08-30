import asyncio
import websockets
import json
import httpx
import logging
from fastapi import FastAPI
import uvicorn
import os

# ---------- CONFIG ----------
CHANNEL_NAME = "lastmove"   # your Kick channel
NTFY_TOPIC = "streamchats123"    # ntfy topic name
# ----------------------------

logging.basicConfig(level=logging.INFO, format="%(message)s")

app = FastAPI()

@app.get("/", include_in_schema=False)
@app.head("/", include_in_schema=False)
def home():
    return {"status": "Kick Chat Fetcher is running!"}


async def send_to_ntfy(message: str):
    """Send formatted text to ntfy topic"""
    async with httpx.AsyncClient() as client:
        try:
            await client.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=message.encode("utf-8"))
        except Exception as e:
            logging.error(f"❌ Failed to send ntfy message: {e}")


async def get_channel_info():
    """Fetch channel info from Kick API"""
    url = f"https://kick.com/api/v2/channels/{CHANNEL_NAME}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url)
        if resp.status_code == 200:
            return resp.json()
        else:
            logging.error(f"❌ Channel fetch failed [{resp.status_code}]: {resp.text}")
            return None


async def connect_to_chat():
    """Connect to Kick WebSocket chat and process messages"""
    was_live = None  # track last known live status

    while True:
        try:
            channel_info = await get_channel_info()
            if not channel_info:
                logging.info("⏳ Retrying channel fetch in 10s...")
                await asyncio.sleep(10)
                continue

            channel_id = channel_info["id"]
            is_live = channel_info.get("livestream") is not None

            # Detect LIVE/OFFLINE status change
            if is_live and was_live is not True:
                logging.info(f"✅ {CHANNEL_NAME} is LIVE!")
                await send_to_ntfy(f"✅ {CHANNEL_NAME} is LIVE!")
            elif not is_live and was_live is not False:
                logging.info(f"❌ {CHANNEL_NAME} is OFFLINE.")
                await send_to_ntfy(f"❌ {CHANNEL_NAME} is OFFLINE.")

            was_live = is_live

            if not is_live:
                await asyncio.sleep(15)
                continue

            # Only connect WebSocket if live
            ws_url = "wss://chat.kick.com/socket.io/?EIO=4&transport=websocket"
            async with websockets.connect(ws_url) as ws:
                logging.info(f"🚀 Connected to Kick chat for {CHANNEL_NAME} ({channel_id})")

                while True:
                    msg = await ws.recv()
                    if "message" in msg:
                        try:
                            data = json.loads(msg)
                            username = data.get("username", "Unknown")
                            text = data.get("content", "")
                            formatted = f"{username}: {text}"
                            logging.info(f"💬 {formatted}")
                            await send_to_ntfy(formatted)
                            await asyncio.sleep(5)  # anti-spam delay
                        except Exception:
                            pass

        except Exception as e:
            logging.error(f"⚠️ Disconnected from WebSocket, retrying in 5s... {e}")
            await asyncio.sleep(5)


@app.on_event("startup")
async def start_fetcher():
    asyncio.create_task(connect_to_chat())


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))  # ✅ Render-compatible port
    uvicorn.run(app, host="0.0.0.0", port=port)
