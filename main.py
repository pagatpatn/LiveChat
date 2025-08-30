import os
import time
import re
import requests
from datetime import datetime, timedelta
from kickapi import KickAPI

# --- Config ---
KICK_CHANNEL = os.getenv("KICK_CHANNEL", "default_channel")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "kick-chat-notifications")
POLL_INTERVAL = 5  # seconds
TIME_WINDOW_MINUTES = 5  # Increase time window to 5 minutes

if not KICK_CHANNEL:
    raise ValueError("Please set KICK_CHANNEL environment variable")

kick_api = KickAPI()

# Emoji regex pattern
emoji_pattern = r"\[emote:(\d+):([^\]]+)\]"

def send_ntfy(user, msg):
    """Send chat message notifications."""
    try:
        requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=f"{user}: {msg}".encode("utf-8"))
        time.sleep(POLL_INTERVAL)
    except Exception as e:
        print("⚠️ Failed to send NTFY:", e)

def extract_emoji(text):
    """Extract and replace emojis from the text."""
    matches = re.findall(emoji_pattern, text)
    if matches:
        # Replace emote with actual emoji text
        for match in matches:
            emote_id, emote_name = match
            text = text.replace(f"[emote:{emote_id}:{emote_name}]", f"🎉 {emote_name}")  # Example of emoji handling
    return text

def get_live_chat():
    """Get live chat messages for a channel."""
    try:
        print(f"Fetching live chat for channel: {KICK_CHANNEL}")
        channel = kick_api.channel(KICK_CHANNEL)

        if not channel:
            print(f"❌ Channel {KICK_CHANNEL} not found.")
            return None
        
        print(f"✅ Found channel {channel.username}")
        # Fetch messages within the last TIME_WINDOW_MINUTES
        past_time = datetime.utcnow() - timedelta(minutes=TIME_WINDOW_MINUTES)
        formatted_time = past_time.strftime('%Y-%m-%dT%H:%M:%S.000Z')

        chat = kick_api.chat(channel.id, formatted_time)
        messages = []
        
        if chat and hasattr(chat, 'messages') and chat.messages:
            for msg in chat.messages:
                messages.append({
                    'username': msg.sender.username if hasattr(msg, 'sender') else 'Unknown',
                    'text': extract_emoji(msg.text) if hasattr(msg, 'text') else 'No text',
                    'timestamp': datetime.now().strftime('%H:%M:%S'),
                    'channel': channel.username
                })
        
        return messages
    except Exception as e:
        print(f"❌ Error fetching live chat: {e}")
        return None

def listen_live_chat():
    """Fetch and listen to live chat for a Kick video."""
    print(f"🚀 Starting live chat listener for channel: {KICK_CHANNEL}")
    last_fetched_messages = set()  # Store messages we have already sent

    while True:
        messages = get_live_chat()
        
        if not messages:
            print("⏳ No new live messages, retrying in 10s...")
            time.sleep(10)
            continue

        for msg in messages:
            msg_id = f"{msg['username']}:{msg['text']}"  # Unique message identifier
            
            if msg_id not in last_fetched_messages:
                print(f"{msg['username']}: {msg['text']}")
                send_ntfy(msg['username'], msg['text'])
                last_fetched_messages.add(msg_id)

        time.sleep(10)  # Poll every 10 seconds

if __name__ == "__main__":
    listen_live_chat()
