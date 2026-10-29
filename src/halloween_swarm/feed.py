"""Tick sources: the live scenario MCP feed, or an offline fixture file."""

import asyncio
import json
import os
import time
from pathlib import Path

from crewai.mcp import MCPServerHTTP
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from halloween_swarm.config import QUEUE_FILE, env
from halloween_swarm.partners import LEDGER


class FeedError(RuntimeError):
    pass


def normalise(resp: dict) -> tuple[dict, bool]:
    """Return (tick, exhausted) whether the server nests the tick or not."""
    tick = resp.get("tick") if isinstance(resp.get("tick"), dict) else resp
    return tick, bool(resp.get("exhausted") or tick.get("exhausted"))


class LiveFeed:
    def __init__(self) -> None:
        # Never the bare URL string: inside an event loop that shorthand silently yields zero tools.
        self.server = MCPServerHTTP(url=env("SCENARIO_MCP"), streamable=True, headers={})
        self.team = env("TEAM")
        self.token = os.environ.get("TEAM_TOKEN", "").strip()

    async def _acall(self, tool: str, args: dict) -> dict:
        async with streamablehttp_client(self.server.url, headers=self.server.headers or {}) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, args)
        text = "\n".join(c.text for c in result.content if getattr(c, "type", None) == "text")
        data = result.structuredContent if result.structuredContent is not None else json.loads(text or "{}")
        if result.isError:
            raise FeedError(f"{tool}: {text[:300]}")
        return data

    def call(self, tool: str, args: dict) -> dict:
        for attempt in (1, 2):
            started = time.monotonic()
            try:
                data = asyncio.run(self._acall(tool, args))
                LEDGER.add("scenario-mcp", tool, started, ok=True)
                return data
            except Exception as e:
                LEDGER.add("scenario-mcp", tool, started, ok=False, error=f"{type(e).__name__}: {str(e)[:120]}")
                if attempt == 2:
                    raise FeedError(f"{tool} failed twice: {type(e).__name__}: {e}") from e
                time.sleep(3)
        raise AssertionError("unreachable")

    def _team_args(self) -> dict:
        return {"team": self.team, **({"token": self.token} if self.token else {})}

    def scenarios(self) -> list[str]:
        return [s["name"] for s in self.call("hack26-list-scenarios", {})["scenarios"]]

    def get_tick(self, scenario: str) -> tuple[dict, bool, dict]:
        raw = self.call("hack26-get-tick", {**self._team_args(), "scenario": scenario})
        tick, exhausted = normalise(raw)
        return tick, exhausted, raw

    def submit(self, tick_id: int, action: str) -> dict:
        return self.call("hack26-submit-containment", {**self._team_args(), "tick_id": tick_id, "action": action})

    def submit_or_queue(self, tick_id: int, action: str) -> dict:
        try:
            return self.submit(tick_id, action)
        except FeedError as e:
            QUEUE_FILE.parent.mkdir(exist_ok=True)
            with QUEUE_FILE.open("a") as f:
                f.write(json.dumps({"tick_id": tick_id, "action": action, "queued_at": time.time()}) + "\n")
            return {"queued": True, "error": str(e)[:200]}

    def flush_queue(self) -> list[dict]:
        if not QUEUE_FILE.exists():
            return []
        pending = [json.loads(line) for line in QUEUE_FILE.read_text().splitlines() if line.strip()]
        results, still = [], []
        for item in pending:
            try:
                results.append({**item, "judgment": self.submit(item["tick_id"], item["action"])})
            except FeedError:
                still.append(item)
        QUEUE_FILE.write_text("".join(json.dumps(i) + "\n" for i in still))
        return results

    def scoreboard(self) -> dict:
        return self.call("hack26-get-scoreboard", {})


class FixtureFeed:
    """Replays a fixture file offline. Never submits."""

    def __init__(self, path: Path) -> None:
        data = json.loads(Path(path).read_text())
        self.name = data.get("scenario", Path(path).stem)
        self.ticks = data["ticks"]

    def scenarios(self) -> list[str]:
        return [self.name]

    def get_tick(self, scenario: str) -> tuple[dict, bool, dict]:
        if not self.ticks:
            return {}, True, {"exhausted": True}
        tick = self.ticks.pop(0)
        return tick, False, tick
