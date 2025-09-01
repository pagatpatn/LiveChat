import os
import time
import requests
from datetime import datetime, timedelta
from kickapi import KickAPI
import re

# --- Config ---
KICK_CHANNEL = os.getenv("KICK_CHANNEL", "default_channel")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "kick-chat-notifications")
POLL_INTERVAL = 5
TIME_WINDOW_MINUTES = 0.05

if not KICK_CHANNEL:
    raise ValueError("Please set KICK_CHANNEL environment variable")

kick_api = KickAPI()

# Extract emote patterns
emoji_pattern = r"\[emote:(\d+):([^\]]+)\]"

def extract_emojis(text: str):
    """Extract Kick emote placeholders, return cleaned text + list of image URLs."""
    matches = re.findall(emoji_pattern, text)
    emote_urls = []
    for emote_id, emote_name in matches:
        emote_urls.append(f"https://files.kick.com/emotes/{emote_id}/fullsize")
        # Replace placeholder with readable name
        text = text.replace(f"[emote:{emote_id}:{emote_name}]", f"[{emote_name}]")
    return text, emote_urls

def send_ntfy(user, msg, emote_urls=None):
    """Send message to NTFY and attach the first emote image if available."""
    try:
        formatted_msg = f"{user}: {msg}"
        headers = {"Title": "Kick"}
        if emote_urls:
            headers["Attach"] = emote_urls[0]
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=formatted_msg.encode("utf-8"),
            headers=headers
        )
    except Exception as e:
        print("⚠️ Failed to send NTFY:", e)

def get_live_chat():
    """Fetch live messages and process emotes."""
    try:
        channel = kick_api.channel(KICK_CHANNEL)
        if not channel:
            return None

        past = (datetime.utcnow() - timedelta(minutes=TIME_WINDOW_MINUTES)).strftime('%Y-%m-%dT%H:%M:%S.000Z')
        chat = kick_api.chat(channel.id, past)
        messages = []
        if chat and hasattr(chat, 'messages') and chat.messages:
            for msg in chat.messages:
                text = msg.text if hasattr(msg, 'text') else 'No text'
                text, emotes = extract_emojis(text)
                messages.append({
                    'username': msg.sender.username if hasattr(msg, 'sender') else 'Unknown',
                    'text': text,
                    'emotes': emotes,
                    'timestamp': datetime.now().strftime('%H:%M:%S'),
                    'channel': channel.username
                })
        return messages
    except:
        return None

def listen_live_chat():
    """Continuously listen for new messages and notify accordingly."""
    last_fetched = set()
    last_sent = time.time()

    while True:
        msgs = get_live_chat()
        if not msgs:
            time.sleep(10)
            continue

        for msg in msgs:
            msg_id = f"{msg['username']}:{msg['text']}"
            if msg_id not in last_fetched and time.time() - last_sent >= 5:
                print(f"[{msg['timestamp']}] {msg['username']}: {msg['text']}")
                send_ntfy(msg['username'], msg['text'], msg.get('emotes'))
                last_fetched.add(msg_id)
                last_sent = time.time()

        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    listen_live_chat()
