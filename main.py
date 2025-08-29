import base64, hashlib, json
from fastapi import FastAPI, Request, Response
import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

app = FastAPI()
PUBLIC_KEY_PEM = None
KICK_PUBLIC_KEY_URL = "https://api.kick.com/public/v1/public-key"

async def fetch_kick_public_key_pem() -> str:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(KICK_PUBLIC_KEY_URL)
        r.raise_for_status()
        return r.text

def load_public_key(pem: str):
    return serialization.load_pem_public_key(pem.encode("utf-8"))

@app.on_event("startup")
async def startup():
    global PUBLIC_KEY_PEM
    PUBLIC_KEY_PEM = await fetch_kick_public_key_pem()

def verify_signature(headers, raw_body: bytes) -> bool:
    # Kick signature verification
    try:
        msg_id = headers["Kick-Event-Message-Id"]
        ts = headers["Kick-Event-Message-Timestamp"]
        sig_b64 = headers["Kick-Event-Signature"]
    except KeyError:
        return False

    sign_str = f"{msg_id}.{ts}.{raw_body.decode()}"
    digest = hashlib.sha256(sign_str.encode()).digest()
    signature = base64.b64decode(sig_b64)
    pub = load_public_key(PUBLIC_KEY_PEM)

    try:
        pub.verify(signature, digest, padding.PKCS1v15(), hashes.SHA256())
        return True
    except Exception:
        return False

@app.get("/healthz")
async def healthz():
    return {"ok": True}

@app.post("/kick/webhook")
async def kick_webhook(request: Request):
    raw = await request.body()
    if not verify_signature(request.headers, raw):
        return Response(status_code=401)

    event_type = request.headers.get("Kick-Event-Type", "")
    payload = await request.json()
    print(json.dumps({"event": event_type, "payload": payload}), flush=True)

    if event_type == "chat.message.sent":
        msg = payload.get("content")
        sender = (payload.get("sender") or {}).get("username")
        broadcaster = (payload.get("broadcaster") or {}).get("username")
        print(f"[{broadcaster}] {sender}: {msg}", flush=True)

    return {"status": "ok"}
