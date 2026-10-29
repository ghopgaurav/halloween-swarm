"""Smoke-test partner credentials. Prints PASS/FAIL per service.

Parasail free tier is 5 req/min; this makes 3 Parasail calls (models, chat, embeddings).
Each call retries at most once (after Retry-After on a 429). Keys are never printed in full.
"""

import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv
from openai import APIStatusError, OpenAI

ROOT = Path(__file__).resolve().parent.parent
PARASAIL_BASE = "https://api.parasail.io/v1"
CHAT_MODEL = "parasail-glm-53"
EMBED_MODEL = "parasail-bge-m3"

load_dotenv(ROOT / ".env")
results: list[tuple[str, bool, str]] = []


def mask(key: str) -> str:
    return f"{key[:4]}…{key[-2:]} ({len(key)} chars)" if len(key) > 8 else "(too short)"


def record(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")


def retry_once(call):
    """Run call(); on 401/403/429 or network error, retry exactly once."""
    try:
        return call()
    except (httpx.HTTPStatusError, APIStatusError) as e:
        resp = e.response
        if resp.status_code == 429:
            wait = float(resp.headers.get("retry-after", "15"))
            print(f"      429 rate limited, waiting {wait:.0f}s (Retry-After)")
            time.sleep(wait)
        elif resp.status_code not in (401, 403):
            raise
        return call()
    except httpx.TransportError:
        return call()


def env_key(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    if not value:
        record(name, False, "empty in .env")
        return None
    print(f"      {name} = {mask(value)}")
    return value


def check_youcom() -> None:
    key = env_key("YDC_API_KEY")
    if not key:
        return

    def call():
        r = httpx.post(
            "https://ydc-index.io/v1/search",
            headers={"X-API-Key": key},
            json={"query": "AWS Builder Loft San Francisco", "count": 3},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    try:
        data = retry_once(call)
        web = data.get("results", {}).get("web", [])
        if not web:
            record("You.com search", False, f"no web results; keys: {list(data)}")
        else:
            record("You.com search", True, f"{len(web)} hits, first: {web[0].get('title', '')[:60]!r}")
    except Exception as e:
        record("You.com search", False, describe(e))


def check_parasail() -> None:
    key = env_key("PARASAIL_API_KEY")
    if not key:
        return

    def list_models():
        r = httpx.get(f"{PARASAIL_BASE}/models", headers={"Authorization": f"Bearer {key}"}, timeout=30)
        r.raise_for_status()
        return [m["id"] for m in r.json()["data"]]

    try:
        ids = retry_once(list_models)
    except Exception as e:
        record("Parasail models", False, describe(e))
        return
    record("Parasail models", True, f"{len(ids)} models listed")
    embed_like = [i for i in ids if any(s in i.lower() for s in ("embed", "gritlm", "bge", "e5", "gte"))]
    record("Parasail chat model listed", CHAT_MODEL in ids, CHAT_MODEL)
    record("Parasail embed model listed", EMBED_MODEL in ids, f"{EMBED_MODEL}; embedding-like: {embed_like}")

    client = OpenAI(base_url=PARASAIL_BASE, api_key=key, max_retries=0, timeout=60)
    try:
        resp = retry_once(lambda: client.chat.completions.create(
            model=CHAT_MODEL, messages=[{"role": "user", "content": "Reply with the single word: boo"}], max_tokens=200,
        ))
        msg = resp.choices[0].message
        text = (msg.content or "").strip() or "(empty content; reasoning model may need more max_tokens)"
        record("Parasail chat", True, f"{text[:60]!r}")
    except Exception as e:
        record("Parasail chat", False, describe(e))

    embed_model = EMBED_MODEL if EMBED_MODEL in ids else (embed_like[0] if embed_like else None)
    if not embed_model:
        record("Parasail embeddings", False, "no embeddings model listed")
        return
    try:
        emb = retry_once(lambda: client.embeddings.create(model=embed_model, input="cold spot near the coffee bar"))
        record("Parasail embeddings", True, f"{embed_model}, dim={len(emb.data[0].embedding)}")
    except Exception as e:
        record("Parasail embeddings", False, describe(e))


def describe(e: Exception) -> str:
    resp = getattr(e, "response", None)
    if resp is not None:
        return f"HTTP {resp.status_code}: {resp.text[:200]}"
    return f"{type(e).__name__}: {e}"


if __name__ == "__main__":
    check_youcom()
    check_parasail()
    failed = [name for name, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed" + (f"; failed: {failed}" if failed else ""))
    sys.exit(1 if failed else 0)
