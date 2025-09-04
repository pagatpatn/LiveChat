import os
import time
import requests
import re
import threading
import json
from datetime import datetime, timedelta
from queue import Queue
from flask import Flask, request
from kickapi import KickAPI

# -----------------------------
# --- Config / Environment ---
# -----------------------------
# Facebook
FB_APP_ID = os.getenv("FB_APP_ID")
FB_APP_SECRET = os.getenv("FB_APP_SECRET")
FB_USER_TOKEN = os.getenv("FB_USER_TOKEN")  # short-lived user token
FB_PAGE_ID = os.getenv("FB_PAGE_ID")
FB_VERIFY_TOKEN = os.getenv("FB_VERIFY_TOKEN", "my_verify_token")

# Kick
KICK_CHANNEL = os.getenv("KICK_CHANNEL", "")
KICK_POLL_INTERVAL = 5
KICK_TIME_WINDOW_MINUTES = 0.1

# YouTube
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
YOUTUBE_CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID", "")
YOUTUBE_NTFY_DELAY = 2

# NTFY
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "streamchats123")

# -----------------------------
# --- Global Tracking ---
# -----------------------------
ntfy_queue = Queue()
last_ntfy_sent = 0

# Facebook
fb_page_token = None

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
# --- Facebook Webhook ---
# -----------------------------
fb_app = Flask(__name__)

def refresh_page_token():
    global fb_page_token
    try:
        # 1️⃣ Get long-lived user token
        exchange_url = (
            f"https://graph.facebook.com/v20.0/oauth/access_token"
            f"?grant_type=fb_exchange_token"
            f"&client_id={FB_APP_ID}"
            f"&client_secret={FB_APP_SECRET}"
            f"&fb_exchange_token={FB_USER_TOKEN}"
        )
        resp = requests.get(exchange_url).json()
        long_lived_user_token = resp.get("access_token")
        if not long_lived_user_token:
            print("❌ Failed to get long-lived user token:", resp)
            return False

        # 2️⃣ Get page token
        accounts_url = f"https://graph.facebook.com/v20.0/me/accounts?access_token={long_lived_user_token}"
        res2 = requests.get(accounts_url).json()
        pages = res2.get("data", [])
        for page in pages:
            if page.get("id") == FB_PAGE_ID:
                fb_page_token = page.get("access_token")
                print("✅ Page access token refreshed!")
                return True
        print("❌ Page not found in accounts:", res2)
        return False
    except Exception as e:
        print("❌ Exception refreshing page token:", e)
        return False

def subscribe_facebook_page():
    global fb_page_token
    if not fb_page_token or not FB_PAGE_ID:
        print("⚠️ Cannot subscribe webhook: page token or page ID missing")
        return
    url = f"https://graph.facebook.com/v20.0/{FB_PAGE_ID}/subscribed_apps"
    params = {"access_token": fb_page_token, "subscribed_fields": "live_videos"}
    try:
        res = requests.post(url, params=params).json()
        print("📡 Facebook webhook subscription result:", res)
    except Exception as e:
        print("❌ Failed to subscribe webhook:", e)

@fb_app.route("/webhook", methods=["GET", "POST"])
def facebook_webhook():
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        print(f"📩 Verification attempt: mode={mode}, token={token}")
        if mode == "subscribe" and token == FB_VERIFY_TOKEN:
            print("✅ Facebook webhook verified!")
            return challenge, 200
        print("❌ Verification failed!")
        return "Verification failed", 403

    if request.method == "POST":
        data = request.json
        print(f"📩 Incoming POST from Facebook: {data}")
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
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
                message_text = getattr(msg, "text", "No text")
                message_text = extract_emoji(message_text)
                messages.append({
                    "id": getattr(msg, "id", f"{msg.sender.username}:{message_text}"),
                    "username": getattr(msg.sender, "username", "Unknown"),
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

# -----------------------------
# --- YouTube Listener ---
# -----------------------------
def get_youtube_live_chat_id():
    global last_checked_video_id
    try:
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
                    return live_chat_id
            last_checked_video_id = None

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
        last_checked_video_id = video_id

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
        print("⚠️ YouTube API not set, skipping listener")
        return
    while True:
        live_chat_id = get_youtube_live_chat_id()
        if not live_chat_id:
            print("⏳ No YouTube live stream, retrying in 30s...")
            time.sleep(30)
            continue
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
                if "error" in resp and resp["error"]["errors"][0]["reason"] == "liveChatEnded":
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
# --- Start All Listeners ---
# -----------------------------
def start_all_listeners():
    print("🚀 Starting all background listeners...")
    threading.Thread(target=ntfy_worker, daemon=True).start()
    threading.Thread(target=listen_kick, daemon=True).start()
    threading.Thread(target=listen_youtube, daemon=True).start()
    success = refresh_page_token()
    if success:
        subscribe_facebook_page()
    print("✅ All background listeners started.")

# Start listeners in background
threading.Thread(target=start_all_listeners, daemon=True).start()
