import asyncio
import json
import websockets
import aiohttp

CHANNEL_NAME = "lastmove"   # hardcoded channel
NTFY_TOPIC = "streamchats123"

KICK_WS_URL = "wss://chat-server.kick.com/ws"


async def send_ntfy(message: str):
    """Send message to NTFY topic with a delay for spam proof."""
    async with aiohttp.ClientSession() as session:
        await session.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=message.encode("utf-8"))
    await asyncio.sleep(5)  # delay to avoid spam


async def connect_to_chat():
    """Keep trying to connect to Kick WebSocket and listen for messages."""
    while True:
        try:
            print(f"🔎 Checking if channel '{CHANNEL_NAME}' is live...")

            async with websockets.connect(KICK_WS_URL) as ws:
                # Join chat room
                join_payload = {
                    "method": "join",
                    "params": {
                        "room": f"channel:{CHANNEL_NAME}"
                    },
                    "id": 1
                }
                await ws.send(json.dumps(join_payload))

                print(f"✅ Channel '{CHANNEL_NAME}' is LIVE. Listening for chats...")

                # Process messages
                async for raw_msg in ws:
                    try:
                        msg = json.loads(raw_msg)

                        if "params" in msg and "room" in msg["params"]:
                            data = msg["params"]
                            if "username" in data and "content" in data:
                                username = data["username"]
                                text = data["content"]
                                formatted = f"{username}: {text}"
                                print(f"💬 {formatted}")
                                await send_ntfy(formatted)

                    except Exception as e:
                        print(f"⚠️ Error parsing chat message: {e}")

        except Exception as e:
            print(f"❌ Channel '{CHANNEL_NAME}' seems OFFLINE or disconnected. Retrying in 5s... ({e})")
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(connect_to_chat())
