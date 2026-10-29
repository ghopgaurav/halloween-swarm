"""Partner HTTP calls (You.com, Parasail embeddings, Discord webhook), each recorded in the ledger."""

import contextvars
import threading
import time

import httpx

from halloween_swarm.config import EMBED_MODEL, PARASAIL_BASE, env

# Which unit of work a call belongs to: "tick", or "dispatch:<tick_id>" for a background escalation.
SCOPE: contextvars.ContextVar[str] = contextvars.ContextVar("ledger_scope", default="tick")


class Ledger:
    """Every partner call, tagged with the unit of work it belongs to: the evidence log for the judges."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.calls: list[dict] = []

    def add(self, partner: str, op: str, started: float | None = None, **extra) -> None:
        row = {"partner": partner, "op": op, "scope": SCOPE.get(), **extra}
        if started is not None:
            row["ms"] = round((time.monotonic() - started) * 1000)
        with self._lock:
            self.calls.append(row)

    def drain(self, scope: str = "tick") -> list[dict]:
        with self._lock:
            taken = [c for c in self.calls if c["scope"] == scope]
            self.calls = [c for c in self.calls if c["scope"] != scope]
        return taken


LEDGER = Ledger()


def retry_after(resp: httpx.Response, default: float = 2.0) -> float:
    try:
        return min(float(resp.headers.get("retry-after", default)), 60.0)
    except ValueError:
        return default


def request(method: str, url: str, *, partner: str, op: str, retry_on_timeout: bool = True, **kwargs) -> httpx.Response:
    """One request, retried once: after Retry-After on 429, after a short backoff on 5xx or a dropped connection."""
    for attempt in (1, 2):
        started = time.monotonic()
        try:
            resp = httpx.request(method, url, timeout=30, **kwargs)
        except httpx.TransportError as e:
            LEDGER.add(partner, op, started, ok=False, error=type(e).__name__)
            if attempt == 2 or not retry_on_timeout:
                raise
            time.sleep(2)
            continue
        LEDGER.add(partner, op, started, ok=resp.is_success, status=resp.status_code,
                   **({"ratelimit_remaining": resp.headers["x-ratelimit-remaining"]} if "x-ratelimit-remaining" in resp.headers else {}))
        if resp.headers.get("x-ratelimit-remaining") == "0":
            # Out of quota for this window: wait for the reset (seconds when small, else a short pause) before the next call.
            try:
                reset = float(resp.headers.get("x-ratelimit-reset", "1"))
            except ValueError:
                reset = 1.0
            time.sleep(min(reset if reset <= 60 else 1.0, 10.0))
        if attempt == 1 and (resp.status_code == 429 or (resp.status_code >= 500 and retry_on_timeout)):
            time.sleep(retry_after(resp) if resp.status_code == 429 else 2)
            continue
        resp.raise_for_status()
        return resp
    raise AssertionError("unreachable")


def you_search(query: str, count: int = 3) -> list[dict]:
    resp = request(
        "POST", "https://ydc-index.io/v1/search", partner="you.com", op="search",
        headers={"X-API-Key": env("YDC_API_KEY")},
        json={"query": query, "count": count, "extraction": {"extraction_mode": "highlights"}},
    )
    hits = []
    for r in resp.json().get("results", {}).get("web", []):
        contents = r.get("contents") or {}
        passages = contents.get("highlights") or r.get("snippets") or [r.get("description", "")]
        hits.append({
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "highlights": [p[:300] for p in passages if p][:2],
        })
    return hits


def parasail_embed(texts: list[str]) -> list[list[float]]:
    resp = request(
        "POST", f"{PARASAIL_BASE}/embeddings", partner="parasail", op=f"embeddings:{EMBED_MODEL}",
        headers={"Authorization": f"Bearer {env('PARASAIL_API_KEY')}"},
        json={"model": EMBED_MODEL, "input": texts},
    )
    rows = sorted(resp.json()["data"], key=lambda d: d["index"])
    return [row["embedding"] for row in rows]


def post_webhook(content: str) -> int:
    """Post to the venue Discord webhook. A write: retried only on 429, never on a timeout or 5xx."""
    resp = request(
        "POST", env("DISCORD_WEBHOOK_URL"), partner="discord-webhook", op="post",
        retry_on_timeout=False, json={"content": content[:1900]},
    )
    return resp.status_code
