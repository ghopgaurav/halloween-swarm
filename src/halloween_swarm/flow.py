"""Per-tick Flow: triage in code, send only contested sectors to the swarm, enforce doctrine, draft the escalation."""

import json
import time

from crewai.flow import Flow, listen, or_, router, start
from pydantic import BaseModel

from halloween_swarm.budget import AGENTS
from halloween_swarm.config import doctrine
from halloween_swarm.crew import HalloweenSwarm
from halloween_swarm.gate import apply_gate, civilians_clear, pinned_count
from halloween_swarm.schemas import SectorDecision, TickDecision
from halloween_swarm.signals import ground_many, pattern_match
from halloween_swarm.triage import triage_tick


class TickState(BaseModel):
    tick: dict = {}
    team: str = ""
    matches: dict | None = None
    triage: list[dict] = []
    roster: list[str] = []
    grounding: dict = {}
    reports: dict = {}
    proposed: dict | None = None
    final: dict = {}
    overrides: list[dict] = []
    escalation: dict | None = None
    swarm_error: str | None = None
    timings_ms: dict = {}


def one_line(text: str, limit: int = 160) -> str:
    """Collapse whitespace and cut at a clause boundary, never mid-word."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for sep in (". ", "; ", ", ", " "):
        if sep in cut[limit // 2:]:
            return cut[: cut.rindex(sep)].rstrip(".;, ")
    return cut


class TickFlow(Flow[TickState]):

    @start()
    def triage(self) -> None:
        started = time.monotonic()
        reports = self.state.tick["sector_reports"]
        self.state.matches = pattern_match(reports)
        self.state.triage = [t.to_dict() for t in triage_tick(self.state.tick, self.state.matches)]
        self.state.timings_ms["triage"] = round((time.monotonic() - started) * 1000)

    @router(triage)
    def route(self) -> str:
        contested = [t for t in self.state.triage if t["tier"] == "contested"]
        budget = int(self.state.tick.get("swarm_budget", {}).get("max_active_agents", 4))
        if not contested:
            return "settled"
        if budget < 2:
            self.state.swarm_error = "swarm_budget.max_active_agents < 2: contested sectors decided by the gate"
            return "settled"
        return "contested"

    @listen("contested")
    def run_swarm(self) -> None:
        started = time.monotonic()
        by_sector = {r["sector"]: r for r in self.state.tick["sector_reports"]}
        contested = [t for t in self.state.triage if t["tier"] == "contested"]
        needed = sorted({n for t in contested for n in t["needs"]})
        budget = int(self.state.tick.get("swarm_budget", {}).get("max_active_agents", 4))
        swarm = HalloweenSwarm(needed=needed, max_active_agents=budget)
        self.state.roster = swarm.roster + ["commander"]

        def wants(name: str) -> list[dict]:
            return [by_sector[t["sector"]] for t in contested if name in t["needs"]]

        intel_rows = [r for r in wants("intel_analyst") if r.get("sighting")]
        if "intel_analyst" in swarm.roster and intel_rows:
            self.state.grounding = ground_many([(r["sighting"]["entity_class"], r["sector"]) for r in intel_rows])

        matches = self.state.matches or {}
        dump = lambda rows: json.dumps(rows, indent=1)
        inputs = {
            "sensor_slice": dump([{"sector": r["sector"], "sensors": r["sensors"], "containment_state": r["containment_state"],
                                   "embedding_match": matches.get(r["sector"])} for r in wants("sensor_analyst")]),
            "sighting_slice": dump([{"sector": r["sector"], "sighting": r["sighting"],
                                     "you_com": self.state.grounding.get(r["sighting"]["entity_class"].strip().lower())}
                                    for r in intel_rows]),
            "civilian_slice": dump([{"sector": r["sector"], "civilian_status": r["civilian_status"],
                                     "containment_state": r["containment_state"]} for r in wants("civilian_officer")]),
            "settled_facts": dump([{
                "sector": t["sector"],
                "containment_state": by_sector[t["sector"]]["containment_state"],
                "civilians": ("clear" if civilians_clear(by_sector[t["sector"]]["civilian_status"])
                              else f"{pinned_count(by_sector[t['sector']]['civilian_status'])} pinned"),
                "embedding_threat": t["embedding_threat"],
                "nearest_pattern": t["nearest"],
                "sighting": ({k: by_sector[t["sector"]]["sighting"][k] for k in ("entity_class", "confidence", "witness_count")}
                             if by_sector[t["sector"]].get("sighting") else None),
            } for t in contested]),
            "sector_names": ", ".join(t["sector"] for t in contested),
            "doctrine": doctrine(),
        }
        for attempt in (1, 2):
            try:
                with AGENTS.hold(len(self.state.roster), budget):
                    out = swarm.crew().kickoff(inputs=inputs)
                break
            except Exception as e:
                self.state.swarm_error = f"attempt {attempt}: {type(e).__name__}: {str(e)[:200]}"
                if attempt == 2:
                    self.state.timings_ms["swarm"] = round((time.monotonic() - started) * 1000)
                    return
                time.sleep(2)
        self.state.swarm_error = None
        self.state.timings_ms["swarm"] = round((time.monotonic() - started) * 1000)
        for t in out.tasks_output:
            self.state.reports[t.name] = t.pydantic.model_dump() if t.pydantic else t.raw
        if isinstance(out.pydantic, TickDecision):
            self.state.proposed = out.pydantic.model_dump()

    @listen(or_("settled", run_swarm))
    def safety_gate(self) -> dict:
        settled = [SectorDecision(**t["decision"]) for t in self.state.triage if t["decision"]]
        swarm_calls = TickDecision(**self.state.proposed).sectors if self.state.proposed else []
        contested_names = {t["sector"] for t in self.state.triage if t["tier"] == "contested"}
        sectors = settled + [d for d in swarm_calls if d.sector in contested_names]
        proposed = TickDecision(sectors=sectors, primary_sector=sectors[0].sector if sectors else "",
                                primary_action=sectors[0].action if sectors else "observe") if sectors else None
        final, overrides = apply_gate(self.state.tick, proposed)
        self.state.final = final.model_dump()
        self.state.overrides = overrides

        primary = next(d for d in final.sectors if d.sector == final.primary_sector)
        if primary.escalate and primary.action != "observe":
            self.state.escalation = {"sector": primary.sector, "action": primary.action,
                                     "rationale": one_line(primary.rationale)}
        return self.state.final
