import asyncio
import json
import httpx
import websockets
import logging

CHANNEL_NAME = "lastmove"  # hardcoded Kick channel
NTFY_TOPIC = "streamchats123"

logging.basicConfig(level=logging.INFO, format="%(message)s")


async def send_ntfy(message: str):
    """Send a message to NTFY with 5s delay for spam-proofing."""
    async with httpx.AsyncClient() as client:
        await client.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=message.encode("utf-8"))
    await asyncio.sleep(5)


async def get_chatroom_info():
    """Fetch chatroom metadata using the /chatroom endpoint."""
    url = f"https://kick.com/api/v2/channels/{CHANNEL_NAME}/chatroom"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url)
        if resp.status_code == 200:
            return resp.json()
        else:
            logging.error(f"❌ Failed to fetch chatroom info [{resp.status_code}]: {resp.text}")
            return None


async def connect_to_chat():
    """Connect to Kick chat WebSocket and process messages."""
    was_live = None

    while True:
        try:
            info = await get_chatroom_info()
            if not info:
                logging.info("⏳ Retrying in 10s...")
                await asyncio.sleep(10)
                continue

            # Detect LIVE / OFFLINE
            is_live = info.get("livestream") is not None
            if is_live and was_live is not True:
                logging.info(f"✅ {CHANNEL_NAME} is LIVE!")
                await send_ntfy(f"✅ {CHANNEL_NAME} is LIVE!")
            elif not is_live and was_live is not False:
                logging.info(f"❌ {CHANNEL_NAME} is OFFLINE")
                await send_ntfy(f"❌ {CHANNEL_NAME} is OFFLINE")
            was_live = is_live

            if not is_live:
                await asyncio.sleep(10)
                continue

            # Connect WebSocket using room id from chatroom info
            room_id = info["room"]["id"]
            ws_url = f"wss://chat.kick.com/chat?room_id={room_id}"
            async with websockets.connect(ws_url) as ws:
                logging.info(f"🚀 Connected to Kick chat for {CHANNEL_NAME}")

                async for raw_msg in ws:
                    try:
                        msg = json.loads(raw_msg)
                        if "username" in msg and "content" in msg:
                            username = msg["username"]
                            text = msg["content"]
                            formatted = f"{username}: {text}"
                            logging.info(f"💬 {formatted}")
                            await send_ntfy(formatted)
                    except Exception as e:
                        logging.error(f"⚠️ Failed to parse message: {e}")

        except Exception as e:
            logging.error(f"⚠️ Disconnected / error, retrying in 5s... {e}")
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(connect_to_chat())
