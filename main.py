import os
import time
import requests
import threading
from datetime import datetime

# --- Config (Railway ENV) ---
FB_PAGE_ID = os.getenv("FB_PAGE_ID", "")
FB_ACCESS_TOKEN = os.getenv("FB_ACCESS_TOKEN", "")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "streamchats123")

# Polling
FB_POLL_INTERVAL = 5  # seconds

# Track seen comments
fb_seen_ids = set()

def send_ntfy(title: str, msg: str):
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=msg.encode("utf-8"),
            headers={"Title": title},
            timeout=5,
        )
    except Exception as e:
        print("⚠️ Failed to send NTFY:", e)

def get_live_video_id():
    """Find current live video for the FB page."""
    url = (
        f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/videos"
        f"?fields=id,live_status,title"
        f"&access_token={FB_ACCESS_TOKEN}"
    )
    resp = requests.get(url).json()
    if "error" in resp:
        print("⚠️ API Error:", resp)
        return None

    for video in resp.get("data", []):
        if video.get("live_status") == "LIVE":
            return video["id"]
    return None

def fetch_new_comments(video_id: str):
    """Fetch only new comments from a live video."""
    url = (
        f"https://graph.facebook.com/v19.0/{video_id}/comments"
        f"?order=reverse_chronological"
        f"&filter=stream"
        f"&fields=from{{name}},message,created_time,id"
        f"&access_token={FB_ACCESS_TOKEN}"
    )
    resp = requests.get(url).json()
    if "error" in resp:
        print("⚠️ API Error fetching comments:", resp)
        return []

    new_comments = []
    for c in resp.get("data", []):
        cid = c["id"]
        if cid not in fb_seen_ids:  # avoid duplicates
            fb_seen_ids.add(cid)
            new_comments.append(c)

    return list(reversed(new_comments))  # oldest first

def listen_facebook():
    """Loop for Facebook live comments."""
    print("📺 Checking for live video...")
    video_id = None

    while not video_id:
        video_id = get_live_video_id()
        if not video_id:
            print("⏳ No live video found, retrying in 10s...")
            time.sleep(10)

    print(f"✅ Live video found: {video_id}")
    while True:
        comments = fetch_new_comments(video_id)
        for c in comments:
            ts = c.get("created_time", "")
            user = c.get("from", {}).get("name", "Unknown")
            msg = c.get("message", "")
            print(f"[FB {ts}] {user}: {msg}")
            send_ntfy("Facebook", f"{user}: {msg}")

        time.sleep(FB_POLL_INTERVAL)

if __name__ == "__main__":
    listen_facebook()
