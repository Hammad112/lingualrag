"""Full-stack integration test: simulates the browser flow with CORS preflight.

Verifies:
  - CORS preflight succeeds for the frontend origin
  - Frontend's /auth/send-otp call works
  - /auth/verify-otp returns token + user shaped correctly
  - /documents and /documents/upload work
  - /chat/stream over SSE with bearer auth works
"""
import asyncio, json, sys, time, re, httpx

BASE = "http://127.0.0.1:8000"
FRONTEND_ORIGIN = "http://localhost:3001"
EMAIL = f"ui_{int(time.time())}@example.com"
LOG = sys.argv[1] if len(sys.argv) > 1 else None
OTP_RE = re.compile(r"OTP for .+? \(.+?\): (\d{4,8})")


def grab_otp():
    if not LOG: return None
    try:
        return OTP_RE.findall(open(LOG, encoding="utf-8", errors="ignore").read())[-1]
    except (FileNotFoundError, IndexError):
        return None


async def run():
    cors_headers = {"Origin": FRONTEND_ORIGIN}
    async with httpx.AsyncClient(base_url=BASE, timeout=120, headers=cors_headers) as c:
        # 1. CORS preflight for /auth/send-otp
        r = await c.request(
            "OPTIONS", "/auth/send-otp",
            headers={
                "Origin": FRONTEND_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert "access-control-allow-origin" in {k.lower() for k in r.headers.keys()}, \
            f"CORS missing: {r.headers}"
        print("[1/8] CORS preflight: ok")

        # 2. Send OTP
        r = await c.post("/auth/send-otp", json={"email": EMAIL, "full_name": "UI Test"})
        assert r.status_code == 200, r.text
        print("[2/8] Send OTP: ok")

        # 3. Read OTP
        otp = None
        for _ in range(20):
            otp = grab_otp()
            if otp: break
            await asyncio.sleep(0.2)
        assert otp, "No OTP in log"
        print(f"[3/8] OTP read: {otp}")

        # 4. Verify
        r = await c.post("/auth/verify-otp", json={"email": EMAIL, "otp": otp, "purpose": "signup"})
        assert r.status_code == 200, r.text
        data = r.json()
        for k in ("token", "refreshToken", "user"):
            assert k in data, f"missing {k} in {data}"
        for k in ("id", "email", "name", "isAdmin", "createdAt"):
            assert k in data["user"], f"missing user.{k}"
        token = data["token"]
        print(f"[4/8] Verify: ok ({data['user']['email']})")

        auth = {"Authorization": f"Bearer {token}", **cors_headers}

        # 5. /auth/me
        r = await c.get("/auth/me", headers=auth)
        assert r.status_code == 200, r.text
        assert r.json()["user"]["email"] == EMAIL
        print("[5/8] /auth/me: ok")

        # 6. List documents (empty)
        r = await c.get("/documents", headers=auth)
        assert r.status_code == 200 and "documents" in r.json()
        print(f"[6/8] /documents (list): ok ({len(r.json()['documents'])} docs)")

        # 7. Upload
        sample = b"LingualRAG is awesome. It supports many languages including English, Urdu, and Arabic."
        r = await c.post("/documents/upload", files={"file": ("hello.txt", sample, "text/plain")}, headers=auth)
        assert r.status_code == 200, r.text
        doc_id = r.json()["id"]
        for _ in range(60):
            r = await c.get(f"/documents/{doc_id}/status", headers=auth)
            if r.json()["status"] == "ready":
                break
            await asyncio.sleep(0.5)
        assert r.json()["status"] == "ready", r.json()
        print("[7/8] Upload + processing: ok")

        # 8. Chat stream
        sources, answer = [], ""
        async with c.stream(
            "POST", "/chat/stream",
            json={"query": "What is LingualRAG?"},
            headers=auth,
        ) as resp:
            assert resp.status_code == 200
            buf = ""
            async for chunk in resp.aiter_text():
                buf += chunk
                while "\n\n" in buf:
                    frame, buf = buf.split("\n\n", 1)
                    if not frame.startswith("data:"): continue
                    evt = json.loads(frame[5:].strip())
                    if evt.get("type") == "sources":
                        sources = evt["sources"]
                    elif evt.get("type") == "chunk":
                        answer += evt["content"]
        assert sources, "no sources from stream"
        assert answer, "no answer streamed"
        print(f"[8/8] Chat stream: ok ({len(sources)} sources, {len(answer)} chars)")
        print("\nFull-stack flow verified.")


if __name__ == "__main__":
    asyncio.run(run())
