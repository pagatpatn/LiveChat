from fastapi import FastAPI
import httpx

app = FastAPI()

@app.get("/healthz")
async def healthz():
    return {"ok": True}

@app.get("/kick/{channel}")
async def kick_chat(channel: str):
    """Fetch recent chat messages from a Kick channel"""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"https://kick.com/api/v2/channels/{channel}/chatroom/messages")
        return r.json()
