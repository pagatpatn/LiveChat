# -----------------------------
# --- Multi-platform Live Chat Bot (Render Ready & Optimized) ---
# -----------------------------
import os
import time
import threading
import requests
import re
from queue import Queue
from datetime import datetime, timedelta
from flask import Flask, request

# Optional Kick API wrapper
from kickapi import KickAPI

# -----------------------------
# --- Config / Env Variables ---
# -----------------------------
# Facebook
FB_APP_ID = os.getenv("FB_APP_ID")
FB_APP_SECRET = os.getenv("FB_APP_SECRET")
FB_USER_LONG_TOKEN = os.getenv("FB_USER_LONG_TOKEN")
FB_PAGE_ID = os.getenv("FB_PAGE_ID")
FB_VERIFY_TOKEN = os.getenv("FB_VERIFY_TOKEN")
FB_PAGE_TOKEN = os.getenv("FB_PAGE_TOKEN")

# Kick
KICK_CHANNEL = os.getenv("KICK_CHANNEL", "")
KICK_POLL_INTERVAL = float(os.getenv("KICK_POLL_INTERVAL", 5))

# YouTube
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
YOUTUBE_CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID", "")
YOUTUBE_NTFY_DELAY = float(os.getenv("YOUTUBE_NTFY_DELAY", 2))

# NTFY
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "streamchats123")
ntfy_queue = Queue()

# -----------------------------
# --- Global Tracking ---
# -----------------------------
# Facebook
active_live_videos = set()
fb_seen_comment_ids = set()

# Kick
kick_api = KickAPI()
kick_seen_ids = set()
kick_queue = []

# YouTube
yt_sent_messages = set()
last_checked_video_id = None

# -----------------------------
# --- Flask App for Webhook ---
# -----------------------------
fb_app = Flask(__name__)

# -----------------------------
# --- NTFY Worker ---
# -----------------------------
def ntfy_worker():
    while True:
        msg_obj = ntfy_queue.get()
        if msg_obj is None:
            break
        try:
            body = f"{msg_obj['user']}: {msg_obj['msg']}"
            title = msg_obj.get("title", "Chat")
            requests.post(
                f"https://ntfy.sh/{NTFY_TOPIC}",
                data=body.encode("utf-8"),
                headers={"Title": title},
                timeout=5,
            )
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
            for change in entry.get("changes", []):
                if change.get("field") == "live_videos":
                    video_id = change.get("value", {}).get("id")
                    if video_id:
                        print(f"🎬 Facebook live video started: {video_id}")
                        active_live_videos.add(video_id)
        return "OK", 200

def poll_fb_comments():
    global fb_seen_comment_ids
    while True:
        for video_id in list(active_live_videos):
            try:
                url = f"https://graph.facebook.com/v20.0/{video_id}/comments"
                params = {
                    "fields": "id,from{{name}},message,created_time",
                    "access_token": FB_PAGE_TOKEN,
                    "order": "chronological",
                    "limit": 25
                }
                res = requests.get(url, params=params).json()
                comments = res.get("data", [])
                for c in comments:
                    cid = c.get("id")
                    if not cid or cid in fb_seen_comment_ids:
                        continue
                    user = c.get("from", {}).get("name", "Unknown")
                    msg = c.get("message", "")
                    print(f"[Facebook] {user}: {msg}")
                    ntfy_queue.put({"title": "Facebook", "user": user, "msg": msg})
                    fb_seen_comment_ids.add(cid)
            except Exception as e:
                print("⚠️ Error fetching Facebook comments:", e)
        time.sleep(2)

def subscribe_facebook_page():
    if not FB_PAGE_TOKEN or not FB_PAGE_ID:
        print("⚠️ Cannot subscribe webhook, missing token or page ID")
        return
    url = f"https://graph.facebook.com/v20.0/{FB_PAGE_ID}/subscribed_apps"
    params = {"access_token": FB_PAGE_TOKEN, "subscribed_fields": "live_videos"}
    try:
        res = requests.post(url, params=params).json()
        print("📡 Facebook webhook subscription result:", res)
    except Exception as e:
        print("❌ Failed to subscribe Facebook webhook:", e)

def refresh_page_token():
    global FB_PAGE_TOKEN
    while True:
        try:
            # Step 1: Refresh long-lived user token
            user_token_url = f"https://graph.facebook.com/v20.0/oauth/access_token"
            params = {
                "grant_type": "fb_exchange_token",
                "client_id": FB_APP_ID,
                "client_secret": FB_APP_SECRET,
                "fb_exchange_token": FB_USER_LONG_TOKEN
            }
            resp = requests.get(user_token_url, params=params).json()
            new_user_token = resp.get("access_token", FB_USER_LONG_TOKEN)

            # Step 2: Generate new Page token
            page_token_url = f"https://graph.facebook.com/v20.0/{FB_PAGE_ID}"
            params = {"fields": "access_token", "access_token": new_user_token}
            page_resp = requests.get(page_token_url, params=params).json()
            FB_PAGE_TOKEN = page_resp.get("access_token", FB_PAGE_TOKEN)
            print("✅ Page access token refreshed!")
        except Exception as e:
            print("⚠️ Failed to refresh page token:", e)
        time.sleep(24 * 60 * 60)  # Refresh once a day

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

def poll_kick_chat():
    if not KICK_CHANNEL:
        return
    channel = kick_api.channel(KICK_CHANNEL)
    if not channel:
        print(f"⚠️ Kick channel '{KICK_CHANNEL}' not found")
        return
    print(f"✅ Connected to Kick channel: {channel.username}")
    global kick_queue, kick_seen_ids
    while True:
        try:
            chat = kick_api.chat(channel.id, (datetime.utcnow() - timedelta(minutes=0.1)).strftime("%Y-%m-%dT%H:%M:%S.000Z"))
            for msg in getattr(chat, "messages", []):
                mid = getattr(msg, "id", None)
                if not mid or mid in kick_seen_ids:
                    continue
                text = extract_emoji(getattr(msg, "text", "No text"))
                user = getattr(msg.sender, "username", "Unknown")
                kick_queue.append({"id": mid, "username": user, "text": text})
                kick_seen_ids.add(mid)
            if kick_queue:
                m = kick_queue.pop(0)
                ntfy_queue.put({"title": "Kick", "user": m["username"], "msg": m["text"]})
        except Exception as e:
            print("⚠️ Error fetching Kick chat:", e)
        time.sleep(KICK_POLL_INTERVAL)

# -----------------------------
# --- YouTube Listener ---
# -----------------------------
yt_sent_messages = set()
last_checked_video_id = None

def get_youtube_live_chat_id():
    global last_checked_video_id
    try:
        if last_checked_video_id:
            resp = requests.get(
                f"https://www.googleapis.com/youtube/v3/videos?part=liveStreamingDetails&id={last_checked_video_id}&key={YOUTUBE_API_KEY}"
            ).json()
            items = resp.get("items", [])
            if items:
                live_chat_id = items[0]["liveStreamingDetails"].get("activeLiveChatId")
                if live_chat_id:
                    return live_chat_id
            last_checked_video_id = None

        search_resp = requests.get(
            f"https://www.googleapis.com/youtube/v3/search?part=snippet&channelId={YOUTUBE_CHANNEL_ID}&eventType=live&type=video&maxResults=1&key={YOUTUBE_API_KEY}"
        ).json()
        items = search_resp.get("items", [])
        if not items:
            return None
        video_id = items[0]["id"]["videoId"]
        last_checked_video_id = video_id
        details_resp = requests.get(
            f"https://www.googleapis.com/youtube/v3/videos?part=liveStreamingDetails&id={video_id}&key={YOUTUBE_API_KEY}"
        ).json()
        return details_resp["items"][0]["liveStreamingDetails"].get("activeLiveChatId")
    except Exception as e:
        print("❌ Error fetching YouTube chat ID:", e)
        return None

def poll_youtube_chat():
    global yt_sent_messages
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
                if "error" in resp:
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
                print("❌ YouTube chat loop error:", e)
                yt_sent_messages = set()
                break

# -----------------------------
# --- Start All Listeners ---
# -----------------------------
def start_all_listeners():
    threading.Thread(target=ntfy_worker, daemon=True).start()
    threading.Thread(target=poll_fb_comments, daemon=True).start()
    threading.Thread(target=refresh_page_token, daemon=True).start()
    threading.Thread(target=poll_kick_chat, daemon=True).start()
    threading.Thread(target=poll_youtube_chat, daemon=True).start()
    subscribe_facebook_page()
    print("✅ All background listeners started.")

# -----------------------------
# --- Flask Entry Point ---
# -----------------------------
if __name__ == "__main__":
    start_all_listeners()
    port = int(os.environ.get("PORT", 5000))
    fb_app.run(host="0.0.0.0", port=port)
