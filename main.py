import requests
import json

# 👇 replace with your Page Access Token (not user token)
PAGE_ACCESS_TOKEN = "YOUR_PAGE_ACCESS_TOKEN"
PAGE_ID = "110575327401854"  # Last Move Gaming

BASE_URL = "https://graph.facebook.com/v20.0"

def log_test(name, url):
    print(f"\n=== Testing {name} ===")
    try:
        r = requests.get(url)
        data = r.json()
        print("Response:", json.dumps(data, indent=2))
        if "error" in data:
            print("⚠️ Error found in this endpoint")
        elif not data.get("data") and not data.get("id"):
            print("⚠️ No video/data found in this endpoint")
    except Exception as e:
        print("❌ Exception:", e)

def main():
    # Test 1: Who am I with this token?
    log_test("/me", f"{BASE_URL}/me?access_token={PAGE_ACCESS_TOKEN}")

    # Test 2: Check page info
    log_test("/PAGE_ID", f"{BASE_URL}/{PAGE_ID}?fields=id,name&access_token={PAGE_ACCESS_TOKEN}")

    # Test 3: Live videos
    log_test("/PAGE_ID/live_videos", 
             f"{BASE_URL}/{PAGE_ID}/live_videos?fields=id,status,live_views,permalink_url,creation_time,broadcast_start_time&access_token={PAGE_ACCESS_TOKEN}")

    # Test 4: Videos type=live
    log_test("/PAGE_ID/videos?type=live", 
             f"{BASE_URL}/{PAGE_ID}/videos?type=live&fields=id,title,description,live_status,permalink_url&access_token={PAGE_ACCESS_TOKEN}")

    # Test 5: All videos
    log_test("/PAGE_ID/videos", 
             f"{BASE_URL}/{PAGE_ID}/videos?fields=id,title,live_status,permalink_url&access_token={PAGE_ACCESS_TOKEN}")

if __name__ == "__main__":
    main()
