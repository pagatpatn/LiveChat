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

fb_seen_comment_ids = set()
kick_api = KickAPI()
kick_seen_ids = set()
kick_queue = []
yt_sent_messages = set()

# -----------------------------
# --- NTFY Worker ---
# -----------------------------
def clean_single_line(msg: str) -> str:
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
                requests.post(
                    f"https://ntfy.sh/{NTFY_TOPIC}",
                    data=body.encode("utf-8"),
                    headers={"Title": title},
                    timeout=5,
                )
            else:
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
# --- Facebook Section ---
# -----------------------------
GRAPH = "https://graph.facebook.com/v20.0"
fb_app = Flask(__name__)

# Global state for Facebook
fb_current_video_id = None
fb_stop_polling = threading.Event()

@fb_app.route("/webhook", methods=["GET", "POST"])
def facebook_webhook():
    global fb_current_video_id, fb_stop_polling

    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == FB_VERIFY_TOKEN:
            print("✅ [Facebook] Webhook verified successfully!", flush=True)
            return challenge, 200
        print("❌ [Facebook] Webhook verification failed!", flush=True)
        return "Verification failed", 403

    if request.method == "POST":
        data = request.json
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                if change.get("field") == "live_videos":
                    value = change.get("value", {})
                    video_id = value.get("id")
                    desc = value.get("description", "(no description)")
                    print(f"🎬 [Facebook] Live video detected: {video_id} | {desc}", flush=True)

                    # Reset stop flag and update current video
                    fb_stop_polling.clear()
                    fb_current_video_id = video_id

                    # Start polling thread for this live
                    threading.Thread(target=poll_facebook_comments, daemon=True).start()
        return "OK", 200


def poll_facebook_comments():
    """Polls Graph API for comments on the active live video"""
    global fb_current_video_id, fb_stop_polling

    if not fb_current_video_id:
        return

    video_id = fb_current_video_id
    print(f"📡 [Facebook] Connecting to comments for live {video_id}...", flush=True)

    seen_ids = set()
    retries = 0

    while not fb_stop_polling.is_set():
        try:
            url = f"{GRAPH}/{video_id}/live_comments"
            params = {
                "access_token": FB_PAGE_TOKEN,
                "comment_rate": "one_per_two_seconds",
                "fields": "from,message,created_time",
            }
            res = requests.get(url, params=params, timeout=10).json()

            if "error" in res:
                print(f"⚠️ [Facebook] API error: {res['error']}", flush=True)
                retries += 1
                time.sleep(min(10 * retries, 60))
                continue

            comments = res.get("data", [])
            if comments:
                for c in comments:
                    cid = c.get("id")
                    if cid in seen_ids:
                        continue
                    seen_ids.add(cid)
                    user = c.get("from", {}).get("name", "Unknown")
                    msg = c.get("message", "")
                    print(f"[Facebook] {user}: {msg}", flush=True)
                    ntfy_queue.put({"title": "Facebook", "user": user, "msg": msg})
                retries = 0  # reset retries after success
            else:
                time.sleep(3)

        except Exception as e:
            print("❌ [Facebook] Polling error:", e, flush=True)
            retries += 1
            time.sleep(min(10 * retries, 60))


def listen_facebook():
    """Subscribes the app to receive live video webhooks"""
    print("📡 [Facebook] Connecting to webhook subscription...", flush=True)
    retries = 0
    while True:
        try:
            if FB_PAGE_TOKEN and FB_PAGE_ID:
                url = f"{GRAPH}/{FB_PAGE_ID}/subscribed_apps"
                params = {"access_token": FB_PAGE_TOKEN, "subscribed_fields": "live_videos"}
                res = requests.post(url, params=params).json()
                if "success" in res and res["success"]:
                    print("✅ [Facebook] Subscribed to live video events.", flush=True)
                    return
            print("❌ [Facebook] Subscription failed, retrying...", flush=True)
            retries += 1
            time.sleep(min(10 * retries, 60))
        except Exception as e:
            print("⚠️ [Facebook] Subscription error:", e, flush=True)
            retries += 1
            time.sleep(min(10 * retries, 60))


# -----------------------------
# --- Kick Section ---
# -----------------------------
EMOJI_MAP = {"GiftedYAY": "🎉", "ErectDance": "💃"}
emoji_pattern = r"\[emote:(\d+):([^\]]+)\]"

def extract_emoji(text: str) -> str:
    matches = re.findall(emoji_pattern, text)
    for emote_id, emote_name in matches:
        emoji_char = EMOJI_MAP.get(emote_name, f"[{emote_name}]")
        text = text.replace(f"[emote:{emote_id}:{emote_name}]", emoji_char)
    return text

def listen_kick():
    print("📡 [Kick] Connecting...", flush=True)
    if not KICK_CHANNEL:
        print("⚠️ [Kick] KICK_CHANNEL not set, skipping.", flush=True)
        return
    channel = None
    while not channel:
        try:
            channel = kick_api.channel(KICK_CHANNEL)
            if not channel:
                print("❌ [Kick] Channel not found, retrying...", flush=True)
                time.sleep(10)
        except Exception as e:
            print("⚠️ [Kick] Error:", e, flush=True)
            time.sleep(10)
    print(f"✅ [Kick] Connected to chat: {channel.username}", flush=True)
    global kick_queue
    while True:
        try:
            past_time = datetime.utcnow() - timedelta(minutes=KICK_TIME_WINDOW_MINUTES)
            chat = kick_api.chat(channel.id, past_time.strftime("%Y-%m-%dT%H:%M:%S.000Z"))
            if chat and getattr(chat, "messages", []):
                for msg in chat.messages:
                    text = extract_emoji(getattr(msg, "text", ""))
                    msg_id = getattr(msg, "id", f"{msg.sender.username}:{text}")
                    if msg_id not in kick_seen_ids:
                        kick_seen_ids.add(msg_id)
                        kick_queue.append({"username": msg.sender.username, "text": text})
            if kick_queue:
                m = kick_queue.pop(0)
                print(f"[Kick] {m['username']}: {m['text']}", flush=True)
                ntfy_queue.put({"title": "Kick", "user": m["username"], "msg": m["text"]})
            time.sleep(KICK_POLL_INTERVAL)
        except Exception as e:
            print("⚠️ [Kick] Listener error, retrying:", e, flush=True)
            time.sleep(KICK_POLL_INTERVAL)

# -----------------------------
# --- YouTube Section ---
# -----------------------------
def listen_youtube():
    print("📡 [YouTube] Connecting...", flush=True)
    if not YOUTUBE_API_KEY or not YOUTUBE_CHANNEL_ID:
        print("⚠️ [YouTube] API not set, skipping.", flush=True)
        return
    global yt_sent_messages
    while True:
        try:
            search_url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&channelId={YOUTUBE_CHANNEL_ID}&eventType=live&type=video&maxResults=1&key={YOUTUBE_API_KEY}"
            resp = requests.get(search_url).json()
            if not resp.get("items"):
                print("❌ [YouTube] No live stream found, retrying...", flush=True)
                time.sleep(30)
                continue
            video_id = resp["items"][0]["id"]["videoId"]
            url = f"https://www.googleapis.com/youtube/v3/videos?part=liveStreamingDetails&id={video_id}&key={YOUTUBE_API_KEY}"
            details = requests.get(url).json()
            live_chat_id = details["items"][0]["liveStreamingDetails"].get("activeLiveChatId")
            if not live_chat_id:
                print("❌ [YouTube] No active chat found, retrying...", flush=True)
                time.sleep(30)
                continue
            print("✅ [YouTube] Connected to live chat!", flush=True)
            page_token = None
            while True:
                chat_url = f"https://www.googleapis.com/youtube/v3/liveChat/messages?liveChatId={live_chat_id}&part=snippet,authorDetails&key={YOUTUBE_API_KEY}"
                if page_token:
                    chat_url += f"&pageToken={page_token}"
                data = requests.get(chat_url).json()
                for item in data.get("items", []):
                    msg_id = item["id"]
                    if msg_id in yt_sent_messages:
                        continue
                    yt_sent_messages.add(msg_id)
                    user = item["authorDetails"]["displayName"]
                    msg = item["snippet"]["displayMessage"]
                    print(f"[YouTube] {user}: {msg}", flush=True)
                    ntfy_queue.put({"title": "YouTube", "user": user, "msg": msg})
                    time.sleep(YOUTUBE_NTFY_DELAY)
                page_token = data.get("nextPageToken")
                time.sleep(data.get("pollingIntervalMillis", 5000) / 1000)
        except Exception as e:
            print("⚠️ [YouTube] Error, retrying:", e, flush=True)
            yt_sent_messages = set()
            time.sleep(30)

# -----------------------------
# --- Main ---
# -----------------------------
_listeners_started = False
def start_all_listeners():
    global _listeners_started
    if _listeners_started:
        return
    threading.Thread(target=ntfy_worker, daemon=True).start()
    threading.Thread(target=listen_facebook, daemon=True).start()
    threading.Thread(target=listen_kick, daemon=True).start()
    threading.Thread(target=listen_youtube, daemon=True).start()
    _listeners_started = True
    print("✅ All listeners started.", flush=True)

@fb_app.route("/", methods=["GET"])
def home():
    start_all_listeners()
    return "Livechat service is running!", 200

if __name__ == "__main__":
    start_all_listeners()
    port = int(os.getenv("PORT", 8080))
    fb_app.run(host="0.0.0.0", port=port)
