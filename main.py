import os
import time
import requests
from datetime import datetime, timedelta
from kickapi import KickAPI
import re

# --- Config ---
KICK_CHANNEL = os.getenv("KICK_CHANNEL", "default_channel")  # Set default channel if not provided
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "kick-chat-notifications")  # Set default NTFY topic
POLL_INTERVAL = 5  # Polling interval in seconds
TIME_WINDOW_MINUTES = 0.01  # Time window for fetching messages

if not KICK_CHANNEL:
    raise ValueError("Please set KICK_CHANNEL environment variable")

kick_api = KickAPI()

# --- Regex Pattern for Kick emotes ---
emoji_pattern = r"\[emote:(\d+):([^\]]+)\]"

# --- Global emote dictionary (BTTV, FFZ, 7TV) ---
global_emotes = {}

def load_global_emotes():
    """Fetch global emotes from BTTV, 7TV, and FFZ."""
    try:
        # BTTV Global
        bttv = requests.get("https://api.betterttv.net/3/cached/emotes/global").json()
        for e in bttv:
            global_emotes[e["code"]] = f"https://cdn.betterttv.net/emote/{e['id']}/3x"

        # 7TV Global
        seventv = requests.get("https://7tv.io/v3/emote-sets/global").json()
        for e in seventv.get("emotes", []):
            global_emotes[e["name"]] = e["data"]["host"]["url"] + "/3x.webp"

        # FFZ Global
        ffz = requests.get("https://api.frankerfacez.com/v1/set/global").json()
        for set_id, data in ffz["sets"].items():
            for e in data["emoticons"]:
                urls = e["urls"]
                # Pick largest available size
                url = urls.get("4") or urls.get("2") or urls.get("1")
                global_emotes[e["name"]] = url

        print(f"✅ Loaded {len(global_emotes)} global emotes")
    except Exception as e:
        print("⚠️ Failed to load global emotes:", e)


def extract_emojis(text: str):
    """Replace emote codes with image URLs for Kick and global emotes."""
    emote_urls = []

    # Handle Kick native emotes
    matches = re.findall(emoji_pattern, text)
    for emote_id, emote_name in matches:
        emote_url = f"https://files.kick.com/emotes/{emote_id}/fullsize"
        emote_urls.append(emote_url)
        text = text.replace(f"[emote:{emote_id}:{emote_name}]", emote_url)

    # Handle global emotes like [KEKW]
    bracketed = re.findall(r"\[([A-Za-z0-9_]+)\]", text)
    for name in bracketed:
        if name in global_emotes:
            emote_url = global_emotes[name]
            emote_urls.append(emote_url)
            text = text.replace(f"[{name}]", emote_url)

    return text.strip(), emote_urls


def send_ntfy(user, msg, emotes):
    """Send chat message notifications to NTFY."""
    try:
        formatted_msg = f"{user}: {msg}"
        headers = {"Title": "Kick"}

        # If there are emote image URLs, attach first one
        if emotes:
            headers["Attach"] = emotes[0]
            if len(emotes) > 1:
                formatted_msg += " " + " ".join(emotes[1:])

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
    except Exception as e:
        print("⚠️ Error fetching chat:", e)
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
                    # Console shows image URLs now
                    print(f"[{msg['timestamp']}] {msg['username']}: {msg['text']}")
                    send_ntfy(msg['username'], msg['text'], msg['emotes'])
                    last_fetched_messages.add(msg_id)
                    last_sent_time = time.time()

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    load_global_emotes()
    listen_live_chat()
