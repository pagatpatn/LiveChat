import os
import json
import asyncio
import websockets
import requests
from datetime import datetime

# --- Environment Variables ---
KICK_CHANNEL = os.getenv("KICK_CHANNEL", "your_channel_name")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "chat-notifier")

# --- Fetch WebSocket URL ---
def get_websocket_url(channel):
    url = f"https://kick.com/api/v2/channels/{channel}/chatroom"
    response = requests.get(url)
    data = response.json()
    return data["chatroom"]["websocket_url"]

# --- Send Notifications ---
def send_ntfy(platform, user, msg):
    payload = {
        "topic": NTFY_TOPIC,
        "message": f"[{platform}] {user}: {msg}",
        "priority": 1,
        "tags": ["chat"]
    }
    requests.post("https://ntfy.sh", json=payload)

# --- WebSocket Listener ---
async def listen_chat():
    ws_url = get_websocket_url(KICK_CHANNEL)
    async with websockets.connect(ws_url) as ws:
        print(f"Connected to Kick chat: {KICK_CHANNEL}")
        while True:
            message = await ws.recv()
            data = json.loads(message)
            if data.get("type") == "chat":
                user = data["data"]["user"]["username"]
                msg = data["data"]["message"]
                print(f"[{datetime.now().strftime('%H:%M:%S')}] {user}: {msg}")
                send_ntfy("Kick", user, msg)

# --- Run the Listener ---
if __name__ == "__main__":
    asyncio.run(listen_chat())
