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
MESSAGE_DELAY = int(os.getenv("MESSAGE_DELAY", 5))  # delay in seconds between notifications

if not KICK_CHANNEL:
    raise ValueError("Please set KICK_CHANNEL environment variable")

kick_api = KickAPI()


def send_ntfy(user: str, msg: str):
    """Send chat message notifications to NTFY."""
    try:
        formatted_msg = f"{user}: {msg}"
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=formatted_msg.encode("utf-8"),
            headers={"Title": "Kick"},
        )
    except Exception:
        pass  # suppress errors so they don’t appear in log

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
    except Exception:
        return []

def listen_live_chat():
    """Listen to live chat, log instantly, send to NTFY with delay."""
    channel = kick_api.channel(KICK_CHANNEL)
    if not channel:
        raise ValueError(f"Channel '{KICK_CHANNEL}' not found")

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
                # log instantly
                print(f"[{msg['timestamp']}] {msg['username']}: {msg['text']}")

        # 2. If delay passed and queue has messages, send the next one
        if queue and (time.time() - last_sent_time >= MESSAGE_DELAY):
            msg = queue.pop(0)  # FIFO
            send_ntfy(msg["username"], msg["text"])
            last_sent_time = time.time()

        time.sleep(1)

if __name__ == "__main__":
    listen_live_chat()
