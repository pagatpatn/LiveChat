import asyncio
import websockets
import json
import httpx
import logging
from fastapi import FastAPI
import uvicorn

# ---------- CONFIG ----------
CHANNEL_NAME = "LastMove"
NTFY_TOPIC = "streamchats123"
# ----------------------------

logging.basicConfig(level=logging.INFO, format="%(message)s")

app = FastAPI()

@app.get("/")
def home():
    return {"status": "Kick Chat Fetcher is running!"}

async def send_to_ntfy(message: str):
    async with httpx.AsyncClient() as client:
        await client.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=message.encode("utf-8"))

async def connect_to_chat():
    url = f"wss://chat.kick.com/socket.io/?EIO=4&transport=websocket"

    while True:
        try:
            async with websockets.connect(url) as ws:
                logging.info(f"🚀 Connected to Kick WebSocket for channel: {CHANNEL_NAME}")

                while True:
                    msg = await ws.recv()

                    # Simple debug log
                    if "text" in msg:
                        try:
                            data = json.loads(msg)
                            username = data.get("username", "Unknown")
                            text = data.get("text", "")
                            formatted = f"{username}: {text}"
                            logging.info(f"💬 {formatted}")
                            await send_to_ntfy(formatted)
                            await asyncio.sleep(5)  # delay for spam-proof
                        except:
                            pass
        except Exception as e:
            logging.error(f"⚠️ Disconnected from WebSocket, retrying in 5s... {e}")
            await asyncio.sleep(5)

@app.on_event("startup")
async def start_fetcher():
    asyncio.create_task(connect_to_chat())

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=10000)
