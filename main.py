import os
import json
import asyncio
import requests
import websockets
from datetime import datetime

# --- Configuration ---
KICK_CHANNEL = os.getenv("KICK_CHANNEL", "lastmove")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "kick-chats")
DELAY = 5  # delay between NTFY messages for spam-proof

# --- Send message to NTFY ---
def send_ntfy(user: str, message: str):
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=f"{user}: {message}".encode("utf-8")
        )
    except Exception as e:
        print("⚠️ Failed to send NTFY:", e)

# --- Fetch WebSocket URL with safe parsing ---
def get_websocket_url(channel):
    url = f"https://kick.com/api/v2/channels/{channel}/chatroom"
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
        if "chatroom" not in data:
            print("❌ Kick returned no chatroom info:", data)
            return None
        return data["chatroom"].get("websocket_url")
    except Exception as e:
        print("❌ Failed to fetch WebSocket URL:", e)
        return None

# --- Listen to Kick chat ---
async def listen_chat():
    while True:
        ws_url = get_websocket_url(KICK_CHANNEL)
        if not ws_url:
            print(f"⏳ Could not get WebSocket URL for {KICK_CHANNEL}, retrying in 10s...")
            await asyncio.sleep(10)
            continue

        try:
            async with websockets.connect(ws_url) as ws:
                print(f"✅ Connected to Kick chat: {KICK_CHANNEL}")
                async for message in ws:
                    try:
                        data = json.loads(message)
                        if data.get("type") == "chat":
                            user = data["data"]["user"]["username"]
                            msg = data["data"]["message"]
                            timestamp = datetime.now().strftime("%H:%M:%S")
                            print(f"[{timestamp}] {user}: {msg}")
                            send_ntfy(user, msg)
                    except Exception as e:
                        print("⚠️ Failed to parse chat message:", e)
        except Exception as e:
            print("❌ Connection error, retrying in 5s...", e)
            await asyncio.sleep(5)

# --- Main ---
if __name__ == "__main__":
    print(f"🚀 Starting Kick chat fetcher for channel: {KICK_CHANNEL}")
    asyncio.run(listen_chat())
