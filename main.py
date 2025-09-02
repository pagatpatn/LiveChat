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

# Track seen comments and last msg per user
seen_comment_ids = set()
last_message_by_user = {}

# Queue for ntfy push
pending_ntfy_msgs = []


def safe_request(url, params):
    try:
        res = requests.get(url, params=params, timeout=15)
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
        print("⏳ No videos data found yet.")
        return None

    for v in data:
        if v.get("live_status") == "LIVE":
            print(f"✅ Live video found: {v['id']} | {v.get('description','(no desc)')}")
            return v["id"]

    print("❌ No active LIVE video right now.")
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
    if not items:
        return []

    fresh = []
    for c in items:
        cid = c.get("id")
        if not cid or cid in seen_comment_ids:
            continue

        user = c.get("from", {}).get("name", "Unknown")
        msg = c.get("message", "")

        # 🚫 Prevent spam
        if last_message_by_user.get(user) == msg:
            continue

        seen_comment_ids.add(cid)
        last_message_by_user[user] = msg
        fresh.append(c)

    fresh.reverse()
    return fresh


def send_ntfy(messages):
    """Send batched messages to ntfy"""
    if not messages:
        return
    text = "\n".join(f"{m['from']['name']}: {m.get('message','')}" for m in messages)

    try:
        res = requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=text.encode("utf-8"),
            headers={"Title": "Facebook"},
            timeout=10,
        )
        if res.status_code == 200:
            print(f"📤 Sent {len(messages)} messages to ntfy")
        else:
            print(f"⚠️ Failed to send to ntfy: {res.status_code} {res.text}")
    except Exception as e:
        print(f"❌ ntfy send failed: {e}")


def main():
    print("🚀 Facebook Live Chat Fetcher started")

    video_id = None
    while not video_id:
        print("\n📺 Checking for live video…")
        video_id = get_live_video(PAGE_ID, PAGE_TOKEN)
        if not video_id:
            time.sleep(10)

    print(f"🎯 Active live video ID: {video_id}")
    print("💬 Listening for new comments…")

    last_ntfy_push = time.time()

    while True:
        new_comments = fetch_new_comments(video_id, PAGE_TOKEN)
        if new_comments:
            for c in new_comments:
                user = c.get("from", {}).get("name", "Unknown")
                msg = c.get("message", "")
                ts = c.get("created_time", "")
                print(f"[{ts}] {user}: {msg}")
                pending_ntfy_msgs.append(c)

        # ⏱ Push to ntfy every 5s
        if time.time() - last_ntfy_push >= 5 and pending_ntfy_msgs:
            send_ntfy(pending_ntfy_msgs)
            pending_ntfy_msgs.clear()
            last_ntfy_push = time.time()

        time.sleep(2)  # keep 2s polling for real-time


if __name__ == "__main__":
    main()
