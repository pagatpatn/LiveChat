import os
import time
import requests
import re
import threading
import json
from datetime import datetime, timedelta
from queue import Queue
from flask import Flask, request, abort
from kickapi import KickAPI

# =====================================================
# === CHANGES SECTION (edit only this part if needed) ==
# =====================================================
MAX_SHORT_MSG_LEN = 95       # max length for "short" NTFY messages
WORD_BREAK_LEN = 30          # long words broken every X chars
SPLIT_MSG_LEN = 2000         # chunk size for splitting long messages
NTFY_PART_DELAY = 3          # seconds delay between parts
NTFY_COOLDOWN = 5            # min seconds between notifications

# Facebook
FB_PAGE_ID = os.getenv("FB_PAGE_ID")
FB_PAGE_TOKEN = os.getenv("FB_PAGE_TOKEN")
FB_VERIFY_TOKEN = os.getenv("FB_VERIFY_TOKEN")

# Kick
KICK_CHANNEL = os.getenv("KICK_CHANNEL", "")
KICK_POLL_INTERVAL = float(os.getenv("KICK_POLL_INTERVAL", 5))
KICK_TIME_WINDOW_MINUTES = float(os.getenv("KICK_TIME_WINDOW_MINUTES", 0.1))

# YouTube
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
YOUTUBE_CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID", "")
YOUTUBE_NTFY_DELAY = float(os.getenv("YOUTUBE_NTFY_DELAY", 2))

# NTFY
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "streamchats123")

# =====================================================
# === END OF CHANGES SECTION ==========================
# =====================================================

# -----------------------------
# --- Global Tracking ---
# -----------------------------
ntfy_queue = Queue()
last_ntfy_sent = 0

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
# --- NTFY Worker ---
# -----------------------------
def clean_single_line(msg: str) -> str:
    """Force message into a single line and prevent ntfy from wrapping long words"""
    flat = " ".join(msg.replace("\n", " ").replace("\r", " ").split())
    fixed_words = []
    for word in flat.split():
        if len(word) > WORD_BREAK_LEN:
            chunks = [word[i:i+WORD_BREAK_LEN] for i in range(0, len(word), WORD_BREAK_LEN)]
            fixed_words.append("\u200B".join(chunks))
        else:
            fixed_words.append(word)
    return " ".join(fixed_words)

def split_message(text, max_len=SPLIT_MSG_LEN):
    """Split long text into chunks with word boundaries"""
    parts = []
    while len(text) > max_len:
        split_at = text.rfind(" ", 0, max_len)
        if split_at == -1:
            split_at = max_len
        parts.append(text[:split_at].strip())
        text = text[split_at:].strip()
    if text:
        parts.append(text)
    return parts

def ntfy_worker():
    global last_ntfy_sent
    while True:
        msg_obj = ntfy_queue.get()
        if msg_obj is None:
            break
        try:
            now = time.time()
            if now - last_ntfy_sent < NTFY_COOLDOWN:
                time.sleep(NTFY_COOLDOWN - (now - last_ntfy_sent))

            title = msg_obj.get("title", "Chat")
            user = msg_obj.get("user", "Unknown")
            msg = msg_obj.get("msg", "")

            clean_msg = clean_single_line(msg)
            body = f"{user}: {clean_msg}"

            if len(body) <= MAX_SHORT_MSG_LEN:
                # short message
                requests.post(
                    f"https://ntfy.sh/{NTFY_TOPIC}",
                    data=body.encode("utf-8"),
                    headers={"Title": title},
                    timeout=5,
                )
            else:
                # long message → split into parts
                parts = split_message(body, SPLIT_MSG_LEN)
                for i, part in enumerate(parts, 1):
                    part_title = f"{title} [{i}/{len(parts)}]"
                    requests.post(
                        f"https://ntfy.sh/{NTFY_TOPIC}",
                        data=part.encode("utf-8"),
                        headers={"Title": part_title},
                        timeout=5,
                    )
                    if i < len(parts):
                        time.sleep(NTFY_PART_DELAY)

            last_ntfy_sent = time.time()

        except Exception as e:
            print("⚠️ Failed to send NTFY:", e, flush=True)
        ntfy_queue.task_done()

# -----------------------------
# --- Facebook Webhook Section ---
# -----------------------------
GRAPH = "https://graph.facebook.com/v20.0"
fb_app = Flask(__name__)

def refresh_fb_token():
    global FB_PAGE_TOKEN
    if not FB_PAGE_TOKEN:
        print("⚠️ No FB_PAGE_TOKEN set", flush=True)
        return
    try:
        url = f"https://graph.facebook.com/v20.0/oauth/access_token"
        params = {
            "grant_type": "fb_exchange_token",
            "client_id": os.getenv("FB_APP_ID"),
            "client_secret": os.getenv("FB_APP_SECRET"),
            "fb_exchange_token": FB_PAGE_TOKEN,
        }
        res = requests.get(url, params=params).json()
        if "access_token" in res:
            FB_PAGE_TOKEN = res["access_token"]
            print("✅ Page access token refreshed!", flush=True)
    except Exception as e:
        print("❌ Failed to refresh token:", e, flush=True)

@fb_app.route("/webhook", methods=["GET", "POST"])
def facebook_webhook():
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == FB_VERIFY_TOKEN:
            print("✅ Facebook webhook verified successfully!", flush=True)
            return challenge, 200
        print("❌ Verification failed!", flush=True)
        return "Verification failed", 403

    if request.method == "POST":
        data = request.json
        for entry in data.get("entry", []):
            changes = entry.get("changes", [])
            for change in changes:
                field = change.get("field")
                value = change.get("value", {})
                if field == "live_videos":
                    video_id = value.get("id")
                    desc = value.get("description", "(no description)")
                    print(f"🎬 [Facebook] Live video started: {video_id} | {desc}", flush=True)
                    comments = value.get("comments", {}).get("data", [])
                    for comment in comments:
                        user = comment.get("from", {}).get("name", "Unknown")
                        msg = comment.get("message", "")
                        print(f"[Facebook] {user}: {msg}", flush=True)
                        ntfy_queue.put({"title": "Facebook", "user": user, "msg": msg})
        return "OK", 200

def subscribe_facebook_page():
    if not FB_PAGE_TOKEN or not FB_PAGE_ID:
        print("⚠️ FB_PAGE_TOKEN or FB_PAGE_ID not set", flush=True)
        return
    url = f"{GRAPH}/{FB_PAGE_ID}/subscribed_apps"
    params = {"access_token": FB_PAGE_TOKEN, "subscribed_fields": "live_videos"}
    try:
        res = requests.post(url, params=params).json()
        print("📡 Facebook page webhook subscription result:", res, flush=True)
    except Exception as e:
        print("❌ Failed to subscribe Facebook webhook:", e, flush=True)

def listen_facebook():
    print("🔍 [Facebook] Listener thread started", flush=True)
    refresh_fb_token()
    subscribe_facebook_page()

# -----------------------------
# --- Kick Section ---
# -----------------------------
EMOJI_MAP = {"GiftedYAY": "🎉", "ErectDance": "💃"}
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
        print("⚠️ Error fetching Kick chat:", e, flush=True)
        return []

def listen_kick():
    print("🔍 [Kick] Listener thread started", flush=True)
    if not KICK_CHANNEL:
        print("⚠️ KICK_CHANNEL not set, skipping Kick listener", flush=True)
        return
    channel = kick_api.channel(KICK_CHANNEL)
    if not channel:
        print(f"⚠️ Kick channel '{KICK_CHANNEL}' not found", flush=True)
        return
    print(f"✅ Connected to Kick chat for channel: {channel.username}", flush=True)
    global kick_queue
    while True:
        messages = get_kick_chat(channel.id)
        for msg in messages:
            if msg["id"] not in kick_seen_ids:
                kick_seen_ids.add(msg["id"])
                kick_queue.append(msg)
                print(f"[Kick {msg['timestamp']}] {msg['username']}: {msg['text']}", flush=True)
        if kick_queue:
            msg = kick_queue.pop(0)
            ntfy_queue.put({"title": "Kick", "user": msg["username"], "msg": msg["text"]})
        time.sleep(KICK_POLL_INTERVAL)

# -----------------------------
# --- YouTube Section (Quota Efficient) ---
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

        print("🔍 [YouTube] Searching for active livestream...", flush=True)
        search_url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&channelId={YOUTUBE_CHANNEL_ID}&eventType=live&type=video&maxResults=1&key={YOUTUBE_API_KEY}"
        resp = requests.get(search_url).json()
        items = resp.get("items", [])
        if not items:
            return None
        video_id = items[0]["id"]["videoId"]
        last_checked_video_id = video_id
        url = f"https://www.googleapis.com/youtube/v3/videos?part=liveStreamingDetails&id={video_id}&key={YOUTUBE_API_KEY}"
        resp2 = requests.get(url).json()
        live_chat_id = resp2["items"][0]["liveStreamingDetails"].get("activeLiveChatId")
        return live_chat_id
    except Exception as e:
        print("❌ Error fetching YouTube chat ID:", e, flush=True)
        return None

def listen_youtube():
    print("🔍 [YouTube] Listener thread started", flush=True)
    if not YOUTUBE_API_KEY or not YOUTUBE_CHANNEL_ID:
        print("⚠️ YouTube API details not set, skipping YouTube listener", flush=True)
        return
    global yt_sent_messages
    while True:
        live_chat_id = get_youtube_live_chat_id()
        if not live_chat_id:
            time.sleep(30)
            continue
        print("✅ Connected to YouTube live chat!", flush=True)
        page_token = None
        while True:
            try:
                url = f"https://www.googleapis.com/youtube/v3/liveChat/messages?liveChatId={live_chat_id}&part=snippet,authorDetails&key={YOUTUBE_API_KEY}"
                if page_token:
                    url += f"&pageToken={page_token}"
                resp = requests.get(url).json()
                if "error" in resp and resp["error"]["errors"][0]["reason"] == "liveChatEnded":
                    print("⚠️ YouTube live chat ended, resetting state...", flush=True)
                    yt_sent_messages = set()
                    break
                for item in resp.get("items", []):
                    msg_id = item["id"]
                    if msg_id in yt_sent_messages:
                        continue
                    yt_sent_messages.add(msg_id)
                    user = item["authorDetails"]["displayName"]
                    msg = item["snippet"]["displayMessage"]
                    print(f"[YouTube] {user}: {msg}", flush=True)
                    ntfy_queue.put({"title": "YouTube", "user": user, "msg": msg})
                    time.sleep(YOUTUBE_NTFY_DELAY)
                page_token = resp.get("nextPageToken")
                polling_interval = resp.get("pollingIntervalMillis", 5000) / 1000
                time.sleep(polling_interval)
            except Exception as e:
                print("❌ Error in YouTube chat loop:", e, flush=True)
                yt_sent_messages = set()
                break

# -----------------------------
# --- Main: Run All Listeners ---
# -----------------------------
_listeners_started = False
_listeners_lock = threading.Lock()

def start_all_listeners():
    global _listeners_started
    with _listeners_lock:
        if _listeners_started:
            return
        threading.Thread(target=ntfy_worker, daemon=True).start()
        threads = [
            threading.Thread(target=listen_facebook, daemon=True),
            threading.Thread(target=listen_kick, daemon=True),
            threading.Thread(target=listen_youtube, daemon=True)
        ]
        for t in threads:
            t.start()
        _listeners_started = True
        print("✅ All background listeners started.", flush=True)

@fb_app.before_first_request
def _start_listeners_on_request():
    start_all_listeners()

@fb_app.route("/", methods=["GET"])
def home():
    return "Livechat service is running!", 200

@fb_app.route("/favicon.ico")
def favicon():
    return "", 204

if __name__ == "__main__":
    start_all_listeners()
    port = int(os.getenv("PORT", 8080))
    fb_app.run(host="0.0.0.0", port=port)
