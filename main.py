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
TIME_WINDOW_MINUTES = 0.01

if not KICK_CHANNEL:
    raise ValueError("Please set KICK_CHANNEL environment variable")

kick_api = KickAPI()

# --- Emoji / Emote Handling ---
emoji_pattern = r"\[emote:(\d+):([^\]]+)\]"

def extract_emojis(text: str):
    """
    Replace [emote:id:name] with a readable name and collect the emote's
    image URLs for display via NTFY Attach header.
    """
    matches = re.findall(emoji_pattern, text)
    emote_urls = []
    for emote_id, emote_name in matches:
        # Replace in-text with [NAME]
        placeholder = f"[emote:{emote_id}:{emote_name}]"
        display = f"[{emote_name}]"
        text = text.replace(placeholder, display)
        # Build URL to the full-size Kick emote
        emote_urls.append(f"https://files.kick.com/emotes/{emote_id}/fullsize")
    return text, emote_urls

def send_ntfy(user, msg, emote_urls=None):
    """
    Send chat message to NTFY with optional emote image via 'Attach' header.
    The image will appear if the client supports it.
    """
    headers = {"Title": "Kick"}
    if emote_urls:
        headers["Attach"] = emote_urls[0]  # NTFY supports a single image attachment
    formatted_msg = f"{user}: {msg}"
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=formatted_msg.encode("utf-8"),
            headers=headers
        )
    except Exception as e:
        print("⚠️ Failed to send NTFY:", e)

# --- Fetch Live Chat ---
def get_live_chat():
    try:
        channel = kick_api.channel(KICK_CHANNEL)
        if not channel:
            return None
        
        past = datetime.utcnow() - timedelta(minutes=TIME_WINDOW_MINUTES)
        ts = past.strftime('%Y-%m-%dT%H:%M:%S.000Z')
        chat = kick_api.chat(channel.id, ts)
        results = []
        if chat and hasattr(chat, 'messages'):
            for msg in chat.messages:
                txt = msg.text if hasattr(msg, 'text') else 'No text'
                txt, emotes = extract_emojis(txt)
                results.append({
                    'username': msg.sender.username if hasattr(msg, 'sender') else 'Unknown',
                    'text': txt,
                    'emotes': emotes,
                    'timestamp': datetime.now().strftime('%H:%M:%S'),
                })
        return results
    except Exception:
        return None

# --- Listen Live Chat ---
def listen_live_chat():
    last_msgs = set()
    last_sent = time.time()

    while True:
        messages = get_live_chat()
        if not messages:
            time.sleep(10)
            continue

        for m in messages:
            mid = f"{m['username']}:{m['text']}"
            if mid not in last_msgs and time.time() - last_sent >= 5:
                print(f"[{m['timestamp']}] {m['username']}: {m['text']}")
                send_ntfy(m['username'], m['text'], m.get('emotes'))
                last_msgs.add(mid)
                last_sent = time.time()

        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    listen_live_chat()
