import os
import time
import requests
from datetime import datetime, timedelta
from kickapi import KickAPI
import re

# --- Config ---
KICK_CHANNEL = os.getenv("KICK_CHANNEL", "default_channel")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "kick-chat-notifications")
POLL_INTERVAL = 5  # how often to poll Kick for new messages
TIME_WINDOW_MINUTES = 0.1  # how far back to fetch messages each poll

if not KICK_CHANNEL:
    raise ValueError("Please set KICK_CHANNEL environment variable")

kick_api = KickAPI()

# --- Emoji Mapping ---
EMOJI_MAP = {
    "GiftedYAY": "🎉",
    "ErectDance": "💃",
    # Add more emojis if needed
}

emoji_pattern = r"\[emote:(\d+):([^\]]+)\]"

def extract_emoji(text: str) -> str:
    """Extract and replace Kick emote codes with mapped emojis."""
    matches = re.findall(emoji_pattern, text)
    for match in matches:
        emote_id, emote_name = match
        emoji_char = EMOJI_MAP.get(emote_name, f"[{emote_name}]")
        text = text.replace(f"[emote:{emote_id}:{emote_name}]", emoji_char)
    return text

def send_ntfy(user: str, msg: str):
    """Send chat message notifications to NTFY."""
    try:
        formatted_msg = f"{user}: {msg}"
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=formatted_msg.encode("utf-8"),
            headers={"Title": "Kick"},
        )
    except Exception as e:
        print("⚠️ Failed to send NTFY:", e)

def get_live_chat(channel_id: int):
    """Fetch live chat messages for a given channel ID."""
    try:
        past_time = datetime.utcnow() - timedelta(minutes=TIME_WINDOW_MINUTES)
        formatted_time = past_time.strftime("%Y-%m-%dT%H:%M:%S.000Z")

        chat = kick_api.chat(channel_id, formatted_time)
        messages = []

        if chat and hasattr(chat, "messages") and chat.messages:
            for msg in chat.messages:
                message_text = msg.text if hasattr(msg, "text") else "No text"
                message_text = extract_emoji(message_text)
                messages.append({
                    "id": msg.id if hasattr(msg, "id") else f"{msg.sender.username}:{message_text}",
                    "username": msg.sender.username if hasattr(msg, "sender") else "Unknown",
                    "text": message_text,
                    "timestamp": datetime.now().strftime("%H:%M:%S"),
                })

        return messages
    except Exception as e:
        print("⚠️ Error fetching chat:", e)
        return []

def listen_live_chat():
    """Listen to live chat and send messages with 5s delay between each."""
    channel = kick_api.channel(KICK_CHANNEL)
    if not channel:
        raise ValueError(f"Channel '{KICK_CHANNEL}' not found")

    print(f"✅ Connected to Kick chat for channel: {channel.username}")

    seen_ids = set()
    queue = []
    last_sent_time = 0

    while True:
        # 1. Fetch new messages
        messages = get_live_chat(channel.id)
        for msg in messages:
            if msg["id"] not in seen_ids:
                seen_ids.add(msg["id"])
                queue.append(msg)

        # 2. If 5s passed and queue has messages, send the next one
        if queue and (time.time() - last_sent_time >= 5):
            msg = queue.pop(0)  # FIFO
            print(f"[{msg['timestamp']}] {msg['username']}: {msg['text']}")
            send_ntfy(msg["username"], msg["text"])
            last_sent_time = time.time()

        time.sleep(1)  # check every second

if __name__ == "__main__":
    listen_live_chat()
