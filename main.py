import os
import time
import requests
import re
import threading
from datetime import datetime, timedelta
from kickapi import KickAPI

# --- Config (from env vars for Railway) ---
KICK_CHANNEL = os.getenv("KICK_CHANNEL", "")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
YOUTUBE_CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID", "")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "streamchats123")

# Kick polling
KICK_POLL_INTERVAL = 5
KICK_TIME_WINDOW_MINUTES = 0.1
KICK_DELAY = 5  # delay between NTFY sends for Kick

# YouTube polling
YOUTUBE_NTFY_DELAY = 2

# --- Kick setup ---
kick_api = KickAPI()
kick_seen_ids = set()
kick_queue = []
kick_last_sent = 0

# --- Emoji Mapping ---
EMOJI_MAP = {
    "GiftedYAY": "🎉",
    "ErectDance": "💃",
}
emoji_pattern = r"\[emote:(\d+):([^\]]+)\]"

def extract_emoji(text: str) -> str:
    matches = re.findall(emoji_pattern, text)
    for match in matches:
        emote_id, emote_name = match
        emoji_char = EMOJI_MAP.get(emote_name, f"[{emote_name}]")
        text = text.replace(f"[emote:{emote_id}:{emote_name}]", emoji_char)
    return text

def send_ntfy(title: str, msg: str):
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=msg.encode("utf-8"),
            headers={"Title": title},
            timeout=5,
        )
    except Exception as e:
        print("⚠️ Failed to send NTFY:", e)

# --- Kick Chat ---
def get_kick_chat(channel_id: int):
    try:
        past_time = datetime.utcnow() - timedelta(minutes=KICK_TIME_WINDOW_MINUTES)
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
    except Exception as e:
        print("⚠️ Error fetching Kick chat:", e)
        return []

def listen_kick():
    if not KICK_CHANNEL:
        print("⚠️ KICK_CHANNEL not set, skipping Kick listener")
        return

    channel = kick_api.channel(KICK_CHANNEL)
    if not channel:
        print(f"⚠️ Kick channel '{KICK_CHANNEL}' not found")
        return

    print(f"✅ Connected to Kick chat for channel: {channel.username}")
    global kick_last_sent

    while True:
        messages = get_kick_chat(channel.id)
        for msg in messages:
            if msg["id"] not in kick_seen_ids:
                kick_seen_ids.add(msg["id"])
                kick_queue.append(msg)
                # log immediately
                print(f"[Kick {msg['timestamp']}] {msg['username']}: {msg['text']}")

        if kick_queue and (time.time() - kick_last_sent >= KICK_DELAY):
            msg = kick_queue.pop(0)
            send_ntfy("Kick", f"{msg['username']}: {msg['text']}")
            kick_last_sent = time.time()

        time.sleep(1)

# --- YouTube Chat ---
youtube_sent_messages = set()

def get_youtube_live_chat_id():
    try:
        search_url = (
            f"https://www.googleapis.com/youtube/v3/search"
            f"?part=snippet"
            f"&channelId={YOUTUBE_CHANNEL_ID}"
            f"&eventType=live"
            f"&type=video"
            f"&key={YOUTUBE_API_KEY}"
        )
        resp = requests.get(search_url).json()
        items = resp.get("items", [])
        if not items:
            return None
        video_id = items[0]["id"]["videoId"]

        videos_url = (
            f"https://www.googleapis.com/youtube/v3/videos"
            f"?part=liveStreamingDetails"
            f"&id={video_id}"
            f"&key={YOUTUBE_API_KEY}"
        )
        resp2 = requests.get(videos_url).json()
        live_chat_id = resp2["items"][0]["liveStreamingDetails"].get("activeLiveChatId")
        return live_chat_id
    except Exception as e:
        print("❌ Error fetching YouTube chat ID:", e)
        return None

def listen_youtube():
    if not YOUTUBE_API_KEY or not YOUTUBE_CHANNEL_ID:
        print("⚠️ YouTube API details not set, skipping YouTube listener")
        return

    while True:
        print("🔍 Checking YouTube for live stream...")
        live_chat_id = get_youtube_live_chat_id()
        if not live_chat_id:
            print("⏳ No YouTube live stream detected. Retrying in 10s...")
            time.sleep(10)
            continue

        print("✅ Connected to YouTube live chat!")
        page_token = None

        while True:
            try:
                url = (
                    f"https://www.googleapis.com/youtube/v3/liveChat/messages"
                    f"?liveChatId={live_chat_id}"
                    f"&part=snippet,authorDetails"
                    f"&key={YOUTUBE_API_KEY}"
                )
                if page_token:
                    url += f"&pageToken={page_token}"

                resp = requests.get(url).json()
                for item in resp.get("items", []):
                    msg_id = item["id"]
                    if msg_id in youtube_sent_messages:
                        continue
                    youtube_sent_messages.add(msg_id)

                    user = item["authorDetails"]["displayName"]
                    msg = item["snippet"]["displayMessage"]
                    print(f"[YouTube] {user}: {msg}")

                    send_ntfy("YouTube", f"{user}: {msg}")
                    time.sleep(YOUTUBE_NTFY_DELAY)

                page_token = resp.get("nextPageToken")
                polling_interval = resp.get("pollingIntervalMillis", 5000) / 1000
                time.sleep(polling_interval)

            except Exception as e:
                print("❌ Error in YouTube chat loop:", e)
                break

# --- Run both in parallel ---
if __name__ == "__main__":
    threads = []
    t1 = threading.Thread(target=listen_kick, daemon=True)
    t2 = threading.Thread(target=listen_youtube, daemon=True)
    threads.extend([t1, t2])
    for t in threads:
        t.start()
    for t in threads:
        t.join()
