#!/usr/bin/env python
"""The Exorcism Protocol loop: get tick -> triage -> swarm (contested sectors only) -> gate -> submit, with
escalations briefed and posted in the background, until the feed is exhausted."""

import argparse
import contextvars
import json
import sys
import time
import warnings
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

# The specialists start concurrently in threads. Their first calls race the OpenAI SDK's lazy imports
# (deadlocked or half-imported modules), so load those resources once on the main thread.
import openai  # noqa: E402

_warm = openai.OpenAI(api_key="warmup", base_url="http://localhost")
_ = (_warm.chat.completions, _warm.beta, _warm.embeddings, _warm.responses)
del _warm, _

from halloween_swarm.config import RUNS_DIR, env  # noqa: E402
from halloween_swarm.budget import AGENTS  # noqa: E402
from halloween_swarm.crew import ReviewSwarm  # noqa: E402
from halloween_swarm.evidence import EVIDENCE_LISTENER  # noqa: E402,F401  (registers the listener)
from halloween_swarm.feed import FixtureFeed, LiveFeed  # noqa: E402
from halloween_swarm.flow import TickFlow, one_line  # noqa: E402
from halloween_swarm.partners import LEDGER, SCOPE, post_webhook  # noqa: E402
from halloween_swarm.schemas import ReviewVerdict  # noqa: E402


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fixture", type=Path, help="replay a fixture file offline (never submits or posts)")
    p.add_argument("--dry-run", action="store_true", help="live feed, but never submit or post")
    p.add_argument("--scenario", action="append", help="live scenario(s) to run; default: all listed")
    p.add_argument("--max-ticks", type=int, default=25, help="safety cap per scenario")
    return p.parse_args(argv)


def dispatch(team: str, tick: dict, esc: dict, metrics: str, post: bool) -> dict:
    """The review swarm checks the submitted escalation and writes the dispatch, then it is posted (when acting).
    Runs in the background, so it never delays a submission."""
    SCOPE.set(f"dispatch:{tick['tick_id']}")
    started = time.monotonic()
    report = next(r for r in tick["sector_reports"] if r["sector"] == esc["sector"])
    budget = int(tick.get("swarm_budget", {}).get("max_active_agents", 4))
    verdict, roster, error = None, [], None
    for attempt in (1, 2):
        try:
            with AGENTS.hold(4, budget) as n:
                swarm = ReviewSwarm(report, max_agents=n)
                roster = swarm.roster + ["commander"]
                out = swarm.crew().kickoff(inputs=swarm.inputs(esc["action"]))
            verdict, error = out.pydantic, None
            break
        except Exception as e:
            error = f"attempt {attempt}: {type(e).__name__}: {str(e)[:160]}"
            time.sleep(2)

    message = f"{team} · {esc['sector']} · {esc['action']} · {esc['rationale']}"
    if isinstance(verdict, ReviewVerdict):
        if verdict.agrees:
            message += f" · swarm review ({len(roster)} agents): confirmed, {one_line(verdict.rationale, 140)}"
        else:
            message += (f" · swarm review ({len(roster)} agents): challenged, would {verdict.recommended_action}: "
                        f"{one_line(verdict.rationale, 140)}")
        message += f" · responders: {one_line(verdict.responder_note, 120)}"
    message += f" · {metrics}"
    status = None
    if post:
        try:
            status = post_webhook(message)
        except Exception as e:
            status = f"failed: {type(e).__name__}"
    return {"kind": "dispatch", "tick_id": tick["tick_id"], "message": message, "webhook_status": status,
            "review_roster": roster, "verdict": verdict.model_dump() if isinstance(verdict, ReviewVerdict) else None,
            "review_error": error, "ms": round((time.monotonic() - started) * 1000),
            "partner_calls": LEDGER.drain(f"dispatch:{tick['tick_id']}")}


def main(argv=None) -> int:
    args = parse_args(argv)
    offline = args.fixture is not None
    acting = not offline and not args.dry_run
    feed = FixtureFeed(args.fixture) if offline else LiveFeed()
    team = env("TEAM")
    mode = "fixture" if offline else ("dry-run" if args.dry_run else "LIVE")

    RUNS_DIR.mkdir(exist_ok=True)
    log_path = RUNS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-{mode}.jsonl"
    print(f"[{mode}] team={team} log={log_path.relative_to(RUNS_DIR.parent)}")

    def log(record: dict) -> None:
        with log_path.open("a") as f:
            f.write(json.dumps(record, default=str) + "\n")

    if acting:
        for item in feed.flush_queue():
            print(f"  flushed queued submission tick {item['tick_id']}: {item['judgment']}")

    run_started = time.monotonic()
    dispatches = []
    pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="dispatch")
    for scenario in (args.scenario or feed.scenarios()):
        seen: set = set()
        for _ in range(args.max_ticks):
            LEDGER.drain()
            tick_started = time.monotonic()
            tick, exhausted, raw = feed.get_tick(scenario)
            fetch_ms = round((time.monotonic() - tick_started) * 1000)
            if exhausted or not tick or tick.get("tick_id") in seen:
                print(f"  {scenario}: feed exhausted")
                break
            seen.add(tick["tick_id"])

            flow = TickFlow()
            flow.kickoff(inputs={"tick": tick, "team": team})
            state, final = flow.state, flow.state.final
            decide_ms = round((time.monotonic() - tick_started) * 1000)

            judgment = feed.submit_or_queue(tick["tick_id"], final["primary_action"]) if acting else None
            scored_ms = round((time.monotonic() - tick_started) * 1000)

            budget = tick.get("swarm_budget", {}).get("max_active_agents")
            agents = len(state.roster)
            if state.escalation:
                score = (judgment or {}).get("judgment", {}).get("score")
                took = f"{decide_ms}ms" if decide_ms < 1000 else f"{decide_ms / 1000:.1f}s"
                how = (f"swarm of {agents}/{budget} agents" if agents
                       else "doctrine triage, swarm not needed")
                metrics = (f"tick {tick['tick_id']} · decided in {took} by {how}"
                           + (f" · score {score}" if score is not None else ""))
                job = pool.submit(contextvars.copy_context().run, dispatch, team, tick, state.escalation, metrics, acting)
                dispatches.append(job)

            calls = LEDGER.drain()
            tiers = Counter(t["tier"] for t in state.triage)
            log({
                "kind": "tick", "mode": mode, "scenario": scenario, "tick_id": tick["tick_id"],
                "timings_ms": {"fetch": fetch_ms, **state.timings_ms, "decided": decide_ms, "scored": scored_ms},
                "triage": state.triage, "tiers": dict(tiers),
                "agents_ran": state.roster, "peak_active_agents_process_wide": AGENTS.take_peak(),
                "budget_max_active_agents": budget,
                "llm_calls_on_decision_path": sum(1 for c in calls if c["op"].startswith("chat:")),
                "partner_calls": calls, "partner_call_counts": dict(Counter(c["partner"] for c in calls)),
                "grounding": state.grounding, "reports": state.reports, "proposed": state.proposed,
                "final": final, "gate_overrides": state.overrides, "swarm_error": state.swarm_error,
                "escalation": state.escalation, "submitted": acting, "judgment": judgment,
            })

            sectors = ", ".join(f"{d['sector']}={d['action']}{'!' if d['escalate'] else ''}" for d in final["sectors"])
            print(f"  tick {tick['tick_id']}: {final['primary_action'].upper()} ({final['primary_sector']}) | {sectors}")
            print(f"    tiers={dict(tiers)} agents={state.roster or 'none'} decided={decide_ms}ms "
                  f"scored={scored_ms if acting else '-'}ms calls={dict(Counter(c['partner'] for c in calls))}")
            if state.overrides:
                print(f"    gate overrides: {state.overrides}")
            if state.swarm_error:
                print(f"    swarm error: {state.swarm_error}")
            if judgment is not None:
                print(f"    judgment: {judgment}")

    for job in dispatches:
        result = job.result()
        log(result)
        verb = f"POSTED -> {result['webhook_status']}" if acting else "would post"
        print(f"  dispatch tick {result['tick_id']} ({result['ms']}ms, {verb}): {result['message']}")
    pool.shutdown()
    print(f"  run time: {time.monotonic() - run_started:.1f}s")

    if not offline:
        print("\nScoreboard:")
        board = feed.scoreboard()
        for row in board.get("teams", []):
            marker = " <- us" if row.get("team") == team else ""
            print(f"  {row.get('team'):<28} score={row.get('total_score')} submissions={row.get('submissions')} "
                  f"false_alarms={row.get('false_alarms')}{marker}")
    return 0


def run():
    """Entry point for `crewai run`."""
    sys.exit(main(sys.argv[1:]))


if __name__ == "__main__":
    run()
