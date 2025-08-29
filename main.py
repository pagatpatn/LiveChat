from fastapi import FastAPI
import httpx
import asyncio
import os

app = FastAPI()

# Config from Railway Variables
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "kick-chat")
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"
CHANNEL = os.getenv("KICK_CHANNEL", "xqc")

async def poll_and_forward_chat(channel: str):
    """Continuously fetch chat for a channel if live and forward to ntfy"""
    last_message_id = None

    async with httpx.AsyncClient() as client:
        while True:
            try:
                # 1. Check if channel is live
                r_info = await client.get(f"https://kick.com/api/v2/channels/{channel}")
                if r_info.status_code == 200:
                    info = r_info.json()
                    if not info.get("livestream"):  # channel not live
                        print(f"{channel} is offline, retrying...")
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

                            # Format: Channel - Username: Message
                            payload = f"{channel} - {username}: {text}"

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
    asyncio.create_task(poll_and_forward_chat(CHANNEL))


@app.get("/healthz")
async def healthz():
    return {"ok": True}
