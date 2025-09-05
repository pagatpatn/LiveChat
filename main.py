import os
import time
import requests
import re
import threading
import json
from datetime import datetime, timedelta
from queue import Queue
from kickapi import KickAPI

# =====================================================
# --- Environment Variables ---
# =====================================================
FB_PAGE_ID = os.getenv("FB_PAGE_ID")
FB_PAGE_TOKEN = os.getenv("FB_PAGE_TOKEN")
FB_APP_ID = os.getenv("FB_APP_ID")
FB_APP_SECRET = os.getenv("FB_APP_SECRET")

KICK_CHANNEL = os.getenv("KICK_CHANNEL", "")
KICK_POLL_INTERVAL = float(os.getenv("KICK_POLL_INTERVAL", 5))
KICK_TIME_WINDOW_MINUTES = float(os.getenv("KICK_TIME_WINDOW_MINUTES", 0.1))

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
YOUTUBE_CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID", "")
YOUTUBE_NTFY_DELAY = float(os.getenv("YOUTUBE_NTFY_DELAY", 2))

NTFY_TOPIC = os.getenv("NTFY_TOPIC", "streamchats123")

# per-user last message tracking
kick_last_message_by_user = {}
yt_last_message_by_user = {}
fb_last_message_by_user = {}

# =====================================================
# --- Global Tracking ---
# =====================================================
ntfy_queue = Queue()
last_ntfy_sent = 0

fb_seen_comment_ids = set()
kick_seen_ids = set()
kick_queue = []
yt_sent_messages = set()

kick_api = KickAPI()

# =====================================================
# --- NTFY Worker ---
# =====================================================
MAX_SHORT_MSG_LEN = 123  # NTFY short message limit

def clean_single_line(msg: str) -> str:
    flat = " ".join(msg.replace("\n", " ").replace("\r", " ").split())
    fixed_words = []
    for word in flat.split():
        if len(word) > 30:
            chunks = [word[i:i+30] for i in range(0, len(word), 30)]
            fixed_words.append("\u200B".join(chunks))
        else:
            fixed_words.append(word)
    return " ".join(fixed_words)

def split_message(text, max_len=MAX_SHORT_MSG_LEN):
    """Split text into parts, each not exceeding max_len."""
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
            if now - last_ntfy_sent < 5:
                time.sleep(5 - (now - last_ntfy_sent))

            title = msg_obj.get("title", "Chat")
            user = msg_obj.get("user", "Unknown")
            msg = msg_obj.get("msg", "")
            clean_msg = clean_single_line(msg)
            body = f"{user}: {clean_msg}"

            # Send in chunks if message exceeds MAX_SHORT_MSG_LEN
            if len(body) <= MAX_SHORT_MSG_LEN:
                requests.post(f"https://ntfy.sh/{NTFY_TOPIC}",
                              data=body.encode("utf-8"),
                              headers={"Title": title},
                              timeout=5)
            else:
                parts = split_message(body, MAX_SHORT_MSG_LEN)
                for i, part in enumerate(parts, 1):
                    part_title = f"{title} [{i}/{len(parts)}]" if len(parts) > 1 else title
                    requests.post(f"https://ntfy.sh/{NTFY_TOPIC}",
                                  data=part.encode("utf-8"),
                                  headers={"Title": part_title},
                                  timeout=5)
                    if i < len(parts):
                        time.sleep(3)

            last_ntfy_sent = time.time()

        except Exception as e:
            print("⚠️ Failed to send NTFY:", e)

        ntfy_queue.task_done()


# =====================================================
# --- Facebook ---
# =====================================================
GRAPH = "https://graph.facebook.com/v20.0"

def safe_request(url, params):
    try:
        res = requests.get(url, params=params, timeout=10)
        data = res.json()
        if "error" in data:
            print(f"⚠️ [Facebook] API Error: {json.dumps(data, indent=2)}")
            return {}
        return data
    except Exception as e:
        print(f"❌ [Facebook] Request failed: {e}")
        return {}

def refresh_fb_token():
    global FB_PAGE_TOKEN
    if not FB_PAGE_TOKEN:
        return
    try:
        url = f"{GRAPH}/oauth/access_token"
        params = {
            "grant_type": "fb_exchange_token",
            "client_id": FB_APP_ID,
            "client_secret": FB_APP_SECRET,
            "fb_exchange_token": FB_PAGE_TOKEN,
        }
        res = requests.get(url, params=params).json()
        if "access_token" in res:
            FB_PAGE_TOKEN = res["access_token"]
            print("✅ [Facebook] Page access token refreshed!")
    except Exception as e:
        print("❌ [Facebook] Failed to refresh token:", e)

def get_live_video():
    url = f"{GRAPH}/{FB_PAGE_ID}/videos"
    params = {"fields": "id,description,live_status,created_time","access_token": FB_PAGE_TOKEN,"limit": 10}
    res = safe_request(url, params).get("data", [])
    for v in res:
        if v.get("live_status") == "LIVE":
            print(f"🎯 [Facebook] Live video detected: {v['id']} | {v.get('description', '(no desc)')}")
            return v["id"]
    return None

def fetch_new_comments(video_id):
    url = f"{GRAPH}/{video_id}/comments"
    params = {"fields": "id,from{name},message,created_time","order": "reverse_chronological","access_token": FB_PAGE_TOKEN,"limit": 25}
    res = safe_request(url, params)
    items = res.get("data", [])
    fresh = []
    for c in reversed(items):
        cid = c.get("id")
        if not cid or cid in fb_seen_comment_ids:
            continue
        user = c.get("from", {}).get("name", "Unknown")
        msg = c.get("message", "")
        if fb_last_message_by_user.get(user) == msg:
            continue
        fb_seen_comment_ids.add(cid)
        fb_last_message_by_user[user] = msg
        fresh.append({"from": {"name": user}, "message": msg, "created_time": c.get("created_time")})
    return fresh

def listen_facebook():
    print("📡 [Facebook] Connecting via Graph API polling...")
    last_token_refresh = time.time()
    video_id = None
    while not video_id:
        video_id = get_live_video()
        if not video_id:
            print("🔍 [Facebook] No live video yet, retrying in 5s...")
            time.sleep(5)
    print(f"💬 [Facebook] Listening for comments on video: {video_id}")
    while True:
        if time.time() - last_token_refresh > 3000:
            refresh_fb_token()
            last_token_refresh = time.time()
        comments = fetch_new_comments(video_id)
        for c in comments:
            ts = c.get("created_time", "")
            user = c.get("from", {}).get("name", "Unknown")
            msg = c.get("message", "")
            print(f"[Facebook] [{ts}] {user}: {msg}")
            ntfy_queue.put({"title": "Facebook", "user": user, "msg": msg})
        time.sleep(1)

# =====================================================
# --- Kick ---
# =====================================================
EMOJI_MAP = {"GiftedYAY": "🎉", "ErectDance": "💃"}
emoji_pattern = r"\[emote:(\d+):([^\]]+)\]"

def extract_emoji(text: str) -> str:
    matches = re.findall(emoji_pattern, text)
    for emote_id, emote_name in matches:
        emoji_char = EMOJI_MAP.get(emote_name, f"[{emote_name}]")
        text = text.replace(f"[emote:{emote_id}:{emote_name}]", emoji_char)
    return text

def listen_kick():
    print("📡 [Kick] Connecting...")
    if not KICK_CHANNEL:
        print("⚠️ [Kick] KICK_CHANNEL not set, skipping.")
        return
    channel = None
    while not channel:
        try:
            channel = kick_api.channel(KICK_CHANNEL)
            if not channel:
                print("❌ [Kick] Channel not found, retrying...")
                time.sleep(10)
        except Exception as e:
            print("⚠️ [Kick] Error:", e)
            time.sleep(10)
    print(f"✅ [Kick] Connected to chat: {channel.username}")
    global kick_queue
    while True:
        try:
            past_time = datetime.utcnow() - timedelta(minutes=KICK_TIME_WINDOW_MINUTES)
            chat = kick_api.chat(channel.id, past_time.strftime("%Y-%m-%dT%H:%M:%S.000Z"))
            if chat and getattr(chat, "messages", []):
                for msg in chat.messages:
                    text = extract_emoji(getattr(msg, "text", ""))
                    msg_id = getattr(msg, "id", None)
                    user = msg.sender.username
                    if not msg_id or msg_id in kick_seen_ids:
                        continue
                    kick_seen_ids.add(msg_id)
                    kick_last_message_by_user[user] = text
                    kick_queue.append({"username": user, "text": text})
            if kick_queue:
                m = kick_queue.pop(0)
                print(f"[Kick] {m['username']}: {m['text']}")
                ntfy_queue.put({"title": "Kick", "user": m["username"], "msg": m["text"]})
            time.sleep(KICK_POLL_INTERVAL)
        except Exception as e:
            print("⚠️ [Kick] Listener error, retrying:", e)
            time.sleep(KICK_POLL_INTERVAL)

# =====================================================
# --- YouTube with 2 API Keys ---
# =====================================================
def listen_youtube():
    print("📡 [YouTube] Connecting...")
    if not YOUTUBE_API_KEY:
        print("⚠️ [YouTube] API not set, skipping.")
        return

    global yt_sent_messages, yt_last_message_by_user

    api_keys = [YOUTUBE_API_KEY]
    if os.getenv("YOUTUBE_API_KEY_2"):
        api_keys.append(os.getenv("YOUTUBE_API_KEY_2"))

    current_key_index = 0

    def get_current_key():
        return api_keys[current_key_index]

    def rotate_key():
        nonlocal current_key_index
        current_key_index = (current_key_index + 1) % len(api_keys)
        print(f"🔑 Rotated to YouTube API key {current_key_index+1}/{len(api_keys)}")

    while True:
        try:
            key = get_current_key()
            search_url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&channelId={YOUTUBE_CHANNEL_ID}&eventType=live&type=video&maxResults=1&key={key}"
            resp = requests.get(search_url).json()

            if "error" in resp:
                err = resp["error"]
                reason = err.get("errors", [{}])[0].get("reason", "")
                if err.get("code") == 403 and "quotaExceeded" in reason:
                    print("⚠️ [YouTube] Quota exceeded for current key, rotating...")
                    rotate_key()
                    time.sleep(5)
                    continue
                else:
                    print("⚠️ [YouTube] API error:", err)
                    time.sleep(30)
                    continue

            if not resp.get("items"):
                print("❌ [YouTube] No live stream found, retrying in 30s...")
                time.sleep(30)
                continue

            video_id = resp["items"][0]["id"]["videoId"]

            # Get live chat ID
            details_url = f"https://www.googleapis.com/youtube/v3/videos?part=liveStreamingDetails&id={video_id}&key={get_current_key()}"
            details = requests.get(details_url).json()
            live_chat_id = details["items"][0]["liveStreamingDetails"].get("activeLiveChatId")
            if not live_chat_id:
                print("❌ [YouTube] No active chat found, retrying in 30s...")
                time.sleep(30)
                continue

            print("✅ [YouTube] Connected to live chat!")
            page_token = None

            while True:
                key = get_current_key()
                chat_url = f"https://www.googleapis.com/youtube/v3/liveChat/messages?liveChatId={live_chat_id}&part=snippet,authorDetails&key={key}"
                if page_token:
                    chat_url += f"&pageToken={page_token}"

                data = requests.get(chat_url).json()

                if "error" in data:
                    err = data["error"]
                    reason = err.get("errors", [{}])[0].get("reason", "")
                    if err.get("code") == 403 and "quotaExceeded" in reason:
                        print("⚠️ [YouTube] Quota exceeded for current key, rotating...")
                        rotate_key()
                        time.sleep(5)
                        continue
                    else:
                        print("⚠️ [YouTube] API error:", err)
                        time.sleep(30)
                        continue

                for item in data.get("items", []):
                    msg_id = item["id"]
                    user = item["authorDetails"]["displayName"]
                    msg = item["snippet"]["displayMessage"]
                    if msg_id in yt_sent_messages or yt_last_message_by_user.get(user) == msg:
                        continue
                    yt_sent_messages.add(msg_id)
                    yt_last_message_by_user[user] = msg
                    print(f"[YouTube] {user}: {msg}")
                    ntfy_queue.put({"title": "YouTube", "user": user, "msg": msg})
                    time.sleep(YOUTUBE_NTFY_DELAY)

                page_token = data.get("nextPageToken")
                interval = data.get("pollingIntervalMillis", 5000) / 1000
                time.sleep(interval)

        except Exception as e:
            print("⚠️ [YouTube] Error, retrying in 30s...", e)
            yt_sent_messages = set()
            yt_last_message_by_user = {}
            time.sleep(30)


# =====================================================
# --- Start All Listeners ---
# =====================================================
def start_all_listeners():
    threading.Thread(target=ntfy_worker, daemon=True).start()
    threading.Thread(target=listen_facebook, daemon=True).start()
    threading.Thread(target=listen_kick, daemon=True).start()
    threading.Thread(target=listen_youtube, daemon=True).start()
    print("✅ All listeners started.")

# =====================================================
# --- Entry Point ---
# =====================================================
if __name__ == "__main__":
    start_all_listeners()
    while True:
        time.sleep(60)
