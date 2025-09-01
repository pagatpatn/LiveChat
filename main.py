import os
import time
import requests
import threading
from datetime import datetime, timedelta
from kickapi import KickAPI
import re

# ========== ENVIRONMENT VARIABLES ==========
# Kick
KICK_CHANNEL = os.getenv("KICK_CHANNEL")
# YouTube
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
YOUTUBE_CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID")
# Common
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "streamchats123")
NTFY_DELAY = int(os.getenv("NTFY_DELAY", "5"))  # delay between NTFY sends

# --- Kick API Init ---
kick_api = KickAPI()

# --- Emoji Mapping ---
EMOJI_MAP = {
    "GiftedYAY": "🎉",
    "ErectDance": "💃",
}
emoji_pattern = r"\[emote:(\d+):([^\]]+)\]"

def extract_emoji(text: str) -> str:
    """Replace Kick emote codes with mapped emojis."""
    matches = re.findall(emoji_pattern, text)
    for emote_id, emote_name in matches:
        emoji_char = EMOJI_MAP.get(emote_name, f"[{emote_name}]")
        text = text.replace(f"[emote:{emote_id}:{emote_name}]", emoji_char)
    return text

def send_ntfy(title: str, msg: str):
    """Send chat message notifications to NTFY."""
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=msg.encode("utf-8"),
            headers={"Title": title},
            timeout=5,
        )
        time.sleep(NTFY_DELAY)
    except Exception as e:
        print("⚠️ Failed to send NTFY:", e)

# ========== KICK CHAT FETCHER ==========
def get_kick_chat(channel_id: int, seen_ids: set, queue: list):
    try:
        past_time = datetime.utcnow() - timedelta(minutes=0.1)
        formatted_time = past_time.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        chat = kick_api.chat(channel_id, formatted_time)

        if chat and hasattr(chat, "messages") and chat.messages:
            for msg in chat.messages:
                message_text = extract_emoji(getattr(msg, "text", ""))
                msg_id = getattr(msg, "id", f"{msg.sender.username}:{message_text}")

                if msg_id not in seen_ids:
                    seen_ids.add(msg_id)
                    entry = {
                        "id": msg_id,
                        "username": msg.sender.username if hasattr(msg, "sender") else "Unknown",
                        "text": message_text,
                        "timestamp": datetime.now().strftime("%H:%M:%S"),
                    }
                    print(f"[Kick] {entry['username']}: {entry['text']}")
                    queue.append(entry)
    except Exception as e:
        print("⚠️ Error fetching Kick chat:", e)

def listen_kick():
    channel = kick_api.channel(KICK_CHANNEL)
    if not channel:
        print(f"❌ Kick channel '{KICK_CHANNEL}' not found")
        return

    print(f"✅ Connected to Kick chat: {channel.username}")
    seen_ids, queue = set(), []
    last_sent = 0

    while True:
        get_kick_chat(channel.id, seen_ids, queue)
        if queue and (time.time() - last_sent >= NTFY_DELAY):
            msg = queue.pop(0)
            send_ntfy("Kick", f"{msg['username']}: {msg['text']}")
            last_sent = time.time()
        time.sleep(1)

# ========== YOUTUBE CHAT FETCHER ==========
sent_messages = set()

def get_live_chat_id():
    try:
        search_url = (
            "https://www.googleapis.com/youtube/v3/search"
            f"?part=snippet&channelId={YOUTUBE_CHANNEL_ID}&eventType=live&type=video&key={YOUTUBE_API_KEY}"
        )
        resp = requests.get(search_url).json()
        items = resp.get("items", [])
        if not items:
            return None

        video_id = items[0]["id"]["videoId"]

        videos_url = (
            "https://www.googleapis.com/youtube/v3/videos"
            f"?part=liveStreamingDetails&id={video_id}&key={YOUTUBE_API_KEY}"
        )
        resp2 = requests.get(videos_url).json()
        return resp2["items"][0]["liveStreamingDetails"].get("activeLiveChatId")
    except Exception as e:
        print("❌ Error fetching YouTube chat ID:", e)
        return None

def listen_youtube_chat(live_chat_id):
    print("✅ Connected to YouTube chat!")
    page_token = None
    while True:
        try:
            url = (
                "https://www.googleapis.com/youtube/v3/liveChat/messages"
                f"?liveChatId={live_chat_id}&part=snippet,authorDetails&key={YOUTUBE_API_KEY}"
            )
            if page_token:
                url += f"&pageToken={page_token}"
            resp = requests.get(url).json()

            for item in resp.get("items", []):
                msg_id = item["id"]
                if msg_id in sent_messages:
                    continue
                sent_messages.add(msg_id)

                user = item["authorDetails"]["displayName"]
                msg = item["snippet"]["displayMessage"]
                print(f"[YouTube] {user}: {msg}")
                send_ntfy(f"YouTube - {user}", msg)

            page_token = resp.get("nextPageToken")
            time.sleep(resp.get("pollingIntervalMillis", 5000) / 1000)
        except Exception as e:
            print("❌ Error polling YouTube chat:", e)
            time.sleep(5)

def listen_youtube():
    while True:
        print("🔍 Checking YouTube live...")
        live_chat_id = get_live_chat_id()
        if live_chat_id:
            print("🎥 YouTube stream found, starting chat listener...")
            listen_youtube_chat(live_chat_id)
        else:
            print("⏳ No YouTube stream live. Retrying in 10s...")
            time.sleep(10)

# ========== MAIN ==========
if __name__ == "__main__":
    threads = []
    if KICK_CHANNEL:
        threads.append(threading.Thread(target=listen_kick, daemon=True))
    if YOUTUBE_API_KEY and YOUTUBE_CHANNEL_ID:
        threads.append(threading.Thread(target=listen_youtube, daemon=True))

    for t in threads:
        t.start()
    for t in threads:
        t.join()
