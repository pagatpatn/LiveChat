import os
import time
from datetime import datetime, timedelta
import requests
from kickapi import KickAPI

# --- Config ---
KICK_CHANNEL = os.getenv("KICK_CHANNEL")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "kick-chats")
POLL_INTERVAL = 5  # seconds

if not KICK_CHANNEL:
    raise ValueError("Please set KICK_CHANNEL environment variable")

kick_api = KickAPI()

def send_ntfy(user, msg):
    try:
        requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=f"{user}: {msg}".encode("utf-8"))
        time.sleep(POLL_INTERVAL)
    except Exception as e:
        print("⚠️ Failed to send NTFY:", e)

def get_live_video():
    """Return live video object or None if no live"""
    try:
        # Attempt to fetch using just the channel name
        channel = kick_api.channel(KICK_CHANNEL)
        
        if not channel:  # if channel is None, try full URL (fallback)
            print(f"⚠️ Channel {KICK_CHANNEL} not found, trying full URL...")
            channel = kick_api.channel(f"https://kick.com/{KICK_CHANNEL}")  # Use full URL

        if channel:
            for video in channel.videos:
                if getattr(video, "live", False):  # check live attribute
                    return video
        else:
            print("❌ Channel not found or videos not available.")
    except Exception as e:
        print(f"❌ Failed to fetch channel/videos: {e}")
    return None

def listen_live_chat():
    print(f"🚀 Starting Kick chat listener for channel: {KICK_CHANNEL}")
    while True:
        video = get_live_video()
        if not video:
            print("⏳ No live video, retrying in 10s...")
            time.sleep(10)
            continue

        print(f"✅ Found live video: {video.title}")
        # Parse start_time for chat polling
        start_time_obj = datetime.strptime(video.start_time, "%Y-%m-%d %H:%M:%S")
        while True:
            try:
                formatted_time = start_time_obj.strftime("%Y-%m-%dT%H:%M:%S.000Z")
                chat = kick_api.chat(video.channel.id, formatted_time)

                for msg in chat.messages:
                    user = msg.sender.username
                    text = msg.text
                    print(f"{user}: {text}")
                    send_ntfy(user, text)

                # increment start_time by POLL_INTERVAL
                start_time_obj += timedelta(seconds=POLL_INTERVAL)
                time.sleep(POLL_INTERVAL)

            except Exception as e:
                print("❌ Error fetching chat, retrying live video in 10s...", e)
                time.sleep(10)
                break  # break inner loop to re-fetch live video

if __name__ == "__main__":
    listen_live_chat()
