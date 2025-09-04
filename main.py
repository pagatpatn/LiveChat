import os
import time
import requests
import re
import threading
import json
from datetime import datetime, timedelta
from queue import Queue
from kickapi import KickAPI

# -----------------------------
# --- Config / Env Variables ---
# -----------------------------
# Facebook
FB_PAGE_TOKEN = os.getenv("FB_PAGE_TOKEN")
FB_PAGE_ID = os.getenv("FB_PAGE_ID")
# Kick
KICK_CHANNEL = os.getenv("KICK_CHANNEL", "")
KICK_POLL_INTERVAL = 5
KICK_TIME_WINDOW_MINUTES = 0.1
KICK_DELAY = 5
# YouTube
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
YOUTUBE_CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID", "")
YOUTUBE_NTFY_DELAY = 2
# NTFY
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "streamchats123")

# -----------------------------
# --- Global Tracking ---
# -----------------------------
# Central NTFY Queue
ntfy_queue = Queue()
last_ntfy_sent = 0  # last time a message was sent (throttle)

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

# -----------------------------
# --- NTFY Worker (Single) ---
# -----------------------------
def ntfy_worker():
    global last_ntfy_sent
    while True:
        msg_obj = ntfy_queue.get()
        if msg_obj is None:
            break
        try:
            # Throttle NTFY sends to 5s
            now = time.time()
            if now - last_ntfy_sent < 5:
                time.sleep(5 - (now - last_ntfy_sent))

            title = msg_obj.get("title", "Chat")   # source: YouTube / Kick / Facebook
            user = msg_obj.get("user", "Unknown")
            msg = msg_obj.get("msg", "")

            # ✅ Put full chat text in body, NOT title
            body = f"{user}: {msg}"

            requests.post(
                f"https://ntfy.sh/{NTFY_TOPIC}",
                data=body.encode("utf-8"),
                headers={"Title": title},  # keep this short so it won’t truncate
                timeout=5,
            )
            last_ntfy_sent = time.time()
        except Exception as e:
            print("⚠️ Failed to send NTFY:", e)
        ntfy_queue.task_done()


# -----------------------------
# --- Facebook (SSE Version with Live Video Detection + Confirmations) ---
# -----------------------------
import sseclient

GRAPH_API = "https://graph.facebook.com/v20.0"
GRAPH_STREAM = "https://streaming-graph.facebook.com/v20.0"

def get_fb_live_video_id(page_id, page_token):
    """Find the currently active LIVE video for the Page."""
    url = f"{GRAPH_API}/{page_id}/videos"
    params = {
        "fields": "id,live_status",
        "access_token": page_token,
        "limit": 5,
    }
    try:
        res = requests.get(url, params=params, timeout=10).json()
        for v in res.get("data", []):
            if v.get("live_status") == "LIVE":
                return v["id"]
    except Exception as e:
        print("⚠️ Error fetching FB live video:", e)
    return None

def listen_facebook():
    """Listen to live comments via SSE with auto-reconnect."""
    if not FB_PAGE_TOKEN or not FB_PAGE_ID:
        print("⚠️ FB_PAGE_TOKEN or FB_PAGE_ID not set, skipping Facebook listener")
        return

    while True:
        video_id = get_fb_live_video_id(FB_PAGE_ID, FB_PAGE_TOKEN)
        if not video_id:
            print("⏳ [Facebook] No active live video found, retrying in 10s...")
            time.sleep(10)
            continue

        print(f"🎥 [Facebook] Live video detected! Video ID: {video_id}")

        url = f"{GRAPH_STREAM}/{video_id}/live_comments"
        params = {
            "access_token": FB_PAGE_TOKEN,
            "comment_rate": "one_per_two_seconds",
            "fields": "from{name,id},message",
        }

        try:
            print(f"📡 [Facebook] Connecting to SSE stream for video {video_id}...")
            res = requests.get(url, params=params, stream=True, timeout=60)
            res.raise_for_status()
            print("✅ [Facebook] Successfully connected to live_comments SSE stream!")

            client = sseclient.SSEClient(res)
            for event in client.events():
                if not event.data or event.data == "null":
                    continue
                try:
                    data = json.loads(event.data)
                    user = (
                        data.get("from", {}).get("name")
                        or data.get("from", {}).get("id")
                        or "Unknown"
                    )
                    msg = data.get("message", "")
                    if msg.strip():
                        print(f"[Facebook] {user}: {msg}")
                        ntfy_queue.put({"title": "Facebook", "user": user, "msg": msg})
                except Exception as inner_e:
                    print("⚠️ Error parsing FB SSE event:", inner_e)

        except Exception as e:
            print("❌ [Facebook] SSE connection error:", e)

        print("⏳ [Facebook] Reconnecting in 5 seconds...")
        time.sleep(5)

# -----------------------------
# --- Kick Functions ---
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
            ntfy_queue.put({"title": "Kick", "user": msg["username"], "msg": msg["text"]})
        time.sleep(1)

# ------------------ YouTube Section ------------------ #
yt_sent_messages = set()
last_checked_video_id = None

def get_youtube_live_chat_id():
    """Get liveChatId for an active YouTube livestream with minimal quota usage."""
    global last_checked_video_id
    try:
        # ✅ Reuse previous video_id if still live
        if last_checked_video_id:
            videos_url = (
                f"https://www.googleapis.com/youtube/v3/videos"
                f"?part=liveStreamingDetails"
                f"&id={last_checked_video_id}"
                f"&key={YOUTUBE_API_KEY}"
            )
            resp = requests.get(videos_url).json()
            items = resp.get("items", [])
            if items:
                live_chat_id = items[0]["liveStreamingDetails"].get("activeLiveChatId")
                if live_chat_id:
                    return live_chat_id  # still live, reuse
            # If no longer live, reset cache
            last_checked_video_id = None

        # 🔍 Only search if no cached video_id
        print("🔍 Running YouTube search for active livestream...")
        search_url = (
            f"https://www.googleapis.com/youtube/v3/search"
            f"?part=snippet"
            f"&channelId={YOUTUBE_CHANNEL_ID}"
            f"&eventType=live"
            f"&type=video"
            f"&maxResults=1"
            f"&key={YOUTUBE_API_KEY}"
        )
        resp = requests.get(search_url).json()
        items = resp.get("items", [])
        if not items:
            return None

        video_id = items[0]["id"]["videoId"]
        last_checked_video_id = video_id  # cache

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
    global yt_sent_messages
    if not YOUTUBE_API_KEY or not YOUTUBE_CHANNEL_ID:
        print("⚠️ YouTube API details not set, skipping YouTube listener")
        return

    while True:
        print("🔍 Checking YouTube for live stream...")
        live_chat_id = get_youtube_live_chat_id()
        if not live_chat_id:
            print("⏳ No YouTube live stream detected. Retrying in 30s...")
            time.sleep(30)  # reduce quota usage
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

                # livestream ended → reset & break back to search loop
                if "error" in resp and resp["error"]["errors"][0]["reason"] == "liveChatEnded":
                    print("⚠️ YouTube live chat ended, resetting state...")
                    yt_sent_messages = set()   # 🔄 reset for next stream
                    break

                for item in resp.get("items", []):
                    msg_id = item["id"]
                    if msg_id in yt_sent_messages:
                        continue
                    yt_sent_messages.add(msg_id)

                    user = item["authorDetails"]["displayName"]
                    msg = item["snippet"]["displayMessage"]
                    print(f"[YouTube] {user}: {msg}")
                    # ✅ Use central NTFY queue (same as FB & Kick)
                    ntfy_queue.put({"title": "YouTube", "user": user, "msg": msg})
                    time.sleep(YOUTUBE_NTFY_DELAY)

                page_token = resp.get("nextPageToken")
                polling_interval = resp.get("pollingIntervalMillis", 5000) / 1000
                time.sleep(polling_interval)

            except Exception as e:
                print("❌ Error in YouTube chat loop:", e)
                yt_sent_messages = set()  # 🔄 also reset on crash
                break

# -----------------------------
# --- Main: Run All ---
# -----------------------------
if __name__ == "__main__":
    # Start NTFY worker
    threading.Thread(target=ntfy_worker, daemon=True).start()

    # Start listeners (Facebook via SSE, Kick, YouTube)
    threads = [
        threading.Thread(target=listen_facebook, daemon=True),
        threading.Thread(target=listen_kick, daemon=True),
        threading.Thread(target=listen_youtube, daemon=True)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
