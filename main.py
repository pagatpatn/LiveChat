import os
import requests
import time

# ----------------------
# Configuration
# ----------------------
PAGE_ID = os.getenv("FB_PAGE_ID")
PAGE_TOKEN = os.getenv("FB_PAGE_TOKEN")
POLL_INTERVAL = 5  # seconds

if not PAGE_ID or not PAGE_TOKEN:
    print("Please set environment variables FB_PAGE_ID and FB_PAGE_TOKEN")
    exit(1)

# ----------------------
# Functions
# ----------------------
def get_current_live_video():
    """
    Returns the current live video ID if the stream is actually LIVE.
    Otherwise returns None.
    """
    url = f"https://graph.facebook.com/v18.0/{PAGE_ID}/live_videos"
    params = {"status": "LIVE_NOW", "access_token": PAGE_TOKEN}

    resp = requests.get(url, params=params).json()

    if "data" in resp and resp["data"]:
        video = resp["data"][0]
        if video.get("status") == "LIVE":
            return video["id"]
    return None

# ----------------------
# Main loop
# ----------------------
def main():
    last_video_id = None
    print("Starting Facebook Live chat fetcher...")

    while True:
        video_id = get_current_live_video()
        if video_id:
            if video_id != last_video_id:
                print(f"Connected to Facebook live video: {video_id}")
                last_video_id = video_id
        else:
            if last_video_id is not None:
                print("No live video currently.")
                last_video_id = None

        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()
