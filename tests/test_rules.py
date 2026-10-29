"""Track 1 rule checks that need no network: triage, safety gate, budget, message format, no hardcoding.

Embedding matches are stubbed so the outcomes are deterministic; the live embedding path is exercised by the
fixture runs.
"""

import copy
import json
import re
from pathlib import Path

import pytest

from halloween_swarm.crew import HalloweenSwarm
from halloween_swarm.flow import one_line
from halloween_swarm.gate import apply_gate
from halloween_swarm.schemas import SectorDecision, TickDecision
from halloween_swarm.signals import pattern_match
from halloween_swarm.triage import QUIET_THREAT, triage_tick

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"


def ticks(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text())["ticks"]


def sector(name="s1", emf=3, temp=21, motion=5, sighting=None, civilians="clear", containment="holding"):
    return {"sector": name, "sensors": {"emf_milligauss": emf, "temp_c": temp, "motion_events": motion},
            "sighting": sighting, "civilian_status": civilians, "containment_state": containment}


def tick(*sectors, budget=8):
    return {"tick_id": 1, "facility_id": "test", "sector_reports": list(sectors),
            "swarm_budget": {"max_active_agents": budget, "api_credits_remaining": 1000}}


def match(threat: float, label: str = "stub") -> dict:
    return {"embedding_threat": threat, "nearest": [{"label": label, "similarity": 0.9}]}


def stub_matches(t: dict, threat_of=lambda r: 0.9 if r["sensors"]["emf_milligauss"] >= 35 else 0.1) -> dict:
    return {r["sector"]: match(threat_of(r)) for r in t["sector_reports"]}


def decide(t: dict, proposed: dict[str, tuple[str, bool]] | None = None, matches=None) -> TickDecision:
    """Triage plus a stub commander for contested sectors, then the gate: the real decision path minus the LLM."""
    tri = triage_tick(t, stub_matches(t) if matches is None else matches)
    decisions = [x.decision for x in tri if x.decision]
    for x in tri:
        if x.tier == "contested" and proposed and x.sector in proposed:
            action, escalate = proposed[x.sector]
            decisions.append(SectorDecision(sector=x.sector, action=action, escalate=escalate, rationale="stub"))
    prop = TickDecision(sectors=decisions, primary_sector=decisions[0].sector, primary_action=decisions[0].action) if decisions else None
    return apply_gate(t, prop)[0]


# --- organizer fixtures: decided in code, no LLM ------------------------------------------------------------

@pytest.mark.parametrize("fixture,tick_id,action,escalate", [
    ("outbreak-level-5.json", 142, "evacuate", True),
    ("outbreak-level-5.json", 143, "evacuate", True),
    ("control-tick.json", 900, "observe", False),
])
def test_organizer_ticks(fixture, tick_id, action, escalate):
    t = next(x for x in ticks(fixture) if x["tick_id"] == tick_id)
    matches = pattern_match(t["sector_reports"])
    if matches is None:
        pytest.skip("embeddings unavailable (no cache and no PARASAIL_API_KEY)")
    tri = triage_tick(t, matches)
    assert all(x.tier != "contested" for x in tri), "clear-cut tick should not need the swarm"
    final = decide(t, matches=matches)
    primary = next(d for d in final.sectors if d.sector == final.primary_sector)
    assert (final.primary_action, primary.escalate) == (action, escalate)


def test_decoy_sectors_never_escalate():
    for t in ticks("outbreak-level-5.json"):
        final = decide(t, {r["sector"]: ("observe", False) for r in t["sector_reports"]})
        for d in final.sectors:
            if d.sector != "catering_coffee_bar":
                assert d.action == "observe" and not d.escalate


# --- doctrine invariants -------------------------------------------------------------------------------------

def test_pinned_in_breach_always_evacuates_even_if_commander_disagrees():
    t = tick(sector(emf=5, sighting=None, civilians="3 injured", containment="breached"))
    for action in ("observe", "contain"):
        final = apply_gate(t, TickDecision(sectors=[SectorDecision(sector="s1", action=action, escalate=False, rationale="x")],
                                           primary_sector="s1", primary_action=action))[0]
        assert final.sectors[0].action == "evacuate" and final.sectors[0].escalate


def test_confirmed_hostile_breach_without_civilians_evacuates():
    """Doctrine 1: evacuate on a confirmed apparition breach, pinned civilians or not."""
    t = tick(sector(emf=120, temp=-6, sighting={"entity_class": "wraith", "confidence": 0.9, "witness_count": 2},
                    containment="breached"))
    assert decide(t, {"s1": ("contain", True)}).sectors[0].action == "evacuate"


def test_a_breach_is_never_observed():
    """Scoring: observing a breach scores 0. Whatever the commander says, a breached sector gets at least contain."""
    t = tick(sector(emf=8, sighting=None, containment="breached"))
    assert decide(t, {"s1": ("observe", False)}).sectors[0].action in ("contain", "evacuate")


def test_residual_echo_is_observed_even_at_high_confidence():
    t = tick(sector(emf=10, sighting={"entity_class": "residual-echo", "confidence": 0.95, "witness_count": 5}))
    final = decide(t)
    assert final.primary_action == "observe" and not final.sectors[0].escalate


def test_observe_never_escalates():
    t = tick(sector(emf=60, sighting={"entity_class": "poltergeist", "confidence": 0.5, "witness_count": 1}))
    final = decide(t, {"s1": ("observe", True)})
    assert final.sectors[0].action == "observe" and not final.sectors[0].escalate


def test_no_evacuation_without_confirmation_or_breach():
    t = tick(sector(emf=60, sighting={"entity_class": "poltergeist", "confidence": 0.4, "witness_count": 1}))
    assert decide(t, {"s1": ("evacuate", True)}).sectors[0].action != "evacuate"


def test_sensor_fault_with_no_sighting_is_quiet():
    t = tick(sector(emf=400, temp=21, motion=0))
    tri = triage_tick(t, {"s1": match(0.15, "sensor fault")})
    assert tri[0].tier == "quiet" and tri[0].decision.action == "observe"


# --- routing: the swarm gets only what needs judgment ---------------------------------------------------------

def test_embeddings_down_routes_to_swarm_instead_of_guessing_quiet():
    t = tick(sector(emf=3))
    tri = triage_tick(t, None)
    assert tri[0].tier == "contested" and "sensor_analyst" in tri[0].needs


def test_unparsed_civilian_status_asks_the_civilian_officer():
    t = tick(sector(emf=80, sighting={"entity_class": "wraith", "confidence": 0.8, "witness_count": 2},
                    civilians="2 unaccounted for"))
    assert "civilian_officer" in triage_tick(t, stub_matches(t))[0].needs


def test_contested_needs_match_the_doubt():
    t = tick(sector("a", emf=70, sighting={"entity_class": "poltergeist", "confidence": 0.6, "witness_count": 2}),
             sector("b", emf=90, sighting=None))
    needs = {x.sector: set(x.needs) for x in triage_tick(t, stub_matches(t))}
    assert needs["a"] == {"sensor_analyst", "intel_analyst"}
    assert needs["b"] == {"sensor_analyst"}


@pytest.mark.parametrize("budget,max_specialists", [(8, 3), (4, 3), (3, 2), (2, 1)])
def test_roster_respects_max_active_agents(budget, max_specialists, monkeypatch):
    monkeypatch.setenv("PARASAIL_API_KEY", "test-not-real")
    swarm = HalloweenSwarm(needed=["civilian_officer", "sensor_analyst", "intel_analyst"], max_active_agents=budget)
    assert len(swarm.roster) == max_specialists and len(swarm.roster) + 1 <= budget


def test_multi_sector_primary_is_most_severe():
    t = tick(sector("calm"), sector("hot", emf=130, civilians="2 pinned", containment="breached"), sector("calm2"))
    final = decide(t)
    assert final.primary_sector == "hot" and final.primary_action == "evacuate"


# --- escalation message and hygiene ---------------------------------------------------------------------------

def test_one_line_cuts_at_a_boundary():
    text = "Telemetry confirms an active manifestation with breach, EMF 98 mG and -4 C; four civilians are pinned " * 3
    cut = one_line(text, 160)
    assert len(cut) <= 160 and not cut.endswith(("…", ",", ";")) and "\n" not in cut


def test_no_tick_ids_or_scenario_names_in_decision_code():
    src = "\n".join(p.read_text() for p in (ROOT / "src" / "halloween_swarm").rglob("*.py"))
    for needle in ("142", "143", "900", "outbreak-level-5", "control-tick", "catering_coffee_bar", "level-5-phantom"):
        assert not re.search(rf"(?<![\w-]){re.escape(needle)}(?![\w-])", src), f"decision code mentions {needle!r}"


def test_no_secrets_in_tracked_files():
    pattern = re.compile(r"discord\.com/api/webhooks/\d+/|ydc-sk-|psk-[A-Za-z0-9]{8,}|sk_live_")
    for p in ROOT.rglob("*"):
        if p.is_file() and ".git" not in p.parts and "tests" not in p.parts and p.name != ".env" and p.suffix in {".py", ".md", ".json", ".yaml", ".toml", ".txt", ".example"}:
            assert not pattern.search(p.read_text(errors="ignore")), f"secret-looking value in {p.relative_to(ROOT)}"
