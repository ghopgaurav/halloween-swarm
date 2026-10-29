"""Tier 0: decide every sector the doctrine already settles, in code, and route only contested sectors to the swarm.

Works from tick fields and the embedding threat only, never tick ids or scenario names.
"""

from dataclasses import asdict, dataclass, field
from typing import Literal

from halloween_swarm.gate import civilians_clear, confirmed_hostile, hostile, incident_free, pinned_count
from halloween_swarm.schemas import SectorDecision

# Embedding threat below this reads as normal activity (the reference set puts residual echoes at 0.3).
QUIET_THREAT = 0.4


@dataclass
class SectorTriage:
    sector: str
    tier: Literal["quiet", "mandated", "contested"]
    reason: str
    embedding_threat: float | None
    nearest: str | None
    needs: list[str] = field(default_factory=list)
    decision: SectorDecision | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["decision"] = self.decision.model_dump() if self.decision else None
        return d


def evidence(report: dict, match: dict | None) -> str:
    """A short, fact-only rationale built from the live tick."""
    s, sensors = report.get("sighting"), report.get("sensors", {})
    parts = []
    if report.get("containment_state") == "breached" and pinned_count(report.get("civilian_status", "")):
        parts.append(f"{report['civilian_status']} in a breached sector")
    elif not civilians_clear(report.get("civilian_status", "")):
        parts.append(f"civilians {report['civilian_status']}")
    parts.append(f"{s['entity_class']} @{s['confidence']:.2f} ({s.get('witness_count', 0)} witnesses)" if s else "no sighting")
    reading = f"EMF {sensors.get('emf_milligauss')} mG, {sensors.get('temp_c')} C"
    if match:
        reading += f" (~'{match['nearest'][0]['label']}')"
    parts.append(reading)
    return "; ".join(parts)


def triage_sector(report: dict, match: dict | None) -> SectorTriage:
    threat = match["embedding_threat"] if match else None
    nearest = match["nearest"][0]["label"] if match else None
    sector, sighting = report["sector"], report.get("sighting")
    status = report.get("civilian_status", "")

    if report.get("containment_state") == "breached" and pinned_count(status) > 0:
        return SectorTriage(sector, "mandated", "doctrine 1: pinned civilians in a breached sector", threat, nearest,
                            decision=SectorDecision(sector=sector, action="evacuate", escalate=True,
                                                    rationale=evidence(report, match)))

    if report.get("containment_state") == "breached" and confirmed_hostile(sighting):
        return SectorTriage(sector, "mandated", "doctrine 1: confirmed apparition breach", threat, nearest,
                            decision=SectorDecision(sector=sector, action="evacuate", escalate=True,
                                                    rationale=evidence(report, match)))

    if incident_free(report) and threat is not None and threat < QUIET_THREAT:
        return SectorTriage(sector, "quiet", "doctrine 3/5: no hostile sighting, holding, clear, normal readings",
                            threat, nearest, decision=SectorDecision(sector=sector, action="observe", escalate=False,
                                                                     rationale=evidence(report, match)))

    needs = []
    if not civilians_clear(status) and pinned_count(status) == 0:
        needs.append("civilian_officer")       # status text the parser cannot settle
    if threat is None or threat >= QUIET_THREAT or report.get("containment_state") == "breached":
        needs.append("sensor_analyst")         # readings anomalous, unknown, or a breach to explain
    if sighting and (hostile(sighting) or (threat or 0) >= QUIET_THREAT):
        needs.append("intel_analyst")          # a sighting whose credibility decides the action
    return SectorTriage(sector, "contested", "needs judgment", threat, nearest, needs=needs or ["sensor_analyst"])


def triage_tick(tick: dict, matches: dict | None) -> list[SectorTriage]:
    return [triage_sector(r, (matches or {}).get(r["sector"])) for r in tick["sector_reports"]]
