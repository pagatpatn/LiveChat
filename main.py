import asyncio
import json
import websockets
import httpx
import time

# Hardcode your channel name
CHANNEL_NAME = "lastmove"

# NTFY topic for notifications
NTFY_TOPIC = "kickchats"

# Kick WebSocket endpoint
KICK_WS = "wss://ws2.kick.com/socket.io/?EIO=3&transport=websocket"

async def send_to_ntfy(message: str):
    """Send chat message to ntfy topic"""
    url = f"https://ntfy.sh/{NTFY_TOPIC}"
    try:
        async with httpx.AsyncClient() as client:
            await client.post(url, content=message)
    except Exception as e:
        print(f"❌ Failed to send ntfy message: {e}")

async def connect_kick():
    """Connect to Kick websocket and fetch chat messages"""
    while True:
        try:
            async with websockets.connect(KICK_WS) as ws:
                print(f"🚀 Connected to Kick WebSocket for channel: {CHANNEL_NAME}")

                # Kick WebSocket handshake
                await ws.send("40")  

                # Subscribe to channel room
                await ws.send(f'42["join",{{"name":"chatrooms.{CHANNEL_NAME}"}}]')

                while True:
                    msg = await ws.recv()
                    
                    if msg.startswith("42"):
                        try:
                            data = json.loads(msg[2:])
                            event = data[0]
                            payload = data[1]

                            if event == "ChatMessage":
                                username = payload["sender"]["username"]
                                text = payload["content"]
                                message = f"{username}: {text}"

                                print(f"💬 {message}")
                                await send_to_ntfy(message)

                                # Delay 5s to prevent spam flood
                                time.sleep(5)

                        except Exception as e:
                            print(f"⚠️ Error parsing message: {e}")
        except Exception as e:
            print(f"❌ Disconnected from Kick WebSocket: {e}")
            print("🔄 Retrying in 5s...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(connect_kick())
