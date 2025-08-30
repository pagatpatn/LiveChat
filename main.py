"""
Render-friendly Kick chat poller -> ntfy forwarder.

Behavior:
- Polls Kick for channel info and chatroom messages.
- Only forwards chat while livestream is active.
- Sends logs & chat messages to ntfy (if NTFY_TOPIC env var provided)
- Avoids resending same messages using an ID set.
- Backoff & helpful debug messages for troubleshooting.

Config via Render Environment Variables:
- KICK_CHANNEL  (default: "LastMove")
- NTFY_TOPIC    (e.g. "mytopic"  -> will post to https://ntfy.sh/mytopic)
- POLL_INTERVAL (optional, seconds between polls; default 5)
- LOG_TO_NTFY   (optional "true"/"false"; default "true" if NTFY_TOPIC set)
"""
import os
import asyncio
from datetime import datetime
import httpx
from fastapi import FastAPI

app = FastAPI()

# Configuration
CHANNEL = os.getenv("KICK_CHANNEL", "LastMove")  # change as needed
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "").strip()
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "5"))
LOG_TO_NTFY = os.getenv("LOG_TO_NTFY", "true").lower() in ("1", "true", "yes")

if NTFY_TOPIC:
    NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"
else:
    NTFY_URL = None
    LOG_TO_NTFY = False

async def notify(client: httpx.AsyncClient, message: str):
    """Print to console and optionally send to ntfy."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    out = f"[{ts}] {message}"
    print(out, flush=True)

    if LOG_TO_NTFY and NTFY_URL:
        try:
            # small timeout & ignore response body
            await client.post(NTFY_URL, data=out.encode("utf-8"), timeout=10.0)
        except Exception as e:
            # don't crash on notify failure; log locally
            print(f"[{ts}] ❌ ntfy send failed: {e}", flush=True)

async def poll_and_forward_chat(channel: str):
    """Main background task: detect live, poll chatroom, forward messages."""
    last_ids = set()
    first_success = False

    async with httpx.AsyncClient(timeout=10.0) as client:
        await notify(client, f"🚀 Kick chat fetcher booting for channel: {channel}")

        # Keep trying forever
        while True:
            try:
                # 1) Get channel info (try v2)
                resp = await client.get(f"https://kick.com/api/v2/channels/{channel}")
                if resp.status_code != 200:
                    await notify(client, f"❌ Channel fetch failed [{resp.status_code}]: {resp.text[:300]}")
                    # If blocked (403) or not found (404), sleep longer
                    await asyncio.sleep(10)
                    continue

                info = resp.json()

                # 2) Prefer livestream object from channel info
                livestream = info.get("livestream")
                if not livestream:
                    # Not live
                    await notify(client, f"📡 {channel} is offline — will retry in 10s")
                    await asyncio.sleep(10)
                    continue

                # If we reach here, channel is live
                if not first_success:
                    await notify(client, f"✅ {channel} detected LIVE ({datetime.now().strftime('%H:%M:%S')})")
                    first_success = True

                # Get chatroom id for reliable messages endpoint
                chatroom = livestream.get("chatroom") or info.get("chatroom")
                chatroom_id = None
                if chatroom:
                    chatroom_id = chatroom.get("id")
                if not chatroom_id:
                    # Try to get chatroom id from channel->chatroom fallback
                    await notify(client, "❌ Could not find chatroom id in channel info; retrying")
                    await asyncio.sleep(5)
                    continue

                # 3) Poll messages endpoint
                chat_resp = await client.get(f"https://kick.com/api/v2/chatrooms/{chatroom_id}/messages")
                if chat_resp.status_code != 200:
                    await notify(client, f"❌ Chat fetch failed [{chat_resp.status_code}]: {chat_resp.text[:300]}")
                    await asyncio.sleep(POLL_INTERVAL)
                    continue

                data = chat_resp.json()
                messages = data.get("messages", []) or []

                # iterate in natural order (older -> newer)
                for msg in messages:
                    msg_id = msg.get("id")
                    if not msg_id:
                        continue
                    if msg_id in last_ids:
                        continue

                    sender = (msg.get("sender") or {}).get("username") or "unknown"
                    text = msg.get("content") or ""
                    formatted = f"{sender}: {text}"

                    # send (console + ntfy)
                    await notify(client, f"💬 {formatted}")

                    # mark as seen
                    last_ids.add(msg_id)
                    # keep last_ids bounded to avoid memory growth
                    if len(last_ids) > 1000:
                        # drop oldest half — set has no order, so just reset smaller set
                        last_ids = set(list(last_ids)[-500:])

                    # spam-proof delay between forwards
                    await asyncio.sleep(5)

                await asyncio.sleep(POLL_INTERVAL)

            except Exception as e:
                await notify(client, f"⚠️ Unexpected error: {e}")
                await asyncio.sleep(10)


@app.on_event("startup")
async def startup_event():
    # launch background worker
    asyncio.create_task(poll_and_forward_chat(CHANNEL))

@app.get("/healthz")
async def healthz():
    return {"ok": True}
