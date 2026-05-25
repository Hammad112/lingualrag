"""End-to-end smoke test for LingualRAG backend.

Runs the full pipeline against a live server:
  signup → verify OTP → upload document → query → assert sources

Usage:
  1. Start the server: uvicorn app.main:app
  2. python test_e2e.py
"""
import asyncio
import json
import re
import sys
import time
import httpx

BASE = "http://127.0.0.1:8000"
EMAIL = f"test_{int(time.time())}@example.com"
NAME = "Test User"

# Use a tiny multilingual sample doc embedded in this script so the test is self-contained.
SAMPLE_TEXT = """LingualRAG Test Document

Introduction
LingualRAG is a multilingual retrieval-augmented generation system. It supports English, Arabic, and Urdu.
The system uses dense embeddings combined with BM25 sparse search and reciprocal rank fusion.

Architecture
The architecture has three layers: ingestion, retrieval, and generation. Documents are chunked into pieces of around 500 characters with 80 character overlap.

Languages
For Arabic the system tokenises using a regex that captures Arabic Unicode ranges.
For Urdu the same tokeniser handles Nastaliq script.

Conclusion
This document is intentionally small so the embedding step finishes quickly during automated tests.
"""

OTP_RE = re.compile(r"OTP for .+? \(.+?\): (\d{4,8})")


def grab_otp_from_server_log(log_path: str | None = None) -> str | None:
    """Try to find the most recent OTP in the server log (printed to stdout in dev)."""
    if not log_path:
        return None
    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as fh:
            text = fh.read()
    except FileNotFoundError:
        return None
    matches = OTP_RE.findall(text)
    return matches[-1] if matches else None


async def run(server_log: str | None = None):
    timeout = httpx.Timeout(60.0, connect=10.0)
    async with httpx.AsyncClient(base_url=BASE, timeout=timeout) as client:
        # 1. Health
        r = await client.get("/health")
        assert r.status_code == 200, f"health failed: {r.text}"
        print("[1/6] Server is up.")

        # 2. Send OTP (signup)
        r = await client.post("/auth/send-otp", json={"email": EMAIL, "full_name": NAME})
        assert r.status_code == 200, f"send-otp failed: {r.text}"
        print(f"[2/6] OTP sent to {EMAIL}.")

        # 3. Grab OTP from server log
        otp = None
        for _ in range(20):
            otp = grab_otp_from_server_log(server_log)
            if otp:
                break
            await asyncio.sleep(0.2)
        if not otp:
            print("[!] Could not auto-read OTP from log. Please enter OTP printed in the server console:")
            otp = input("OTP> ").strip()
        print(f"[3/6] OTP read: {otp}")

        # 4. Verify (signup)
        r = await client.post("/auth/verify-otp", json={"email": EMAIL, "otp": otp, "purpose": "signup"})
        assert r.status_code == 200, f"verify failed: {r.text}"
        data = r.json()
        token = data["token"]
        print(f"[4/6] Signed up. User id: {data['user']['id']}")

        auth = {"Authorization": f"Bearer {token}"}

        # 5. Upload document
        files = {"file": ("lingualrag.txt", SAMPLE_TEXT.encode("utf-8"), "text/plain")}
        r = await client.post("/documents/upload", files=files, headers=auth)
        assert r.status_code == 200, f"upload failed: {r.text}"
        doc = r.json()
        doc_id = doc["id"]
        print(f"[5/6] Uploaded doc id={doc_id}, polling for processing…")

        # Poll for ready
        for i in range(90):
            r = await client.get(f"/documents/{doc_id}/status", headers=auth)
            st = r.json().get("status")
            if st == "ready":
                print(f"      Document ready after ~{i*1}s (chunks={r.json().get('chunk_count')}).")
                break
            if st == "error":
                raise RuntimeError(f"Processing failed: {r.json().get('error')}")
            await asyncio.sleep(1)
        else:
            raise RuntimeError("Timeout waiting for processing")

        # 6. Stream a query
        print("[6/6] Querying: 'What is LingualRAG and what languages does it support?'")
        payload = {"query": "What is LingualRAG and what languages does it support?"}
        sources_seen = []
        answer = ""
        async with client.stream("POST", "/chat/stream", json=payload, headers=auth) as resp:
            assert resp.status_code == 200, f"stream failed: {resp.status_code}"
            buf = ""
            async for chunk in resp.aiter_text():
                buf += chunk
                while "\n\n" in buf:
                    frame, buf = buf.split("\n\n", 1)
                    frame = frame.strip()
                    if not frame.startswith("data:"):
                        continue
                    evt = json.loads(frame[5:].strip())
                    if evt.get("type") == "sources":
                        sources_seen = evt.get("sources", [])
                    elif evt.get("type") == "chunk":
                        answer += evt.get("content", "")
                    elif evt.get("type") == "done":
                        pass
        print(f"      Sources: {len(sources_seen)}")
        for s in sources_seen[:3]:
            print(f"        - {s['title']}: {s['excerpt'][:80]}…")
        print(f"      Answer: {answer[:200]}…")
        assert sources_seen, "no sources returned"
        assert any(k in answer.lower() for k in ("lingualrag", "multilingual", "english", "arabic", "urdu")), (
            "answer did not mention expected content"
        )
        print("\nAll checks passed.")


if __name__ == "__main__":
    log = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(run(log))
