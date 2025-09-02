import os
import time
import requests
import json

GRAPH = "https://graph.facebook.com/v20.0"

# ✅ Environment variables
PAGE_TOKEN = os.getenv("FB_PAGE_TOKEN")
PAGE_ID = os.getenv("FB_PAGE_ID")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "facebook_chat")  # set this in Railway

if not PAGE_TOKEN or not PAGE_ID:
    raise ValueError("❌ Missing env vars: FB_PAGE_TOKEN, FB_PAGE_ID")

# Track seen comments and last msg per user to prevent spam
seen_comment_ids = set()
last_message_by_user = {}


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


def get_live_video(page_id, page_token):
    url = f"{GRAPH}/{page_id}/videos"
    params = {
        "fields": "id,description,live_status,created_time",
        "access_token": page_token,
        "limit": 10,
    }
    res = safe_request(url, params)
    data = res.get("data", [])
    if not data:
        return None

    for v in data:
        if v.get("live_status") == "LIVE":
            return v["id"]
    return None


def fetch_new_comments(video_id, page_token):
    url = f"{GRAPH}/{video_id}/comments"
    params = {
        "fields": "id,from{name},message,created_time",
        "order": "reverse_chronological",
        "access_token": page_token,
        "limit": 25,
    }
    res = safe_request(url, params)
    items = res.get("data", [])
    fresh = []

    for c in items:
        cid = c.get("id")
        if not cid or cid in seen_comment_ids:
            continue

        user = c.get("from", {}).get("name", "Unknown")
        msg = c.get("message", "")

        # 🚫 Prevent spam: only first message until different
        if last_message_by_user.get(user) == msg:
            continue

        seen_comment_ids.add(cid)
        last_message_by_user[user] = msg
        fresh.append(c)

    fresh.reverse()
    return fresh


def send_ntfy(msg_obj):
    """Send single message to ntfy"""
    try:
        user = msg_obj.get("from", {}).get("name", "Unknown")
        msg = msg_obj.get("message", "")
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=f"{user}: {msg}".encode("utf-8"),
            headers={"Title": "Facebook"},
            timeout=5,
        )
    except Exception:
        pass  # fail silently to avoid breaking loop


def main():
    print("🚀 Facebook Live Chat Fetcher started")

    video_id = None
    while not video_id:
        print("\n📺 Checking for live video…")
        video_id = get_live_video(PAGE_ID, PAGE_TOKEN)
        if not video_id:
            time.sleep(5)

    print(f"🎯 Active live video ID: {video_id}")
    print("💬 Listening for new comments…")

    while True:
        new_comments = fetch_new_comments(video_id, PAGE_TOKEN)
        for c in new_comments:
            ts = c.get("created_time", "")
            user = c.get("from", {}).get("name", "Unknown")
            msg = c.get("message", "")
            print(f"[{ts}] {user}: {msg}")  # real-time console log
            send_ntfy(c)  # send immediately to ntfy

        time.sleep(1)  # 🔄 1s polling for near real-time

if __name__ == "__main__":
    main()
