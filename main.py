import os
import time
import requests
import re
import threading
import json
from datetime import datetime, timedelta
from queue import Queue
from kickapi import KickAPI
import sseclient

# -----------------------------
# --- Config / Env Variables ---
# -----------------------------
# Facebook
FB_PAGE_TOKEN = os.getenv("FB_PAGE_TOKEN")
FB_PAGE_ID = os.getenv("FB_PAGE_ID")
# Kick
KICK_CHANNEL = os.getenv("KICK_CHANNEL", "")
KICK_TIME_WINDOW_MINUTES = 0.1
# YouTube
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
YOUTUBE_CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID", "")
# NTFY
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "streamchats123")

# -----------------------------
# --- Global Tracking ---
# -----------------------------
ntfy_queue = Queue()
MAX_BANNER_CHARS = 250  # banner-friendly chunk size
GLOBAL_DELAY = 5        # 5 seconds delay for all messages
MAX_QUEUE_LENGTH = 10   # max messages in ntfy_queue to avoid flood

# Facebook
fb_seen_comment_ids = set()
fb_last_message_by_user = {}
fb_last_comment_time = None

# Kick
kick_api = KickAPI()
kick_seen_ids = set()
kick_queue = []

# YouTube
yt_sent_messages = set()
last_checked_video_id = None

# -----------------------------
# --- NTFY Helper Functions ---
# -----------------------------
def safe_ntfy_put(msg_obj):
    """Add message to queue if not exceeding MAX_QUEUE_LENGTH"""
    if ntfy_queue.qsize() >= MAX_QUEUE_LENGTH:
        print("⚠️ NTFY queue full, skipping message:", msg_obj.get("msg", "")[:50])
        return
    ntfy_queue.put(msg_obj)

def send_ntfy_chunked(title, user, msg):
    chunks = [msg[i:i+MAX_BANNER_CHARS] for i in range(0, len(msg), MAX_BANNER_CHARS)]
    total = len(chunks)
    for idx, chunk in enumerate(chunks, 1):
        body = f"[{idx}/{total}] {chunk}" if total > 1 else f"{user}: {chunk}"
        try:
            requests.post(
                f"https://ntfy.sh/{NTFY_TOPIC}",
                data=body.encode("utf-8"),
                headers={"Title": title},
                timeout=5
            )
            print(f"✉️ Sent chunk {idx}/{total}" if total > 1 else "✉️ Sent full message")
        except Exception as e:
            print("⚠️ Failed to send chunk:", e)
        time.sleep(GLOBAL_DELAY)

def ntfy_worker():
    while True:
        msg_obj = ntfy_queue.get()
        if msg_obj is None:
            break
        try:
            title = msg_obj.get("title", "Chat")
            user = msg_obj.get("user", "Unknown")
            msg = msg_obj.get("msg", "")
            send_ntfy_chunked(title, user, msg)
        except Exception as e:
            print("⚠️ Failed to send NTFY:", e)
        ntfy_queue.task_done()

# -----------------------------
# --- Facebook Listener (SSE Fixed) ---
# -----------------------------
def listen_facebook():
    if not FB_PAGE_TOKEN or not FB_PAGE_ID:
        print("⚠️ FB_PAGE_TOKEN or FB_PAGE_ID not set, skipping Facebook listener")
        return

    while True:
        video_id = get_fb_live_video_id(FB_PAGE_ID, FB_PAGE_TOKEN)
        if not video_id:
            print("⏳ [Facebook] No active live video, retrying in 10s...")
            time.sleep(10)
            continue

        print(f"🎥 [Facebook] Live video detected! Video ID: {video_id}")

        # Build URL with raw braces for Facebook SSE
        url = (
            f"https://streaming-graph.facebook.com/v20.0/{video_id}/live_comments"
            f"?access_token={FB_PAGE_TOKEN}"
            f"&comment_rate=one_per_five_seconds"
            f"&fields=from{{name,id}},message"
        )

        try:
            print(f"📡 [Facebook] Connecting to SSE stream for video {video_id}...")
            res = requests.get(url, stream=True, timeout=60)
            res.raise_for_status()
            client = sseclient.SSEClient(res)
            print("✅ [Facebook] Successfully connected to live_comments SSE stream!")

            for event in client.events():
                if not event.data or event.data == "null":
                    continue
                try:
                    data = json.loads(event.data)
                    user = data.get("from", {}).get("name") or data.get("from", {}).get("id") or "Unknown"
                    msg = data.get("message", "")
                    if msg.strip():
                        print(f"[Facebook] {user}: {msg}")
                        ntfy_queue.put({"title": "Facebook", "user": user, "msg": msg})
                        # Enforce global 5s delay for each message
                        time.sleep(GLOBAL_DELAY)
                except Exception as inner_e:
                    print("⚠️ Error parsing FB SSE event:", inner_e)

        except Exception as e:
            print("❌ [Facebook] SSE connection error:", e)

        print("⏳ [Facebook] Reconnecting in 5 seconds...")
        time.sleep(5)


# -----------------------------
# --- Kick Listener ---
# -----------------------------
EMOJI_MAP = {"GiftedYAY":"🎉","ErectDance":"💃"}
emoji_pattern = r"\[emote:(\d+):([^\]]+)\]"

def extract_emoji(text: str) -> str:
    matches = re.findall(emoji_pattern, text)
    for match in matches:
        emote_id, emote_name = match
        emoji_char = EMOJI_MAP.get(emote_name, f"[{emote_name}]")
        text = text.replace(f"[emote:{emote_id}:{emote_name}]", emoji_char)
    return text

def get_kick_chat(channel_id: int):
    try:
        past_time = datetime.utcnow() - timedelta(minutes=KICK_TIME_WINDOW_MINUTES)
        formatted_time = past_time.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        chat = kick_api.chat(channel_id, formatted_time)
        messages = []
        if chat and hasattr(chat, "messages") and chat.messages:
            for msg in chat.messages:
                message_text = extract_emoji(msg.text if hasattr(msg, "text") else "No text")
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
    global kick_queue
    while True:
        messages = get_kick_chat(channel.id)
        for msg in messages:
            if msg["id"] not in kick_seen_ids:
                kick_seen_ids.add(msg["id"])
                kick_queue.append(msg)
                print(f"[Kick {msg['timestamp']}] {msg['username']}: {msg['text']}")
        if kick_queue:
            msg = kick_queue.pop(0)
            safe_ntfy_put({"title": "Kick", "user": msg["username"], "msg": msg["text"]})
        time.sleep(1)

# -----------------------------
# --- YouTube Listener ---
# -----------------------------
def get_youtube_live_chat_id():
    global last_checked_video_id
    try:
        if last_checked_video_id:
            url = f"https://www.googleapis.com/youtube/v3/videos?part=liveStreamingDetails&id={last_checked_video_id}&key={YOUTUBE_API_KEY}"
            resp = requests.get(url).json()
            items = resp.get("items", [])
            if items:
                live_chat_id = items[0]["liveStreamingDetails"].get("activeLiveChatId")
                if live_chat_id:
                    return live_chat_id
            last_checked_video_id = None
        search_url = (
            f"https://www.googleapis.com/youtube/v3/search?part=snippet"
            f"&channelId={YOUTUBE_CHANNEL_ID}&eventType=live&type=video&maxResults=1&key={YOUTUBE_API_KEY}"
        )
        resp = requests.get(search_url).json()
        items = resp.get("items", [])
        if not items:
            return None
        video_id = items[0]["id"]["videoId"]
        last_checked_video_id = video_id
        videos_url = f"https://www.googleapis.com/youtube/v3/videos?part=liveStreamingDetails&id={video_id}&key={YOUTUBE_API_KEY}"
        resp2 = requests.get(videos_url).json()
        return resp2["items"][0]["liveStreamingDetails"].get("activeLiveChatId")
    except Exception as e:
        print("❌ Error fetching YouTube chat ID:", e)
        return None

def listen_youtube():
    global yt_sent_messages
    if not YOUTUBE_API_KEY or not YOUTUBE_CHANNEL_ID:
        print("⚠️ YouTube API details not set, skipping YouTube listener")
        return
    while True:
        live_chat_id = get_youtube_live_chat_id()
        if not live_chat_id:
            print("⏳ No YouTube live stream detected. Retrying in 30s...")
            time.sleep(30)
            continue
        print("✅ Connected to YouTube live chat!")
        page_token = None
        while True:
            try:
                url = f"https://www.googleapis.com/youtube/v3/liveChat/messages?liveChatId={live_chat_id}&part=snippet,authorDetails&key={YOUTUBE_API_KEY}"
                if page_token:
                    url += f"&pageToken={page_token}"
                resp = requests.get(url).json()
                if "error" in resp and resp["error"]["errors"][0]["reason"] == "liveChatEnded":
                    print("⚠️ YouTube live chat ended, resetting state...")
                    yt_sent_messages = set()
                    break
                for item in resp.get("items", []):
                    msg_id = item["id"]
                    if msg_id in yt_sent_messages:
                        continue
                    yt_sent_messages.add(msg_id)
                    user = item["authorDetails"]["displayName"]
                    msg = item["snippet"]["displayMessage"]
                    print(f"[YouTube] {user}: {msg}")
                    safe_ntfy_put({"title": "YouTube", "user": user, "msg": msg})
                page_token = resp.get("nextPageToken")
                polling_interval = resp.get("pollingIntervalMillis", 5000) / 1000
                time.sleep(polling_interval)
            except Exception as e:
                print("❌ Error in YouTube chat loop:", e)
                yt_sent_messages = set()
                break

# -----------------------------
# --- Main: Run All ---
# -----------------------------
if __name__ == "__main__":
    threading.Thread(target=ntfy_worker, daemon=True).start()
    threads = [
        threading.Thread(target=listen_facebook, daemon=True),
        threading.Thread(target=listen_kick, daemon=True),
        threading.Thread(target=listen_youtube, daemon=True)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
