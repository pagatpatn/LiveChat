import os
import asyncio
import requests
from kickpython import KickAPI

# --- Configuration ---
KICK_CHANNEL = os.getenv("lastmove", "lastmove")
NTFY_TOPIC = os.getenv("streamchats123", "kick-chats")

# --- Initialize Kick API ---
api = KickAPI()  # public channel, no OAuth needed

# --- Send to NTFY ---
def send_ntfy(user: str, message: str):
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=f"{user}: {message}".encode("utf-8")
        )
    except Exception as e:
        print("⚠️ Failed to send NTFY:", e)

# --- Kick Chat Listener ---
async def kick_listener():
    print(f"🚀 Starting Kick chat listener for channel: {KICK_CHANNEL}")

    # Use get_channels instead of get_channel
    channels = await api.get_channels(KICK_CHANNEL)
    if not channels:
        print(f"❌ Channel '{KICK_CHANNEL}' not found")
        return
    channel = channels[0]  # pick the first match

    async for chat in api.get_chat(channel.id):
        user = chat.user.username
        message = chat.content
        print(f"{user}: {message}")
        send_ntfy(user, message)

# --- Run ---
if __name__ == "__main__":
    asyncio.run(kick_listener())
