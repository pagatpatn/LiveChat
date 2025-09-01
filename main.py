import os
import time
import requests
from datetime import datetime, timedelta
from kickapi import KickAPI
import re

# 🔑 Your details
KICK_CHANNEL = os.getenv("KICK_CHANNEL", "shortypie")  # Kick username
NTFY_TOPIC = "https://ntfy.sh/streamchats123"    # replace with your ntfy topic
NTFY_DELAY = 2                                   # seconds between notifications

# Track sent messages to prevent duplicates
sent_messages = set()

kick_api = KickAPI()

# Regex for Kick emotes
emoji_pattern = r"\[emote:(\d+):([^\]]+)\]"

def send_ntfy_notification(title, message, emotes=None):
    """Send a banner notification via NTFY."""
    try:
        headers = {
            "Title": title,
            "Priority": "high",
        }
        if emotes:
            headers["Attach"] = emotes[0]  # attach first emote image

        requests.post(
            NTFY_TOPIC,
            data=message.encode("utf-8"),
            headers=headers,
            timeout=5
        )
        time.sleep(NTFY_DELAY)
    except Exception as e:
        print("❌ Failed to send NTFY notification:", e)

def extract_emojis(text: str):
    """Replace Kick emotes with readable names and collect image URLs."""
    emote_urls = []
    matches = re.findall(emoji_pattern, text)
    for emote_id, emote_name in matches:
        emote_url = f"https://files.kick.com/emotes/{emote_id}/fullsize"
        emote_urls.append(emote_url)
        text = text.replace(f"[emote:{emote_id}:{emote_name}]", f"[{emote_name}]")
    return text, emote_urls

def get_live_channel():
    """Check if channel is live. Return channel object or None."""
    try:
        channel = kick_api.channel(KICK_CHANNEL)
        if channel and channel.livestream and channel.livestream.id:
            return channel
        return None
    except Exception as e:
        print("❌ Error checking live status:", e)
        return None

def listen_to_chat(channel):
    """Poll Kick chat messages in realtime until stream ends."""
    print(f"✅ Connected to Kick live chat for {channel.username}!")
    last_check = datetime.utcnow()

    while True:
        try:
            # fetch messages from last few seconds
            past_time = last_check.strftime('%Y-%m-%dT%H:%M:%S.000Z')
            chat = kick_api.chat(channel.id, past_time)
            last_check = datetime.utcnow()

            if chat and hasattr(chat, "messages") and chat.messages:
                for msg in chat.messages:
                    msg_id = getattr(msg, "id", None)
                    if not msg_id or msg_id in sent_messages:
                        continue

                    sent_messages.add(msg_id)
                    user = msg.sender.username if hasattr(msg, "sender") else "Unknown"
                    text = msg.text if hasattr(msg, "text") else ""
                    text, emotes = extract_emojis(text)

                    print(f"[Kick] {user}: {text}")

                    send_ntfy_notification(
                        title=f"New chat from {user}",
                        message=text,
                        emotes=emotes
                    )

            time.sleep(2)  # small poll interval

        except Exception as e:
            print("❌ Exception while polling chat:", e)
            time.sleep(5)
            return  # stop loop and retry outside

if __name__ == "__main__":
    while True:
        print(f"🔍 Checking if {KICK_CHANNEL} is live...")
        channel = get_live_channel()
        if channel:
            print("🎥 Live stream found! Starting chat listener...")
            listen_to_chat(channel)
            print("ℹ️ Stream ended or error. Rechecking in 10s...")
        else:
            print("⏳ Not live. Retrying in 10s...")
            time.sleep(10)
