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
    """Send chat message notifications."""
    try:
        requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=f"{user}: {msg}".encode("utf-8"))
        time.sleep(POLL_INTERVAL)
    except Exception as e:
        print("⚠️ Failed to send NTFY:", e)

def get_live_video():
    """Return live video object or None if no live video is found."""
    try:
        print(f"Fetching data for channel: {KICK_CHANNEL}")
        
        # Attempt to fetch using just the channel name
        channel = kick_api.channel(KICK_CHANNEL)

        if not channel:  # if channel is None, try full URL (fallback)
            print(f"⚠️ Channel {KICK_CHANNEL} not found, trying full URL...")
            channel = kick_api.channel(f"https://kick.com/{KICK_CHANNEL}")  # Use full URL

        if channel:
            print(f"✅ Channel {channel.username} found.")
            # Log the channel's raw data
            print(f"Channel Raw Data: {channel.__dict__}")
            
            for video in channel.videos:
                # Log the video data for debugging
                print(f"Video Raw Data: {video.__dict__}")
                if hasattr(video, "live") and video.live:  # check live attribute
                    return video
        else:
            print("❌ Channel not found or videos not available.")
    except Exception as e:
        print(f"❌ Failed to fetch channel/videos: {e}")
    return None

def listen_live_chat():
    """Fetch and listen to live chat for a Kick video."""
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
                print(f"Fetching chat data at time: {formatted_time}")
                chat = kick_api.chat(video.channel.id, formatted_time)

                # Log chat data for debugging
                print(f"Fetched {len(chat.messages)} messages.")
                
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
