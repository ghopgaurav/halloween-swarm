"""Check the scenario MCP feed: list tools, call get-tick once, save the raw response.

Usage: python scripts/check_feed.py [outbreak-level-5|control-tick]
Never calls hack26-submit-containment.
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
REQUIRED_TOOLS = {"hack26-get-tick", "hack26-submit-containment", "hack26-get-scoreboard"}

load_dotenv(ROOT / ".env")

# The server definition the crew will use. Never pass the bare URL string as shorthand:
# inside an event loop it silently resolves to zero tools.
SCENARIO = MCPServerHTTP(url=os.environ["SCENARIO_MCP"], streamable=True, headers={})


def tool_result_to_json(result):
    if result.structuredContent is not None:
        return result.structuredContent
    texts = [c.text for c in result.content if getattr(c, "type", None) == "text"]
    joined = "\n".join(texts)
    try:
        return json.loads(joined)
    except json.JSONDecodeError:
        return {"raw_text": joined}


async def main() -> int:
    async with streamablehttp_client(SCENARIO.url, headers=SCENARIO.headers or {}) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = {t.name: t for t in (await session.list_tools()).tools}

            print(f"Tools on {SCENARIO.url}:")
            for name, t in tools.items():
                print(f"  - {name}: {json.dumps(t.inputSchema)}")

            missing = REQUIRED_TOOLS - tools.keys()
            if missing:
                print(f"FAIL missing tools: {sorted(missing)}")
                return 1
            print("PASS all 3 required tools present")

            team = os.environ.get("TEAM", "").strip()
            if not team:
                print("FAIL TEAM is empty in .env (use the handle on your welcome card, e.g. team-04)")
                return 1
            args = {"team": team, "scenario": sys.argv[1] if len(sys.argv) > 1 else "outbreak-level-5"}
            if os.environ.get("TEAM_TOKEN", "").strip():
                args["token"] = os.environ["TEAM_TOKEN"].strip()

            result = await session.call_tool("hack26-get-tick", args)
            if result.isError:
                print(f"FAIL get-tick returned error: {tool_result_to_json(result)}")
                return 1

            out = ROOT / "fixtures" / "sample_tick.json"
            out.parent.mkdir(exist_ok=True)
            out.write_text(json.dumps(tool_result_to_json(result), indent=2))
            print(f"PASS get-tick saved to {out.relative_to(ROOT)}")
            return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
