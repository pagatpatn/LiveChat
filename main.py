import os
import time
import requests
from datetime import datetime
from kickapi import KickAPI
import re

# --- Config ---
KICK_CHANNEL = os.getenv("KICK_CHANNEL", "default_channel")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "kick-chat-notifications")
POLL_INTERVAL = 3  # Poll every few seconds

if not KICK_CHANNEL:
    raise ValueError("Please set KICK_CHANNEL environment variable")

kick_api = KickAPI()

# --- Emoji Mapping ---
EMOJI_MAP = {
    "GiftedYAY": "🎉",
    "ErectDance": "💃",
    # Add more as needed
}
emoji_pattern = r"\[emote:(\d+):([^\]]+)\]"

def extract_emoji(text):
    """Replace Kick emote codes with real emojis."""
    matches = re.findall(emoji_pattern, text)
    for emote_id, emote_name in matches:
        emoji = EMOJI_MAP.get(emote_name, f"[{emote_name}]")
        text = text.replace(f"[emote:{emote_id}:{emote_name}]", emoji)
    return text

def send_ntfy(user, msg):
    """Send chat message to NTFY."""
    try:
        formatted_msg = f"{user}: {msg}"
        requests.post(f"https://ntfy.sh/{NTFY_TOPIC}",
                      data=formatted_msg.encode("utf-8"),
                      headers={"Title": "Kick"})
    except Exception as e:
        print("⚠️ Failed to send NTFY:", e)

def get_live_chat(channel_id):
    """Fetch recent live chat messages for the given channel."""
    try:
        chat = kick_api.chat(channel_id)
        messages = []

        if chat and hasattr(chat, 'messages') and chat.messages:
            for msg in chat.messages:
                text = getattr(msg, "text", "") or ""
                text = extract_emoji(text)
                messages.append({
                    "id": msg.id,  # real unique Kick message ID
                    "username": msg.sender.username if hasattr(msg, 'sender') else "Unknown",
                    "text": text,
                    "timestamp": datetime.now().strftime("%H:%M:%S")
                })

        return messages
    except Exception as e:
        print("⚠️ Error fetching chat:", e)
        return []

def listen_live_chat():
    """Listen to live chat in real time."""
    channel = kick_api.channel(KICK_CHANNEL)
    if not channel:
        raise ValueError(f"Channel '{KICK_CHANNEL}' not found")

    print(f"✅ Connected to Kick chat for channel: {channel.username}")
    seen_ids = set()

    while True:
        messages = get_live_chat(channel.id)

        for msg in messages:
            if msg["id"] not in seen_ids:
                print(f"[{msg['timestamp']}] {msg['username']}: {msg['text']}")
                send_ntfy(msg["username"], msg["text"])
                seen_ids.add(msg["id"])

        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    listen_live_chat()
