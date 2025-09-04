# -----------------------------
# --- Imports ---
# -----------------------------
from flask import Flask, request
import os
import threading
import time
import requests
import re
from datetime import datetime, timedelta
from queue import Queue
from kickapi import KickAPI

# -----------------------------
# --- Config / Environment ---
# -----------------------------

FB_PAGE_TOKEN = os.getenv("FB_PAGE_TOKEN")
FB_PAGE_ID = os.getenv("FB_PAGE_ID")
FB_VERIFY_TOKEN = os.getenv("FB_VERIFY_TOKEN", "my_verify_token")

KICK_CHANNEL = os.getenv("KICK_CHANNEL", "")
KICK_TIME_WINDOW_MINUTES = 0.1

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
YOUTUBE_CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID", "")
YOUTUBE_NTFY_DELAY = 2

ntfy_queue = Queue()
fb_page_token = None  # will be refreshed automatically

fb_app = Flask(__name__)

# -----------------------------
# --- Refresh Page Token ---
# -----------------------------
def refresh_page_token():
    global fb_page_token
    try:
        # Step 1: exchange short-lived user token for long-lived user token
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

        # Step 2: get page token using long-lived user token
        accounts_url = f"https://graph.facebook.com/v20.0/me/accounts?access_token={long_lived_user_token}"
        res2 = requests.get(accounts_url).json()
        pages = res2.get("data", [])
        for page in pages:
            if page.get("id") == FB_PAGE_ID:
                fb_page_token = page.get("access_token")
                print("✅ Page access token refreshed successfully!")
                return True

        print("❌ Page not found in accounts:", res2)
        return False
    except Exception as e:
        print("❌ Exception refreshing page token:", e)
        return False

# -----------------------------
# --- Subscribe Page to Webhooks ---
# -----------------------------
def subscribe_facebook_page():
    global fb_page_token
    if not fb_page_token or not FB_PAGE_ID:
        print("⚠️ Cannot subscribe webhook: page token or page ID missing")
        return
    url = f"https://graph.facebook.com/v20.0/{FB_PAGE_ID}/subscribed_apps"
    params = {
        "access_token": fb_page_token,
        "subscribed_fields": "live_videos"  # only live videos
    }
    try:
        res = requests.post(url, params=params).json()
        print("📡 Facebook webhook subscription result:", res)
    except Exception as e:
        print("❌ Failed to subscribe webhook:", e)

# -----------------------------
# --- Facebook Webhook Route ---
# -----------------------------
@fb_app.route("/webhook", methods=["GET", "POST"])
def facebook_webhook():
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        print(f"📩 Verification attempt: mode={mode}, token={token}")
        if mode == "subscribe" and token == FB_VERIFY_TOKEN:
            print("✅ Facebook webhook verified successfully!")
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
# --- Initialization ---
# -----------------------------
def start_facebook_webhook():
    success = refresh_page_token()
    if success:
        subscribe_facebook_page()
    else:
        print("⚠️ Could not refresh page token. Webhook subscription skipped.")

# -----------------------------
# --- Kick Listener ---
# -----------------------------
kick_api = KickAPI()
kick_seen_ids = set()
kick_queue = []
emoji_pattern = r"\[emote:(\d+):([^\]]+)\]"
EMOJI_MAP = {"GiftedYAY":"🎉","ErectDance":"💃"}

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

# -----------------------------
# --- YouTube Listener ---
# -----------------------------
yt_sent_messages = set()
last_checked_video_id = None

def get_youtube_live_chat_id():
    global last_checked_video_id
    try:
        if last_checked_video_id:
            videos_url = (
                f"https://www.googleapis.com/youtube/v3/videos"
                f"?part=liveStreamingDetails&id={last_checked_video_id}"
                f"&key={YOUTUBE_API_KEY}"
            )
            resp = requests.get(videos_url).json()
            items = resp.get("items", [])
            if items:
                live_chat_id = items[0]["liveStreamingDetails"].get("activeLiveChatId")
                if live_chat_id:
                    return live_chat_id
            last_checked_video_id = None

        print("🔍 Searching YouTube for live stream...")
        search_url = (
            f"https://www.googleapis.com/youtube/v3/search"
            f"?part=snippet&channelId={YOUTUBE_CHANNEL_ID}&eventType=live&type=video&maxResults=1&key={YOUTUBE_API_KEY}"
        )
        resp = requests.get(search_url).json()
        items = resp.get("items", [])
        if not items:
            return None

        video_id = items[0]["id"]["videoId"]
        last_checked_video_id = video_id
        videos_url = (
            f"https://www.googleapis.com/youtube/v3/videos"
            f"?part=liveStreamingDetails&id={video_id}&key={YOUTUBE_API_KEY}"
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
        live_chat_id = get_youtube_live_chat_id()
        if not live_chat_id:
            print("⏳ No YouTube live stream detected. Retrying in 30s...")
            time.sleep(30)
            continue

        print("✅ Connected to YouTube live chat!")
        page_token = None
        while True:
            try:
                url = (
                    f"https://www.googleapis.com/youtube/v3/liveChat/messages"
                    f"?liveChatId={live_chat_id}&part=snippet,authorDetails&key={YOUTUBE_API_KEY}"
                )
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
# --- Start All Background Listeners ---
# -----------------------------
def start_all_listeners():
    print("🚀 Starting all background listeners...")
    threading.Thread(target=ntfy_worker, daemon=True).start()
    threading.Thread(target=listen_kick, daemon=True).start()
    threading.Thread(target=listen_youtube, daemon=True).start()
    subscribe_facebook_page()
    print("✅ All background listeners started.")

# Start immediately when module is imported (Gunicorn friendly)
threading.Thread(target=start_all_listeners, daemon=True).start()
