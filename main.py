import os
import asyncio
import requests
from kickpython import KickAPI

# --- Config from Railway environment variables ---
KICK_CHANNEL = os.getenv("KICK_CHANNEL")  # e.g., "LastMove"
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "kick-chats")
NTFY_DELAY = 5  # seconds between messages

if not KICK_CHANNEL:
    raise ValueError("❌ Please set the KICK_CHANNEL environment variable on Railway")

# --- Send message to NTFY ---
async def send_ntfy(user: str, message: str):
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=f"{user}: {message}".encode("utf-8")
        )
        await asyncio.sleep(NTFY_DELAY)
    except Exception as e:
        print("⚠️ Failed to send NTFY:", e)

# --- Kick chat listener ---
async def kick_listener():
    print(f"🚀 Starting Kick chat listener for channel: {KICK_CHANNEL}")

    api = KickAPI()  # Normal instance
    while True:
        try:
            channels = await api.get_channels(KICK_CHANNEL)
        except Exception as e:
            print("❌ Error fetching channels:", e)
            await asyncio.sleep(10)
            continue

        if not channels:
            print(f"❌ Channel '{KICK_CHANNEL}' not found or offline, retrying in 10s...")
            await asyncio.sleep(10)
            continue

        channel = channels[0]
        print(f"✅ Found channel: {channel.username}")

        try:
            async for chat in api.get_chat(channel.id):
                user = chat.user.username
                message = chat.content
                print(f"{user}: {message}")
                await send_ntfy(user, message)
        except Exception as e:
            print("❌ Error fetching chat:", e)
            await asyncio.sleep(5)

# --- Run ---
if __name__ == "__main__":
    asyncio.run(kick_listener())
