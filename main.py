import os
import time
import requests
from kickapi import KickAPI
from datetime import datetime, timedelta

# --- Config ---
KICK_CHANNEL = os.getenv("KICK_CHANNEL")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "kick-chats")
NTFY_DELAY = 5

if not KICK_CHANNEL:
    raise ValueError("Please set KICK_CHANNEL environment variable")

def send_ntfy(user: str, message: str):
    try:
        requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=f"{user}: {message}".encode("utf-8"))
        time.sleep(NTFY_DELAY)
    except Exception as e:
        print("NTFY error:", e)

def kick_listener():
    api = KickAPI()
    print(f"🚀 Starting Kick chat listener for channel: {KICK_CHANNEL}")

    while True:
        try:
            channel = api.channel(KICK_CHANNEL)
            if not channel:
                print(f"❌ Channel '{KICK_CHANNEL}' not found, retrying...")
                time.sleep(10)
                continue

            # Find the live video (status == "live")
            live_video = None
            for video in channel.videos:
                if getattr(video, "status", "") == "live":
                    live_video = video
                    break

            if not live_video:
                print(f"⏳ No live video, retrying in 10s...")
                time.sleep(10)
                continue

            print(f"✅ Live video found: {live_video.title}")

            # Start fetching chat
            start_time = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
            chat = api.chat(channel.id, start_time)

            for message in chat.messages:
                user = message.sender.username
                text = message.text
                print(f"{user}: {text}")
                send_ntfy(user, text)

            time.sleep(5)

        except Exception as e:
            print("❌ Error in Kick listener:", e)
            time.sleep(10)

if __name__ == "__main__":
    kick_listener()
