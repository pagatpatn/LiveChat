from flask import Flask, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import threading
import time
import os

app = Flask(__name__)

# ----------------------
# Configuration
# ----------------------
PAGE_URL = os.getenv("FB_PAGE_URL")  # Facebook Page URL only
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", 2))  # seconds

if not PAGE_URL:
    print("Please set environment variable FB_PAGE_URL")
    exit(1)

# ----------------------
# Selenium setup
# ----------------------
options = Options()
options.add_argument("--headless")  # run in background
options.add_argument("--disable-gpu")
options.add_argument("--no-sandbox")

driver = webdriver.Chrome(options=options)
driver.get(PAGE_URL)
time.sleep(5)

# ----------------------
# Global variables
# ----------------------
seen_messages = set()
latest_messages = []
current_live_url = None

# ----------------------
# Background scraping
# ----------------------
def poll_facebook_chat():
    global seen_messages, latest_messages, current_live_url
    print("Starting Facebook Live chat scraping...")

    while True:
        try:
            # Check if a live video exists
            live_elems = driver.find_elements(By.XPATH, '//a[contains(@aria-label, "LIVE")]')
            if live_elems:
                live_url = live_elems[0].get_attribute("href")
                if live_url != current_live_url:
                    current_live_url = live_url
                    seen_messages.clear()
                    latest_messages.clear()
                    print(f"Connected to new live video: {current_live_url}")
                    driver.get(current_live_url)
                    time.sleep(5)

                # Find chat container
                chat_container = driver.find_element(By.XPATH, '//div[contains(@aria-label, "Comment")]')
                messages = chat_container.find_elements(By.XPATH, './/div[@data-ad-preview="message"]')
                for msg in messages:
                    text = msg.text.strip()
                    if text and text not in seen_messages:
                        seen_messages.add(text)
                        latest_messages.append({"message": text})
                        print("[Facebook Chat]", text)
            else:
                if current_live_url:
                    print("No live video currently.")
                    current_live_url = None
                    seen_messages.clear()
                    latest_messages.clear()
        except Exception as e:
            print("Error fetching messages:", e)
        time.sleep(POLL_INTERVAL)

threading.Thread(target=poll_facebook_chat, daemon=True).start()

# ----------------------
# Flask endpoint
# ----------------------
@app.route("/chat", methods=["GET"])
def get_chat():
    return jsonify(latest_messages)

# ----------------------
# Run Flask
# ----------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
