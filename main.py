import requests
import time
import os

PAGE_ID = os.getenv("FB_PAGE_ID")
ACCESS_TOKEN = os.getenv("FB_PAGE_TOKEN")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", 3))
CHECK_LIVE_INTERVAL = int(os.getenv("CHECK_LIVE_INTERVAL", 15))  # seconds

if not PAGE_ID or not ACCESS_TOKEN:
    print("❌ Please set FB_PAGE_ID and FB_PAGE_TOKEN as environment variables")
    exit(1)

GRAPH_URL = "https://graph.facebook.com/v19.0"

def get_live_video_id():
    url = f"{GRAPH_URL}/{PAGE_ID}/live_videos"
    params = {
        "fields": "id,status,title",
        "access_token": ACCESS_TOKEN,
        "broadcast_status": "LIVE"
    }
    r = requests.get(url, params=params)
    data = r.json()

    if "data" in data and len(data["data"]) > 0:
        live_video = data["data"][0]
        print("✅ Live video found:", live_video)
        return live_video["id"]
    return None

def fetch_live_comments(video_id):
    url = f"{GRAPH_URL}/{video_id}/live_comments"
    params = {
        "fields": "from{name},message,created_time",
        "access_token": ACCESS_TOKEN,
        "comment_rate": "one_per_two_seconds",
        "filter": "stream"
    }

    seen = set()
    print("📡 Listening for chat messages...")

    while True:
        try:
            r = requests.get(url, params=params)
            data = r.json()

            if "data" in data:
                for comment in data["data"]:
                    comment_id = comment.get("id")
                    if comment_id not in seen:
                        seen.add(comment_id)
                        user = comment["from"]["name"]
                        msg = comment.get("message", "")
                        print(f"[Facebook Chat] {user}: {msg}")
        except Exception as e:
            print("❌ Error fetching comments:", e)

        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    while True:
        video_id = get_live_video_id()
        if video_id:
            fetch_live_comments(video_id)
        else:
            print(f"⚠️ No live stream detected, retrying in {CHECK_LIVE_INTERVAL}s...")
            time.sleep(CHECK_LIVE_INTERVAL)
