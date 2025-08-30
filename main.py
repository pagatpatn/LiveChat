import asyncio
import websockets
import json
import httpx
import logging
from fastapi import FastAPI
import uvicorn

# ---------- CONFIG ----------
CHANNEL_NAME = "lastmove"
NTFY_TOPIC = "streamchats123"
# ----------------------------

logging.basicConfig(level=logging.INFO, format="%(message)s")

app = FastAPI()

@app.get("/", include_in_schema=False)
@app.head("/", include_in_schema=False)
def home():
    return {"status": "Kick Chat Fetcher is running!"}


async def send_to_ntfy(message: str):
    async with httpx.AsyncClient() as client:
        await client.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=message.encode("utf-8"))


async def get_channel_id():
    url = f"https://kick.com/api/v2/channels/{CHANNEL_NAME}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url)
        if resp.status_code == 200:
            data = resp.json()
            return data["id"]   # channel id
        else:
            logging.error(f"❌ Could not fetch channel info: {resp.text}")
            return None


async def connect_to_chat():
    while True:
        try:
            channel_id = await get_channel_id()
            if not channel_id:
                logging.info("⏳ Retrying channel fetch in 10s...")
                await asyncio.sleep(10)
                continue

            ws_url = f"wss://chat.kick.com/socket.io/?EIO=4&transport=websocket"
            async with websockets.connect(ws_url) as ws:
                logging.info(f"🚀 Connected to Kick WebSocket for channel {CHANNEL_NAME} ({channel_id})")

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
                            await asyncio.sleep(5)
                        except Exception:
                            pass

        except Exception as e:
            logging.error(f"⚠️ Disconnected from WebSocket, retrying in 5s... {e}")
            await asyncio.sleep(5)


@app.on_event("startup")
async def start_fetcher():
    asyncio.create_task(connect_to_chat())


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000)
