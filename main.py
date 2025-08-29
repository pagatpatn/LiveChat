from fastapi import FastAPI
import httpx
import asyncio
import os

app = FastAPI()

# Config from Railway Variables
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "kick-chat")
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"
CHANNEL = os.getenv("KICK_CHANNEL", "LastMove")

async def poll_and_forward_chat(channel: str):
    """Continuously fetch chat for a channel if live and forward to ntfy"""
    last_message_id = None
    was_live = False

    async with httpx.AsyncClient() as client:
        while True:
            try:
                # 1. Check if channel is live
                r_info = await client.get(f"https://kick.com/api/v2/channels/{channel}")
                if r_info.status_code == 200:
                    info = r_info.json()
                    is_live = bool(info.get("livestream"))

                    # Detect state changes
                    if is_live and not was_live:
                        print(f"✅ {channel} just went LIVE!")
                        was_live = True
                    elif not is_live and was_live:
                        print(f"🛑 {channel} went OFFLINE.")
                        was_live = False

                    if not is_live:
                        print(f"{channel} is offline, retrying in 10s...")
                        await asyncio.sleep(10)
                        continue

                # 2. Fetch chat messages
                r_chat = await client.get(f"https://kick.com/api/v2/channels/{channel}/chatroom/messages")
                if r_chat.status_code == 200:
                    data = r_chat.json()
                    messages = data.get("messages", [])

                    for msg in messages:
                        if last_message_id is None or msg["id"] > last_message_id:
                            username = msg["sender"]["username"]
                            text = msg["content"]

                            # Format: Username: Message
                            payload = f"{username}: {text}"

                            # 3. Send to ntfy
                            try:
                                await client.post(NTFY_URL, data=payload.encode("utf-8"))
                                print("Sent:", payload)
                            except Exception as e:
                                print("Error sending to ntfy:", e)

                            # 4. Wait 5s before sending next message
                            await asyncio.sleep(5)

                            last_message_id = msg["id"]

            except Exception as e:
                print("Error fetching chat:", e)

            await asyncio.sleep(5)  # poll every 5s


@app.on_event("startup")
async def startup_event():
    """Start background polling for a channel"""
    print(f"🚀 Starting Kick chat fetcher for channel: {CHANNEL}")
    asyncio.create_task(poll_and_forward_chat(CHANNEL))


@app.get("/healthz")
async def healthz():
    return {"ok": True}
