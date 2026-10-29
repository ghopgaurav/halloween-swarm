"""Read-only probe of the scenario MCP: tool schemas, scenarios, oracle doctrine, scoreboard.

Writes docs/tools.md and docs/doctrine.md. Never calls get-tick or submit-containment.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from crewai.mcp import MCPServerHTTP
from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
SCENARIO = MCPServerHTTP(url=os.environ["SCENARIO_MCP"], streamable=True, headers={})

QUESTIONS = [
    "What is the official doctrine for choosing contain vs evacuate vs observe?",
    "When should a team escalate to the Discord channel, and when is it a false alarm?",
    "What does a harmless control tick look like?",
    "How should a swarm treat low-confidence residual echoes or sensor faults?",
    "How does the feed signal that there are no more ticks?",
]


def text_of(result) -> str:
    if result.structuredContent is not None:
        return json.dumps(result.structuredContent, indent=2)
    return "\n".join(c.text for c in result.content if getattr(c, "type", None) == "text")


async def main() -> int:
    async with streamablehttp_client(SCENARIO.url, headers=SCENARIO.headers or {}) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools

            lines = [f"# Scenario MCP tools\n\nServer: `{SCENARIO.url}` (streamable HTTP, no auth headers)\n"]
            for t in tools:
                lines += [f"## `{t.name}`\n", (t.description or "").strip() + "\n",
                          "```json", json.dumps(t.inputSchema, indent=2), "```\n"]
            scenarios = text_of(await session.call_tool("hack26-list-scenarios", {}))
            lines += ["## `hack26-list-scenarios` response\n", "```", scenarios, "```\n"]
            scoreboard = text_of(await session.call_tool("hack26-get-scoreboard", {}))
            lines += ["## `hack26-get-scoreboard` response (at probe time)\n", "```", scoreboard, "```\n"]
            (ROOT / "docs").mkdir(exist_ok=True)
            (ROOT / "docs" / "tools.md").write_text("\n".join(lines))
            print("wrote docs/tools.md")

            doc = ["# Doctrine (from hack26-ask-oracle)\n",
                   "Verbatim oracle answers. The commander and the safety gate follow these; nothing here is invented.\n"]
            for q in QUESTIONS:
                await asyncio.sleep(1)
                answer = text_of(await session.call_tool("hack26-ask-oracle", {"question": q}))
                doc += [f"## Q: {q}\n", answer.strip() + "\n"]
            (ROOT / "docs" / "doctrine.md").write_text("\n".join(doc))
            print("wrote docs/doctrine.md")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
