import time
import requests
import os


# 🔑 Your details
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
YOUTUBE_CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID")
NTFY_TOPIC = os.getenv("NTFY_TOPIC")  # replace with your topic
NTFY_DELAY = 2  # seconds between notifications to prevent spam

# Keep track of message IDs to avoid duplicates
sent_messages = set()

def send_ntfy_notification(title, message):
    """Send a banner notification via NTFY."""
    try:
        requests.post(
            NTFY_TOPIC,
            data=message.encode("utf-8"),
            headers={
                "Title": title,
                "Priority": "high",  # banner notification
            },
            timeout=5
        )
        time.sleep(NTFY_DELAY)
    except Exception as e:
        print("❌ Failed to send NTFY notification:", e)

def get_live_chat_id():
    """Return active liveChatId if a live stream is found, else None."""
    try:
        search_url = (
            f"https://www.googleapis.com/youtube/v3/search"
            f"?part=snippet"
            f"&channelId={YOUTUBE_CHANNEL_ID}"
            f"&eventType=live"
            f"&type=video"
            f"&key={YOUTUBE_API_KEY}"
        )
        resp = requests.get(search_url).json()

        if "error" in resp:
            print("❌ SEARCH ERROR:", resp["error"]["message"])
            return None

        items = resp.get("items", [])
        if not items:
            return None

        video_id = items[0]["id"]["videoId"]

        videos_url = (
            f"https://www.googleapis.com/youtube/v3/videos"
            f"?part=liveStreamingDetails"
            f"&id={video_id}"
            f"&key={YOUTUBE_API_KEY}"
        )
        resp2 = requests.get(videos_url).json()

        if "error" in resp2:
            print("❌ VIDEO DETAILS ERROR:", resp2["error"]["message"])
            return None

        live_chat_id = resp2["items"][0]["liveStreamingDetails"].get("activeLiveChatId")
        return live_chat_id

    except Exception as e:
        print("❌ Exception while fetching live chat ID:", e)
        return None

def listen_to_chat(live_chat_id):
    """Listen to live chat messages until the stream ends."""
    print("✅ Connected to YouTube live chat!")
    page_token = None

    while True:
        try:
            url = (
                f"https://www.googleapis.com/youtube/v3/liveChat/messages"
                f"?liveChatId={live_chat_id}"
                f"&part=snippet,authorDetails"
                f"&key={YOUTUBE_API_KEY}"
            )
            if page_token:
                url += f"&pageToken={page_token}"

            resp = requests.get(url).json()

            if "error" in resp:
                print("❌ LIVE CHAT ERROR:", resp["error"]["message"])
                return

            for item in resp.get("items", []):
                msg_id = item["id"]
                if msg_id in sent_messages:
                    continue  # skip duplicates

                sent_messages.add(msg_id)

                user = item["authorDetails"]["displayName"]
                msg = item["snippet"]["displayMessage"]
                print(f"[YouTube] {user}: {msg}")

                # Send NTFY notification
                send_ntfy_notification(title=f"New chat from {user}", message=msg)

            page_token = resp.get("nextPageToken")
            polling_interval = resp.get("pollingIntervalMillis", 5000) / 1000
            time.sleep(polling_interval)

        except Exception as e:
            print("❌ Exception while polling chat:", e)
            time.sleep(5)

if __name__ == "__main__":
    while True:
        print("🔍 Checking for live stream...")
        live_chat_id = get_live_chat_id()
        if live_chat_id:
            print("🎥 Live stream found! Starting chat listener...")
            listen_to_chat(live_chat_id)
            print("ℹ️ Live stream ended or chat unavailable. Rechecking...")
        else:
            print("⏳ No live stream detected. Retrying in 10s...")
            time.sleep(10)
