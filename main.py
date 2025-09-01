import os
import time
import requests
from datetime import datetime, timedelta
from kickapi import KickAPI
import re

# --- Config ---
KICK_CHANNEL = os.getenv("KICK_CHANNEL", "default_channel")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "kick-chat-notifications")
POLL_INTERVAL = 3
TIME_WINDOW_MINUTES = 0.01

# Load BTTV global emotes
BTTV_EMOTES = {}
try:
    resp = requests.get("https://api.betterttv.net/3/cached/emotes/global")
    for e in resp.json():
        BTTV_EMOTES[e['emote']['code']] = e['emote']['id']
except:
    pass

# Emote pattern
emoji_pattern = r"\[emote:(\d+):([^\]]+)\]"

def extract_emojis(text: str):
    """Extract Kick emotes and BTTV matches; return text + image URLs list."""
    emote_urls = []
    matches = re.findall(emoji_pattern, text)
    for emote_id, emote_name in matches:
        kick_url = f"https://files.kick.com/emotes/{emote_id}/fullsize"
        emote_urls.append(kick_url)
        # Replace placeholder text
        text = text.replace(f"[emote:{emote_id}:{emote_name}]", f"[{emote_name}]")

        # If BTTV also has this emote, add its image URL
        bttv_id = BTTV_EMOTES.get(emote_name)
        if bttv_id:
            bttv_url = f"https://cdn.betterttv.net/emote/{bttv_id}/3x"
            emote_urls.append(bttv_url)

    return text, emote_urls

def send_ntfy(user, msg, emotes):
    headers = {"Title": "Kick"}
    if emotes:
        headers["Attach"] = emotes[0]
        # Append additional emote URLs to message text
        formatted_msg = f"{user}: {msg} " + " ".join(emotes[1:])
    else:
        formatted_msg = f"{user}: {msg}"
    requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=formatted_msg.encode(), headers=headers)

def get_live_chat():
    try:
        channel = kick_api.channel(KICK_CHANNEL)
        if not channel:
            return None
        past = (datetime.utcnow() - timedelta(minutes=TIME_WINDOW_MINUTES)).strftime('%Y-%m-%dT%H:%M:%S.000Z')
        chat = kick_api.chat(channel.id, past)
        messages = []
        if chat and hasattr(chat, 'messages'):
            for m in chat.messages:
                txt = m.text if hasattr(m, 'text') else 'No text'
                txt, urls = extract_emojis(txt)
                messages.append({
                    'username': m.sender.username if hasattr(m, 'sender') else 'Unknown',
                    'text': txt,
                    'emotes': urls,
                    'timestamp': datetime.now().strftime('%H:%M:%S')
                })
        return messages
    except:
        return None

def listen_live_chat():
    last_seen = set()
    last_sent = time.time()
    while True:
        msgs = get_live_chat()
        if msgs:
            for msg in msgs:
                msg_id = f"{msg['username']}:{msg['text']}"
                if msg_id not in last_seen and time.time() - last_sent >= 5:
                    print(f"[{msg['timestamp']}] {msg['username']}: {msg['text']}")
                    send_ntfy(msg['username'], msg['text'], msg['emotes'])
                    last_seen.add(msg_id)
                    last_sent = time.time()
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    listen_live_chat()
