import os
import time
import threading
import requests
import re
import json
from datetime import datetime, timedelta
from queue import Queue
from flask import Flask, request

# -----------------------------
# --- Config / Env Variables ---
# -----------------------------
FB_APP_ID = os.getenv("FB_APP_ID")
FB_APP_SECRET = os.getenv("FB_APP_SECRET")
FB_PAGE_ID = os.getenv("FB_PAGE_ID")
FB_VERIFY_TOKEN = os.getenv("FB_VERIFY_TOKEN")
FB_PAGE_TOKEN = os.getenv("FB_PAGE_TOKEN")  # permanent token, refreshable

KICK_CHANNEL = os.getenv("KICK_CHANNEL", "")
KICK_POLL_INTERVAL = float(os.getenv("KICK_POLL_INTERVAL", 5))
KICK_TIME_WINDOW_MINUTES = float(os.getenv("KICK_TIME_WINDOW_MINUTES", 0.1))

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
YOUTUBE_CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID", "")
YOUTUBE_NTFY_DELAY = float(os.getenv("YOUTUBE_NTFY_DELAY", 2))

NTFY_TOPIC = os.getenv("NTFY_TOPIC", "streamchats123")

# -----------------------------
# --- Global Tracking ---
# -----------------------------
ntfy_queue = Queue()

# Facebook
fb_seen_comment_ids = set()
fb_last_message_by_user = {}
fb_last_comment_time = None

# Kick
kick_seen_ids = set()

# YouTube
yt_sent_messages = set()
yt_next_page_token = None
last_checked_video_id = None
yt_last_poll_time = 0

# -----------------------------
# --- Flask App ---
# -----------------------------
fb_app = Flask(__name__)

# -----------------------------
# --- NTFY Worker ---
# -----------------------------
def ntfy_worker():
    last_ntfy_sent = 0
    while True:
        msg_obj = ntfy_queue.get()
        if msg_obj is None:
            break
        try:
            now = time.time()
            if now - last_ntfy_sent < 1:
                time.sleep(1 - (now - last_ntfy_sent))
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
        return "OK", 200

# -----------------------------
# --- Facebook Graph API Polling ---
# -----------------------------
GRAPH = "https://graph.facebook.com/v20.0"

def refresh_fb_page_token():
    global FB_PAGE_TOKEN
    try:
        url = f"https://graph.facebook.com/v20.0/oauth/access_token"
        params = {
            "grant_type": "fb_exchange_token",
            "client_id": FB_APP_ID,
            "client_secret": FB_APP_SECRET,
            "fb_exchange_token": FB_PAGE_TOKEN,
        }
        resp = requests.get(url, params=params).json()
        new_token = resp.get("access_token")
        if new_token:
            FB_PAGE_TOKEN = new_token
            print("✅ Facebook page access token refreshed!")
        else:
            print("⚠️ Failed to refresh token:", resp)
    except Exception as e:
        print("⚠️ Error refreshing token:", e)

def safe_request(url, params):
    try:
        res = requests.get(url, params=params, timeout=10)
        data = res.json()
        if "error" in data:
            print(f"⚠️ API Error: {json.dumps(data, indent=2)}")
            return {}
        return data
    except Exception as e:
        print(f"❌ Request failed: {e}")
        return {}

def get_fb_live_video():
    url = f"{GRAPH}/{FB_PAGE_ID}/videos"
    params = {
        "fields": "id,description,live_status,created_time",
        "access_token": FB_PAGE_TOKEN,
        "limit": 10,
    }
    res = safe_request(url, params)
    for v in res.get("data", []):
        if v.get("live_status") == "LIVE":
            return v["id"]
    return None

def fetch_fb_new_comments(video_id):
    global fb_last_comment_time
    fresh = []
    url = f"{GRAPH}/{video_id}/comments"
    params = {
        "fields": "id,from{id,name},message,created_time",
        "order": "chronological",
        "access_token": FB_PAGE_TOKEN,
        "limit": 25,
    }
    if fb_last_comment_time:
        params["since"] = fb_last_comment_time

    while True:
        res = safe_request(url, params)
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

    if fresh:
        fb_last_comment_time = items[-1]["created_time"]
    return fresh

def listen_facebook_comments():
    if not FB_PAGE_TOKEN or not FB_PAGE_ID:
        print("⚠️ FB_PAGE_TOKEN or FB_PAGE_ID not set")
        return
    video_id = None
    while not video_id:
        video_id = get_fb_live_video()
        if not video_id:
            time.sleep(5)
    print(f"🎯 [Facebook] Live video ID: {video_id}")

    refresh_timer = time.time()
    while True:
        if time.time() - refresh_timer > 3600:
            refresh_fb_page_token()
            refresh_timer = time.time()
        new_comments = fetch_fb_new_comments(video_id)
        for c in new_comments:
            print(f"[Facebook] {c['user']}: {c['msg']}")
            ntfy_queue.put(c)
        time.sleep(1)

# -----------------------------
# --- Kick Listener ---
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

def listen_kick():
    try:
        from kickapi import KickAPI
        kick_api = KickAPI()
        if not KICK_CHANNEL:
            print("⚠️ KICK_CHANNEL not set")
            return
        channel = kick_api.channel(KICK_CHANNEL)
        if not channel:
            print(f"⚠️ Kick channel '{KICK_CHANNEL}' not found")
            return
        print(f"✅ Connected to Kick channel: {channel.username}")

        while True:
            past_time = datetime.utcnow() - timedelta(minutes=KICK_TIME_WINDOW_MINUTES)
            chat = kick_api.chat(channel.id, past_time.strftime("%Y-%m-%dT%H:%M:%S.000Z"))
            if chat and hasattr(chat, "messages"):
                for msg in chat.messages:
                    mid = getattr(msg, "id", f"{msg.sender.username}:{msg.text}")
                    if mid in kick_seen_ids:
                        continue
                    kick_seen_ids.add(mid)
                    text = extract_emoji(getattr(msg, "text", "No text"))
                    ntfy_queue.put({"title": "Kick", "user": msg.sender.username, "msg": text})
            time.sleep(KICK_POLL_INTERVAL)
    except Exception as e:
        print("⚠️ Kick listener error:", e)

# -----------------------------
# --- YouTube Listener (Quota Efficient) ---
# -----------------------------
def get_youtube_live_chat_id():
    global last_checked_video_id
    try:
        if last_checked_video_id:
            resp = requests.get(
                f"https://www.googleapis.com/youtube/v3/videos?part=liveStreamingDetails&id={last_checked_video_id}&key={YOUTUBE_API_KEY}"
            ).json()
            items = resp.get("items", [])
            if items and "activeLiveChatId" in items[0]["liveStreamingDetails"]:
                return items[0]["liveStreamingDetails"]["activeLiveChatId"]
            last_checked_video_id = None

        resp = requests.get(
            f"https://www.googleapis.com/youtube/v3/search?part=snippet&channelId={YOUTUBE_CHANNEL_ID}&eventType=live&type=video&maxResults=1&key={YOUTUBE_API_KEY}"
        ).json()
        items = resp.get("items", [])
        if not items:
            return None

        video_id = items[0]["id"]["videoId"]
        last_checked_video_id = video_id

        resp2 = requests.get(
            f"https://www.googleapis.com/youtube/v3/videos?part=liveStreamingDetails&id={video_id}&key={YOUTUBE_API_KEY}"
        ).json()
        return resp2["items"][0]["liveStreamingDetails"].get("activeLiveChatId")
    except Exception as e:
        print("❌ YouTube chat ID error:", e)
        return None

def listen_youtube():
    global yt_next_page_token, yt_last_poll_time
    if not YOUTUBE_API_KEY or not YOUTUBE_CHANNEL_ID:
        print("⚠️ YouTube API details not set")
        return
    while True:
        live_chat_id = get_youtube_live_chat_id()
        if not live_chat_id:
            time.sleep(30)
            continue

        params = {"liveChatId": live_chat_id, "part": "snippet,authorDetails", "key": YOUTUBE_API_KEY}
        if yt_next_page_token:
            params["pageToken"] = yt_next_page_token
        try:
            resp = requests.get(
                "https://www.googleapis.com/youtube/v3/liveChat/messages",
                params=params
            ).json()
            yt_next_page_token = resp.get("nextPageToken")
            polling_interval = float(resp.get("pollingIntervalMillis", 2000)) / 1000
            for item in resp.get("items", []):
                msg_id = item["id"]
                if msg_id in yt_sent_messages:
                    continue
                yt_sent_messages.add(msg_id)
                user = item["authorDetails"]["displayName"]
                msg = item["snippet"]["displayMessage"]
                ntfy_queue.put({"title": "YouTube", "user": user, "msg": msg})
            time.sleep(polling_interval)
        except Exception as e:
            print("⚠️ YouTube listener error:", e)
            time.sleep(YOUTUBE_NTFY_DELAY)

# -----------------------------
# --- Start All Listeners ---
# -----------------------------
def start_all_listeners():
    threading.Thread(target=ntfy_worker, daemon=True).start()
    threading.Thread(target=listen_facebook_comments, daemon=True).start()
    threading.Thread(target=listen_kick, daemon=True).start()
    threading.Thread(target=listen_youtube, daemon=True).start()
    print("✅ All background listeners started.")

# -----------------------------
# --- Initialize immediately ---
# -----------------------------
start_all_listeners()

# -----------------------------
# --- Run Flask app (Webhook only) ---
# -----------------------------
if __name__ == "__main__":
    fb_app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
