"""Deterministic safety gate applied after the commander.

It enforces the invariants in docs/doctrine.md ("Distilled doctrine") from tick fields only. It never looks at
tick ids or scenario names, and it never chooses an action the doctrine does not dictate: anything not covered
by an invariant keeps the commander's call.
"""

import re

from halloween_swarm.schemas import SectorDecision, TickDecision

# Doctrine rule 3: residual echoes are passive replay loops; a human crowd is not an entity.
BENIGN_ENTITY_CLASSES = {"human-crowd", "residual-echo"}
# Doctrine rule 4: "verify first". Below this a sighting is not a visual confirmation.
CONFIRMED_CONFIDENCE = 0.6
SEVERITY = {"observe": 0, "contain": 1, "evacuate": 2}
AT_RISK = re.compile(r"(\d+)\s*(pinned|trapped|injured|missing|at risk)", re.I)


def pinned_count(civilian_status: str) -> int:
    return sum(int(m.group(1)) for m in AT_RISK.finditer(civilian_status or ""))


def civilians_clear(civilian_status: str) -> bool:
    return (civilian_status or "").strip().lower() == "clear"


def hostile(sighting: dict | None) -> bool:
    return bool(sighting) and sighting.get("entity_class") not in BENIGN_ENTITY_CLASSES


def confirmed_hostile(sighting: dict | None) -> bool:
    return hostile(sighting) and float(sighting.get("confidence") or 0) >= CONFIRMED_CONFIDENCE


def incident_free(report: dict) -> bool:
    return (not hostile(report.get("sighting")) and report.get("containment_state") != "breached"
            and civilians_clear(report.get("civilian_status", "")))


def facts(report: dict) -> str:
    s, sensors = report.get("sighting"), report.get("sensors", {})
    sighting = f"{s['entity_class']} @{s['confidence']:.2f}" if s else "no sighting"
    return (f"{sighting}, civilians {report.get('civilian_status')}, {report.get('containment_state')}, "
            f"EMF {sensors.get('emf_milligauss')} mG, {sensors.get('temp_c')} C")


def gate_sector(report: dict, proposed: SectorDecision | None) -> tuple[SectorDecision, str | None]:
    """Return the enforced decision and, if the gate changed anything, the rule it applied."""
    sector = report["sector"]
    if report.get("containment_state") == "breached" and pinned_count(report.get("civilian_status", "")) > 0:
        rule = "doctrine 1: pinned civilians in a breached sector -> evacuate and escalate"
        decided = SectorDecision(sector=sector, action="evacuate", escalate=True,
                                 rationale=proposed.rationale if proposed and proposed.action == "evacuate" else f"{facts(report)}")
    elif report.get("containment_state") == "breached" and confirmed_hostile(report.get("sighting")):
        rule = "doctrine 1: confirmed apparition breach -> evacuate and escalate"
        decided = SectorDecision(sector=sector, action="evacuate", escalate=True,
                                 rationale=proposed.rationale if proposed and proposed.action == "evacuate" else f"{facts(report)}")
    elif incident_free(report):
        rule = "doctrine 3/5: no incident -> observe, no escalation"
        decided = SectorDecision(sector=sector, action="observe", escalate=False,
                                 rationale=proposed.rationale if proposed and proposed.action == "observe" else f"{facts(report)}")
    elif proposed is None:
        rule = "gate default: commander gave no decision for this sector"
        action = "contain" if confirmed_hostile(report.get("sighting")) else "observe"
        decided = SectorDecision(sector=sector, action=action, escalate=False, rationale=facts(report))
    elif proposed.action == "evacuate" and not (report.get("containment_state") == "breached"
                                                or confirmed_hostile(report.get("sighting"))):
        rule = "doctrine 4: no evacuation without visual confirmation or a breach"
        action = "contain" if hostile(report.get("sighting")) else "observe"
        decided = SectorDecision(sector=sector, action=action, escalate=False, rationale=proposed.rationale)
    else:
        rule, decided = None, proposed

    if decided.action == "observe" and report.get("containment_state") == "breached":
        rule = (rule + "; " if rule else "") + "doctrine 2 + scoring: a breach is never observed -> contain"
        decided = decided.model_copy(update={"action": "contain"})
    if decided.action == "observe" and decided.escalate:
        rule = (rule + "; " if rule else "") + "doctrine 5: never escalate an observe"
        decided = decided.model_copy(update={"escalate": False})
    changed = proposed is None or decided.model_dump() != proposed.model_dump()
    return decided, (rule if changed else None)


def apply_gate(tick: dict, proposed: TickDecision | None) -> tuple[TickDecision, list[dict]]:
    by_sector = {d.sector: d for d in (proposed.sectors if proposed else [])}
    decisions, overrides = [], []
    for report in tick["sector_reports"]:
        decided, rule = gate_sector(report, by_sector.get(report["sector"]))
        decisions.append(decided)
        if rule:
            overrides.append({"sector": report["sector"], "rule": rule,
                              "from": by_sector[report["sector"]].action if report["sector"] in by_sector else None,
                              "to": decided.action})

    primary = max(decisions, key=lambda d: (SEVERITY[d.action], d.escalate))
    return TickDecision(sectors=decisions, primary_sector=primary.sector, primary_action=primary.action), overrides
