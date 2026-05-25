"""Multilingual smoke test: confirms the retrieval pipeline handles English, Urdu, and Arabic."""
import asyncio, json, sys, time, re, httpx

BASE = "http://127.0.0.1:8000"
EMAIL = f"ml_{int(time.time())}@example.com"
LOG = sys.argv[1] if len(sys.argv) > 1 else None

DOC = (
    "English section: LingualRAG supports English documents and queries.\n\n"
    "اردو سیکشن: LingualRAG اردو زبان کی حمایت کرتا ہے اور دستاویزات کا تجزیہ کر سکتا ہے۔\n\n"
    "القسم العربي: يدعم LingualRAG اللغة العربية ويمكنه تحليل المستندات بشكل دقيق.\n"
)

QUERIES = [
    ("en", "What languages does LingualRAG support?"),
    ("ur", "LingualRAG کن زبانوں کی حمایت کرتا ہے؟"),
    ("ar", "ما هي اللغات التي يدعمها LingualRAG؟"),
]

OTP_RE = re.compile(r"OTP for .+? \(.+?\): (\d{4,8})")


def grab_otp():
    if not LOG: return None
    try:
        return OTP_RE.findall(open(LOG, encoding="utf-8", errors="ignore").read())[-1]
    except (FileNotFoundError, IndexError):
        return None


async def run():
    async with httpx.AsyncClient(base_url=BASE, timeout=120) as c:
        await c.post("/auth/send-otp", json={"email": EMAIL, "full_name": "ML"})
        for _ in range(20):
            otp = grab_otp()
            if otp: break
            await asyncio.sleep(0.2)
        r = await c.post("/auth/verify-otp", json={"email": EMAIL, "otp": otp, "purpose": "signup"})
        token = r.json()["token"]
        auth = {"Authorization": f"Bearer {token}"}

        # Upload
        r = await c.post("/documents/upload", files={"file": ("ml.txt", DOC.encode("utf-8"), "text/plain")}, headers=auth)
        doc_id = r.json()["id"]
        for _ in range(60):
            r = await c.get(f"/documents/{doc_id}/status", headers=auth)
            if r.json()["status"] == "ready": break
            await asyncio.sleep(1)
        print(f"Uploaded ({r.json()['chunk_count']} chunks).")

        for lang, q in QUERIES:
            sources, answer = [], ""
            async with c.stream("POST", "/chat/stream", json={"query": q}, headers=auth) as resp:
                buf = ""
                async for chunk in resp.aiter_text():
                    buf += chunk
                    while "\n\n" in buf:
                        frame, buf = buf.split("\n\n", 1)
                        if not frame.startswith("data:"): continue
                        evt = json.loads(frame[5:].strip())
                        if evt.get("type") == "sources": sources = evt["sources"]
                        elif evt.get("type") == "chunk": answer += evt["content"]
            print(f"\n[{lang}] Q: {q}")
            print(f"  Sources: {len(sources)}, top excerpt: {sources[0]['excerpt'][:80] if sources else 'none'}...")
            print(f"  Answer (first 120 chars): {answer[:120]}")
            assert sources, f"no sources for {lang}"
        print("\nAll language paths returned sources.")


if __name__ == "__main__":
    asyncio.run(run())
