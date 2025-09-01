import os
import time
import requests
from datetime import datetime, timedelta
from kickapi import KickAPI
import re
import emoji  # <-- NEW (pip install emoji)

# --- Config ---
KICK_CHANNEL = os.getenv("KICK_CHANNEL", "default_channel")  # Set default channel if not provided
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "kick-chat-notifications")  # Set default NTFY topic
POLL_INTERVAL = 5  # Polling interval in seconds
TIME_WINDOW_MINUTES = 0.01  # Time window for fetching messages (e.g., last 5 minutes)

if not KICK_CHANNEL:
    raise ValueError("Please set KICK_CHANNEL environment variable")

kick_api = KickAPI()

# --- Regex Pattern for Kick emotes ---
emoji_pattern = r"\[emote:(\d+):([^\]]+)\]"

def extract_emojis(text: str):
    """Replace Kick emote codes with Unicode when possible, otherwise keep name and record URLs."""
    emote_urls = []
    matches = re.findall(emoji_pattern, text)
    for emote_id, emote_name in matches:
        emote_url = f"https://files.kick.com/emotes/{emote_id}/fullsize"
        emote_urls.append(emote_url)

        # Try to match with Unicode emoji using python-emoji
        unicode_char = emoji.emojize(f":{emote_name.lower()}:", language="alias")

        if unicode_char != f":{emote_name.lower()}:":  # Found Unicode emoji
            replacement = unicode_char
        else:
            replacement = f"[{emote_name}]"  # fallback placeholder

        text = text.replace(f"[emote:{emote_id}:{emote_name}]", replacement)

    return text, emote_urls

def send_ntfy(user, msg, emotes):
    """Send chat message notifications to NTFY."""
    try:
        formatted_msg = f"{user}: {msg}"
        headers = { "Title": "Kick" }

        # If there are Kick emote image URLs, attach the first one
        if emotes:
            headers["Attach"] = emotes[0]

        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=formatted_msg.encode("utf-8"),
            headers=headers
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
                message_text = msg.text if hasattr(msg, 'text') else 'No text'
                message_text, emote_urls = extract_emojis(message_text)

                messages.append({
                    'username': msg.sender.username if hasattr(msg, 'sender') else 'Unknown',
                    'text': message_text,
                    'emotes': emote_urls,
                    'timestamp': datetime.now().strftime('%H:%M:%S'),
                    'channel': channel.username
                })

        return messages
    except Exception:
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
                    # Console log
                    print(f"[{msg['timestamp']}] {msg['username']}: {msg['text']}")
                    # Send to NTFY
                    send_ntfy(msg['username'], msg['text'], msg['emotes'])
                    last_fetched_messages.add(msg_id)
                    last_sent_time = time.time()

        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    listen_live_chat()
