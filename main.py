import requests
import time

PAGE_ID = "110575327401854"  # 👈 Your Page ID
ACCESS_TOKEN = "YOUR_PAGE_ACCESS_TOKEN"
GRAPH_URL = "https://graph.facebook.com/v19.0"

def test_live_video_methods():
    endpoints = [
        {
            "name": "/live_videos",
            "url": f"{GRAPH_URL}/{PAGE_ID}/live_videos",
            "params": {
                "fields": "id,status,live_status,title,created_time",
                "access_token": ACCESS_TOKEN
            }
        },
        {
            "name": "/videos?type=live",
            "url": f"{GRAPH_URL}/{PAGE_ID}/videos",
            "params": {
                "fields": "id,status,live_status,title,created_time",
                "access_token": ACCESS_TOKEN,
                "type": "live"
            }
        },
        {
            "name": "/videos (no type)",
            "url": f"{GRAPH_URL}/{PAGE_ID}/videos",
            "params": {
                "fields": "id,status,live_status,title,created_time",
                "access_token": ACCESS_TOKEN
            }
        }
    ]

    for ep in endpoints:
        print(f"\n=== Testing {ep['name']} ===")
        try:
            r = requests.get(ep["url"], params=ep["params"])
            data = r.json()
            print("Response:", data)

            if "data" in data and len(data["data"]) > 0:
                for vid in data["data"]:
                    print("Video candidate:", vid)
                    if vid.get("live_status") == "LIVE" or vid.get("status") == "LIVE":
                        print("✅ Found LIVE video:", vid["id"])
            else:
                print("⚠️ No video data found in this endpoint")
        except Exception as e:
            print("Error:", e)


if __name__ == "__main__":
    print("🔍 Starting Facebook Live Debug Tester")
    test_live_video_methods()
