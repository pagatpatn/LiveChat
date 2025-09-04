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

# -----------------------------
# --- Config / Env Variables ---
# -----------------------------
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
def ntfy_worker():
    global last_ntfy_sent
    while True:
        msg_obj = ntfy_queue.get()
        if msg_obj is None:
            break
        try:
            now = time.time()
            if now - last_ntfy_sent < 5:
                time.sleep(5 - (now - last_ntfy_sent))
            title = msg_obj.get("title", "Chat")
            user = msg_obj.get("user", "Unknown")
            msg = msg_obj.get("msg", "")
            body = f"{user}: {msg}"
            requests.post(
                f"https://ntfy.sh/{NTFY_TOPIC}",
                data=body.encode("utf-8"),
                headers={"Title": title},
                timeout=5,
            )
            last_ntfy_sent = time.time()
        except Exception as e:
            print("⚠️ Failed to send NTFY:", e)
        ntfy_queue.task_done()

# -----------------------------
# --- Facebook Webhook Section ---
# -----------------------------
GRAPH = "https://graph.facebook.com/v20.0"
fb_app = Flask(__name__)

def refresh_fb_token():
    global FB_PAGE_TOKEN
    if not FB_PAGE_TOKEN:
        print("⚠️ No FB_PAGE_TOKEN set")
        return
    try:
        # Long-lived token refresh (60 days)
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
            print("✅ Page access token refreshed!")
    except Exception as e:
        print("❌ Failed to refresh token:", e)

@fb_app.route("/webhook", methods=["GET", "POST"])
def facebook_webhook():
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == FB_VERIFY_TOKEN:
            print("✅ Facebook webhook verified successfully!")
            return challenge, 200
        print("❌ Verification failed!")
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
                    print(f"🎬 [Facebook] Live video started: {video_id} | {desc}")
                    comments = value.get("comments", {}).get("data", [])
                    for comment in comments:
                        user = comment.get("from", {}).get("name", "Unknown")
                        msg = comment.get("message", "")
                        print(f"[Facebook] {user}: {msg}")
                        ntfy_queue.put({"title": "Facebook", "user": user, "msg": msg})
        return "OK", 200

def subscribe_facebook_page():
    if not FB_PAGE_TOKEN or not FB_PAGE_ID:
        print("⚠️ FB_PAGE_TOKEN or FB_PAGE_ID not set")
        return
    url = f"{GRAPH}/{FB_PAGE_ID}/subscribed_apps"
    params = {"access_token": FB_PAGE_TOKEN, "subscribed_fields": "live_videos"}
    try:
        res = requests.post(url, params=params).json()
        print("📡 Facebook page webhook subscription result:", res)
    except Exception as e:
        print("❌ Failed to subscribe Facebook webhook:", e)

def listen_facebook():
    print("🔍 [Facebook] Listener thread started")
    refresh_fb_token()
    subscribe_facebook_page()

# -----------------------------
# --- Kick Section ---
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
    print("🔍 [Kick] Listener thread started")
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

        print("🔍 [YouTube] Searching for active livestream...")
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
        print("❌ Error fetching YouTube chat ID:", e)
        return None

def listen_youtube():
    print("🔍 [YouTube] Listener thread started")
    if not YOUTUBE_API_KEY or not YOUTUBE_CHANNEL_ID:
        print("⚠️ YouTube API details not set, skipping YouTube listener")
        return
    global yt_sent_messages
    while True:
        live_chat_id = get_youtube_live_chat_id()
        if not live_chat_id:
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
                    ntfy_queue.put({"title": "YouTube", "user": user, "msg": msg})
                    time.sleep(YOUTUBE_NTFY_DELAY)
                page_token = resp.get("nextPageToken")
                polling_interval = resp.get("pollingIntervalMillis", 5000) / 1000
                time.sleep(polling_interval)
            except Exception as e:
                print("❌ Error in YouTube chat loop:", e)
                yt_sent_messages = set()
                break

# -----------------------------
# --- Main: Run All Listeners ---
# -----------------------------
def start_all_listeners():
    threading.Thread(target=ntfy_worker, daemon=True).start()
    threads = [
        threading.Thread(target=listen_facebook, daemon=True),
        threading.Thread(target=listen_kick, daemon=True),
        threading.Thread(target=listen_youtube, daemon=True)
    ]
    for t in threads:
        t.start()
    print("✅ All background listeners started.")

if __name__ == "__main__":
    start_all_listeners()
    # Run Flask app (Gunicorn will use fb_app)
    fb_app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
