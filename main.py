import os
import time
import requests
from kickapi import KickAPI
from datetime import datetime, timedelta

# --- Config from Railway environment variables ---
KICK_CHANNEL = os.getenv("KICK_CHANNEL")  # e.g., "LastMove"
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "kick-chats")
NTFY_DELAY = 5  # seconds between messages

if not KICK_CHANNEL:
    raise ValueError("❌ Please set the KICK_CHANNEL environment variable on Railway")

# --- Send message to NTFY ---
def send_ntfy(user: str, message: str):
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=f"{user}: {message}".encode("utf-8")
        )
        time.sleep(NTFY_DELAY)
    except Exception as e:
        print("⚠️ Failed to send NTFY:", e)

# --- Kick chat listener ---
def kick_listener():
    api = KickAPI()
    print(f"🚀 Starting Kick chat listener for channel: {KICK_CHANNEL}")

    last_timestamp = None  # Track last message time for polling

    while True:
        try:
            # Fetch channel info
            channel = api.channel(KICK_CHANNEL)
            if not channel:
                print(f"❌ Channel '{KICK_CHANNEL}' not found or offline, retrying in 10s...")
                time.sleep(10)
                continue

            # Get live stream video (assuming first video is live)
            videos = api.videos(channel.id)
            if not videos:
                print(f"⏳ No active live video for '{KICK_CHANNEL}', retrying in 10s...")
                time.sleep(10)
                continue

            live_video = videos[0]  # pick first
            if not live_video.stream:
                print(f"⏳ Video is not live, retrying in 10s...")
                time.sleep(10)
                continue

            print(f"✅ Found live video: {live_video.title}")

            # Convert start time for KickApi chat fetching
            original_date_obj = datetime.strptime(live_video.start_time, '%Y-%m-%d %H:%M:%S')
            formatted_date_str = original_date_obj.strftime('%Y-%m-%dT%H:%M:%S.000Z')

            # Fetch chat
            chat = api.chat(channel.id, formatted_date_str)
            for message in chat.messages:
                user = message.sender.username
                text = message.text
                print(f"{user}: {text}")
                send_ntfy(user, text)

            # Update start_time for next iteration
            live_video.start_time = (original_date_obj + timedelta(seconds=5)).strftime('%Y-%m-%d %H:%M:%S')
            time.sleep(5)

        except Exception as e:
            print("❌ Error in Kick listener:", e)
            time.sleep(10)

# --- Run ---
if __name__ == "__main__":
    kick_listener()
