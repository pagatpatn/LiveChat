import os
import time
import requests
from datetime import datetime, timedelta
from kickapi import KickAPI
import re

# --- Config ---
KICK_CHANNEL = os.getenv("KICK_CHANNEL", "default_channel")  # Set default channel if not provided
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "kick-chat-notifications")  # Set default NTFY topic
POLL_INTERVAL = 0.1  # Polling interval in seconds
TIME_WINDOW_MINUTES = 0.05  # Time window for fetching messages (e.g., last 5 minutes)

if not KICK_CHANNEL:
    raise ValueError("Please set KICK_CHANNEL environment variable")

kick_api = KickAPI()

emoji_pattern = r"\[emote:(\d+):([^\]]+)\]"

def extract_emojis(msg):
    """Replace Kick emote placeholders with their actual image URLs."""
    text = msg.text if hasattr(msg, 'text') else 'No text'

    if hasattr(msg, "emotes") and msg.emotes:
        for emote in msg.emotes:
            if hasattr(emote, "id") and hasattr(emote, "code"):
                placeholder = f"[emote:{emote.id}:{emote.code}]"
                # Kick usually provides image URLs under emote.image or emote.src
                emote_url = None
                if hasattr(emote, "image") and isinstance(emote.image, dict):
                    emote_url = emote.image.get("src")
                elif hasattr(emote, "src"):
                    emote_url = emote.src

                if emote_url:
                    # Replace with actual image link (since NTFY supports Markdown/images)
                    replacement = f"![]({emote_url})"
                else:
                    replacement = f":{emote.code}:"

                text = text.replace(placeholder, replacement)

    return text

def send_ntfy(user, msg):
    """Send chat message notifications to NTFY."""
    try:
        # Format message before sending to NTFY
        formatted_msg = f"{user}: {msg}"

        # Send the notification with the Title Kick
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=formatted_msg.encode("utf-8"),
            headers={"Title": "Kick", "Markdown": "yes"}  # enable Markdown for inline images
        )
    except Exception as e:
        print("⚠️ Failed to send NTFY:", e)

def get_live_chat():
    """Fetch live chat messages for the given channel."""
    try:
        channel = kick_api.channel(KICK_CHANNEL)
        if not channel:
            return None

        past_time = datetime.utcnow() - timedelta(minutes=TIME_WINDOW_MINUTES)
        formatted_time = past_time.strftime('%Y-%m-%dT%H:%M:%S.000Z')

        chat = kick_api.chat(channel.id, formatted_time)
        messages = []

        if chat and hasattr(chat, 'messages') and chat.messages:
            for msg in chat.messages:
                # Replace emotes with image URLs
                message_text = extract_emojis(msg)
                messages.append({
                    'username': msg.sender.username if hasattr(msg, 'sender') else 'Unknown',
                    'text': message_text,
                    'timestamp': datetime.now().strftime('%H:%M:%S'),
                    'channel': channel.username
                })

        return messages
    except Exception as e:
        return None

def listen_live_chat():
    """Fetch and listen to live chat for the channel."""
    last_fetched_messages = set()
    last_sent_time = time.time()

    while True:
        messages = get_live_chat()
        if not messages:
            time.sleep(10)
            continue

        for msg in messages:
            msg_id = f"{msg['username']}:{msg['text']}"
            if msg_id not in last_fetched_messages:
                if time.time() - last_sent_time >= 5:
                    print(f"[{msg['timestamp']}] {msg['username']}: {msg['text']}")
                    send_ntfy(msg['username'], msg['text'])
                    last_fetched_messages.add(msg_id)
                    last_sent_time = time.time()

        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    listen_live_chat()
