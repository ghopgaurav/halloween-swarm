"""Structured outputs for every agent in the swarm."""

from typing import Literal

from pydantic import BaseModel, Field

Action = Literal["contain", "evacuate", "observe"]


class SensorFinding(BaseModel):
    sector: str
    threat_score: float = Field(ge=0, le=1)
    pattern: str = Field(description="Closest reference pattern, or your own label if embeddings were unavailable")
    evidence: str


class SensorReport(BaseModel):
    method: Literal["embeddings", "llm-fallback"]
    sectors: list[SensorFinding]


class IntelFinding(BaseModel):
    sector: str
    entity_class: str | None
    credibility: float = Field(ge=0, le=1, description="How credible the sighting is, after grounding")
    likely_decoy: bool
    grounding: str = Field(description="What the search results imply, in one or two sentences")
    sources: list[str] = Field(default_factory=list)


class IntelReport(BaseModel):
    sectors: list[IntelFinding]


class CivilianFinding(BaseModel):
    sector: str
    civilians_at_risk: bool
    pinned_count: int = Field(ge=0)
    note: str


class CivilianReport(BaseModel):
    sectors: list[CivilianFinding]


class SectorDecision(BaseModel):
    sector: str
    action: Action
    escalate: bool
    rationale: str = Field(description="One sentence, at most 160 characters, citing the deciding facts")


class TickDecision(BaseModel):
    sectors: list[SectorDecision]
    primary_sector: str
    primary_action: Action


class ReviewVerdict(BaseModel):
    agrees: bool = Field(description="Whether doctrine and the specialists' reports support the submitted action")
    recommended_action: Action
    rationale: str = Field(description="One sentence, at most 160 characters, citing the deciding facts")
    responder_note: str = Field(description="An instruction of at most 18 words for responders arriving now")
