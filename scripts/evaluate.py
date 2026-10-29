"""Bias and generalisation check: is the system following doctrine, or recalling the three known ticks?

1. Cold start: embeddings recomputed from scratch (no cache from earlier runs).
2. Metamorphic: rename sectors, change tick/facility ids, shuffle sectors, rename hostile entities.
   A memorising system changes its answer; a doctrine-following one does not.
3. Counterfactual: flip one decisive fact in a known tick; the decision must move the way doctrine says.
4. Held-out: seeded random ticks with unseen sector names, unseen entities and fresh readings, scored against a
   doctrine-only reference written independently of the decision code.
5. Ablation: drop the fixture-derived "human-crowd is benign" literal and see whether the swarm still gets the
   control tick right on its own.

Runs the real TickFlow (embeddings, triage, swarm when contested, gate). Never submits or posts.
Usage: python scripts/evaluate.py [--held-out N] [--seed S]
"""

import argparse
import copy
import json
import random
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import halloween_swarm.main  # noqa: E402,F401  (OpenAI warm-up + evidence listener)
from halloween_swarm import gate, signals  # noqa: E402
from halloween_swarm.flow import TickFlow  # noqa: E402

UNSEEN_SECTORS = ["atrium", "loading_dock", "green_room", "mezzanine", "lab_3", "rooftop", "cloakroom", "stairwell_b"]
UNSEEN_HOSTILE = ["banshee", "shade", "wraith", "revenant", "poltergeist", "specter-class-3"]


def run(tick: dict) -> dict:
    flow = TickFlow()
    t0 = time.monotonic()
    flow.kickoff(inputs={"tick": tick, "team": "eval"})
    s = flow.state
    return {"primary": s.final["primary_action"], "sectors": {d["sector"]: (d["action"], d["escalate"]) for d in s.final["sectors"]},
            "tiers": {t["sector"]: t["tier"] for t in s.triage}, "roster": s.roster, "ms": round((time.monotonic() - t0) * 1000),
            "overrides": s.overrides}


def load(name: str) -> list[dict]:
    return json.loads((ROOT / "fixtures" / name).read_text())["ticks"]


# --- reading regimes, defined from physics-style ranges, not from the fixtures -----------------------------------

def reading(regime: str, rng: random.Random) -> dict:
    if regime == "normal":
        return {"emf_milligauss": rng.randint(0, 15), "temp_c": rng.randint(17, 25), "motion_events": rng.randint(0, 70)}
    if regime == "fault":
        return {"emf_milligauss": rng.randint(300, 900), "temp_c": rng.randint(18, 24), "motion_events": 0}
    if regime == "manifestation":
        return {"emf_milligauss": rng.randint(90, 220), "temp_c": rng.randint(-15, 1), "motion_events": rng.randint(12, 45)}
    raise ValueError(regime)


def reference(report: dict, regime: str) -> str | None:
    """Doctrine-only expected action, or None where doctrine needs judgment (scored for consistency instead)."""
    s, status, state = report["sighting"], report["civilian_status"], report["containment_state"]
    hostile = s is not None and s["entity_class"] not in ("residual-echo",) and s["entity_class"] != "human-crowd"
    confirmed = hostile and s["confidence"] >= 0.6
    pinned = "pinned" in status
    if state == "breached" and (pinned or confirmed):
        return "evacuate"                      # doctrine 1
    if state == "breached":
        return None                            # a breach needs judgment, but must never be observed (checked separately)
    if not hostile and status == "clear" and regime in ("normal", "fault"):
        return "observe"                       # doctrine 3/5: nothing hostile, readings normal or a known fault
    return None


def held_out_tick(i: int, rng: random.Random) -> tuple[dict, dict]:
    sectors, regimes = [], {}
    for name in rng.sample(UNSEEN_SECTORS, rng.randint(1, 3)):
        regime = rng.choice(["normal", "normal", "fault", "manifestation"])
        kind = rng.choice(["none", "none", "echo", "hostile_low", "hostile_high"])
        sighting = None
        if kind == "echo":
            sighting = {"entity_class": "residual-echo", "confidence": round(rng.uniform(0.2, 0.95), 2), "witness_count": rng.randint(0, 3)}
        elif kind.startswith("hostile"):
            conf = rng.uniform(0.25, 0.55) if kind == "hostile_low" else rng.uniform(0.65, 0.95)
            sighting = {"entity_class": rng.choice(UNSEEN_HOSTILE), "confidence": round(conf, 2), "witness_count": rng.randint(0, 5)}
        breached = regime == "manifestation" and rng.random() < 0.5
        status = f"{rng.randint(1, 6)} pinned" if breached and rng.random() < 0.6 else "clear"
        sectors.append({"sector": name, "sensors": reading(regime, rng), "sighting": sighting,
                        "civilian_status": status, "containment_state": "breached" if breached else "holding"})
        regimes[name] = regime
    tick = {"tick_id": 50000 + i, "facility_id": "eval-facility", "sector_reports": sectors,
            "swarm_budget": {"max_active_agents": 8, "api_credits_remaining": 1000}}
    return tick, regimes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--held-out", type=int, default=40)
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    report: dict = {}

    # 1. cold start: point the embedding cache at an empty temp file for the whole evaluation
    signals.CACHE_FILE = Path(tempfile.mkdtemp()) / "embed_cache.json"
    known = load("outbreak-level-5.json") + load("control-tick.json")
    expected = {142: "evacuate", 143: "evacuate", 900: "observe"}
    base = {t["tick_id"]: run(t) for t in known}
    report["cold_start"] = {tid: {"primary": r["primary"], "expected": expected[tid], "ok": r["primary"] == expected[tid],
                                  "ms": r["ms"], "llm_agents": r["roster"]} for tid, r in base.items()}

    # 2. metamorphic invariance
    meta = []
    for t in known:
        for k in range(3):
            v = copy.deepcopy(t)
            v["tick_id"] = rng.randint(10**5, 10**6)
            v["facility_id"] = f"facility-{rng.randint(1, 999)}"
            names = rng.sample(UNSEEN_SECTORS, len(v["sector_reports"]))
            mapping = {}
            for r, n in zip(v["sector_reports"], names):
                mapping[n] = r["sector"]
                r["sector"] = n
                if r["sighting"] and r["sighting"]["entity_class"] not in ("residual-echo", "human-crowd"):
                    r["sighting"]["entity_class"] = rng.choice(UNSEEN_HOSTILE)
            rng.shuffle(v["sector_reports"])
            out = run(v)
            same = all(out["sectors"][n][0] == base[t["tick_id"]]["sectors"][orig][0] for n, orig in mapping.items())
            meta.append({"from": t["tick_id"], "variant": k, "same_decisions": same, "primary": out["primary"]})
    report["metamorphic"] = {"variants": len(meta), "unchanged": sum(m["same_decisions"] for m in meta), "detail": meta}

    # 3. counterfactuals on tick 143's coffee bar
    t143 = copy.deepcopy(next(t for t in known if t["tick_id"] == 143))
    cf = []
    def flip(desc, mutate, check):
        v = copy.deepcopy(t143); mutate(v["sector_reports"][0]); out = run(v)
        action = out["sectors"][v["sector_reports"][0]["sector"]][0]
        cf.append({"change": desc, "action": action, "ok": check(action)})
    flip("civilians clear (breach + confirmed level-5 remain)", lambda r: r.update(civilian_status="clear"), lambda a: a == "evacuate")
    flip("civilians clear and containment holding", lambda r: r.update(civilian_status="clear", containment_state="holding"), lambda a: a in ("contain", "evacuate"))
    flip("no sighting, clear, holding, normal readings",
         lambda r: r.update(sighting=None, civilian_status="clear", containment_state="holding",
                            sensors={"emf_milligauss": 4, "temp_c": 21, "motion_events": 30}), lambda a: a == "observe")
    flip("breached, no sighting, nobody pinned", lambda r: r.update(sighting=None, civilian_status="clear"), lambda a: a == "contain")
    report["counterfactual"] = cf

    # 4. held-out random ticks
    rows = []
    for i in range(args.held_out):
        tick, regimes = held_out_tick(i, rng)
        out = run(tick)
        for r in tick["sector_reports"]:
            exp = reference(r, regimes[r["sector"]])
            got, esc = out["sectors"][r["sector"]]
            rows.append({"tick": tick["tick_id"], "sector": r["sector"], "regime": regimes[r["sector"]],
                         "sighting": r["sighting"], "civilians": r["civilian_status"], "containment": r["containment_state"],
                         "expected": exp, "got": got, "escalate": esc, "tier": out["tiers"][r["sector"]],
                         "breach_observed": r["containment_state"] == "breached" and got == "observe",
                         "false_alarm": exp == "observe" and (got != "observe" or esc)})
        rows[-1]["ms"] = out["ms"]
    strict = [r for r in rows if r["expected"]]
    report["held_out"] = {
        "sectors": len(rows), "doctrine_unambiguous": len(strict),
        "agree": sum(r["expected"] == r["got"] for r in strict),
        "false_alarms": sum(r["false_alarm"] for r in rows),
        "breaches_observed": sum(r["breach_observed"] for r in rows),
        "tiers": dict(Counter(r["tier"] for r in rows)),
        "judgment_cases": dict(Counter(f"{r['regime']} readings, {'sighting' if r['sighting'] else 'no sighting'}, {r['containment']} -> {r['got']}"
                                       for r in rows if not r["expected"])),
        "disagreements": [r for r in strict if r["expected"] != r["got"]],
        "rows": rows,
    }

    # 5. ablation: remove the fixture-derived "human-crowd" literal; the swarm must judge the control tick itself
    gate.BENIGN_ENTITY_CLASSES.discard("human-crowd")
    abl = [run(copy.deepcopy(next(t for t in known if t["tick_id"] == 900))) for _ in range(2)]
    gate.BENIGN_ENTITY_CLASSES.add("human-crowd")
    report["ablation_human_crowd"] = [{"primary": a["primary"], "escalate": a["sectors"]["main_stage"][1], "tier": a["tiers"]["main_stage"],
                                       "agents": a["roster"]} for a in abl]

    out_path = ROOT / "docs" / f"evaluation-seed{args.seed}.json"
    out_path.write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps({k: (v if k != "metamorphic" else {x: v[x] for x in ("variants", "unchanged")}) for k, v in report.items()
                      if k != "held_out"}, indent=1, default=str))
    print(json.dumps({k: v for k, v in report["held_out"].items()}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
