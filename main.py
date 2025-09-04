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
FB_PAGE_TOKEN = os.getenv("FB_PAGE_TOKEN", "")
FB_PAGE_ID = os.getenv("FB_PAGE_ID", "")
FB_VERIFY_TOKEN = os.getenv("FB_VERIFY_TOKEN", "my_verify_token")  # your custom verify token

# Kick
KICK_CHANNEL = os.getenv("KICK_CHANNEL", "")
try:
    KICK_POLL_INTERVAL = float(os.getenv("KICK_POLL_INTERVAL") or 5)
except ValueError:
    KICK_POLL_INTERVAL = 5

try:
    KICK_TIME_WINDOW_MINUTES = float(os.getenv("KICK_TIME_WINDOW_MINUTES") or 0.1)
except ValueError:
    KICK_TIME_WINDOW_MINUTES = 0.1

KICK_DELAY = 5

# YouTube
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
YOUTUBE_CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID", "")
try:
    YOUTUBE_NTFY_DELAY = float(os.getenv("YOUTUBE_NTFY_DELAY") or 2)
except ValueError:
    YOUTUBE_NTFY_DELAY = 2

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
# --- Facebook Webhook (Render Ready) ---
# -----------------------------
fb_app = Flask(__name__)

@fb_app.route("/webhook", methods=["GET", "POST"])
def facebook_webhook():
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == FB_VERIFY_TOKEN:
            print("✅ Facebook webhook verified!")
            return challenge, 200
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

                    # Poll comments after webhook triggers live video
                    comments = fetch_fb_new_comments(video_id, FB_PAGE_TOKEN)
                    for c in comments:
                        ntfy_queue.put(c)
        return "OK", 200

def fetch_fb_new_comments(video_id, page_token):
    global fb_last_comment_time
    fresh = []
    url = f"https://graph.facebook.com/v20.0/{video_id}/comments"
    params = {
        "fields": "id,from{id,name},message,created_time",
        "order": "chronological",
        "access_token": page_token,
        "limit": 25,
    }
    if fb_last_comment_time:
        params["since"] = fb_last_comment_time

    while True:
        try:
            res = requests.get(url, params=params, timeout=10).json()
            items = res.get("data", [])
            if not items:
                break
            for c in items:
                cid = c.get("id")
                if not cid or cid in fb_seen_comment_ids:
                    continue
                user_info = c.get("from", {})
                user = user_info.get("name") or user_info.get("id") or "Unknown"
                msg = c.get("message", "")
                if fb_last_message_by_user.get(user) == msg:
                    continue
                fb_seen_comment_ids.add(cid)
                fb_last_message_by_user[user] = msg
                fresh.append({"title": "Facebook", "user": user, "msg": msg})
            paging = res.get("paging", {})
            next_page = paging.get("next")
            if not next_page:
                break
            url = next_page
            params = {}
        except Exception as e:
            print("❌ Failed fetching FB comments:", e)
            break

    if fresh:
        fb_last_comment_time = items[-1]["created_time"]
    return fresh

def subscribe_facebook_page():
    if not FB_PAGE_TOKEN or not FB_PAGE_ID:
        print("⚠️ FB_PAGE_TOKEN or FB_PAGE_ID not set")
        return
    url = f"https://graph.facebook.com/v20.0/{FB_PAGE_ID}/subscribed_apps"
    params = {"access_token": FB_PAGE_TOKEN, "subscribed_fields": "live_videos"}
    try:
        res = requests.post(url, params=params).json()
        print("📡 Facebook webhook subscription result:", res)
    except Exception as e:
        print("❌ Failed to subscribe FB webhook:", e)

# -----------------------------
# --- Kick Functions ---
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
                message_text = msg.text if hasattr(msg, "text") else "No text"
                message_text = extract_emoji(message_text)
                messages.append({
                    "id": getattr(msg, "id", f"{getattr(msg.sender,'username','Unknown')}:{message_text}"),
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
        print("⚠️ KICK_CHANNEL not set")
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
                ntfy_queue.put({"title": "Kick", "user": msg["username"], "msg": msg["text"]})
        time.sleep(KICK_POLL_INTERVAL)

# -----------------------------
# --- YouTube Functions ---
# -----------------------------
def get_youtube_live_chat_id():
    global last_checked_video_id
    try:
        if last_checked_video_id:
            videos_url = f"https://www.googleapis.com/youtube/v3/videos?part=liveStreamingDetails&id={last_checked_video_id}&key={YOUTUBE_API_KEY}"
            resp = requests.get(videos_url).json()
            items = resp.get("items", [])
            if items:
                live_chat_id = items[0]["liveStreamingDetails"].get("activeLiveChatId")
                if live_chat_id:
                    return live_chat_id
            last_checked_video_id = None

        search_url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&channelId={YOUTUBE_CHANNEL_ID}&eventType=live&type=video&maxResults=1&key={YOUTUBE_API_KEY}"
        resp = requests.get(search_url).json()
        items = resp.get("items", [])
        if not items:
            return None
        video_id = items[0]["id"]["videoId"]
        last_checked_video_id = video_id
        videos_url = f"https://www.googleapis.com/youtube/v3/videos?part=liveStreamingDetails&id={video_id}&key={YOUTUBE_API_KEY}"
        resp2 = requests.get(videos_url).json()
        live_chat_id = resp2["items"][0]["liveStreamingDetails"].get("activeLiveChatId")
        return live_chat_id
    except Exception as e:
        print("❌ Error fetching YouTube chat ID:", e)
        return None

def listen_youtube():
    global yt_sent_messages
    if not YOUTUBE_API_KEY or not YOUTUBE_CHANNEL_ID:
        print("⚠️ YouTube API details not set")
        return

    while True:
        live_chat_id = get_youtube_live_chat_id()
        if not live_chat_id:
            time.sleep(30)
            continue

        page_token = None
        while True:
            try:
                url = f"https://www.googleapis.com/youtube/v3/liveChat/messages?liveChatId={live_chat_id}&part=snippet,authorDetails&key={YOUTUBE_API_KEY}"
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
                    ntfy_queue.put({"title": "YouTube", "user": user, "msg": msg})
                    time.sleep(YOUTUBE_NTFY_DELAY)

                page_token = resp.get("nextPageToken")
                polling_interval = resp.get("pollingIntervalMillis", 5000) / 1000
                time.sleep(polling_interval)
            except Exception as e:
                print("❌ YouTube listener error:", e)
                yt_sent_messages = set()
                break

# -----------------------------
# --- Main: Start All Listeners ---
# -----------------------------
def start_all_listeners():
    threading.Thread(target=ntfy_worker, daemon=True).start()
    threads = [
        threading.Thread(target=listen_kick, daemon=True),
        threading.Thread(target=listen_youtube, daemon=True),
    ]
    for t in threads:
        t.start()
    subscribe_facebook_page()
    print("✅ All background listeners started.")

if __name__ == "__main__":
    start_all_listeners()
    fb_app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
