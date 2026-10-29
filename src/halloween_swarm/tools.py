"""Per-agent tools for the review swarm. Each is bound to its agent's slice of the escalated sector, so a tool
can only reach the data its agent is allowed to see."""

import json

from crewai.tools import BaseTool
from pydantic import BaseModel, Field, PrivateAttr

from halloween_swarm.gate import civilians_clear, pinned_count
from halloween_swarm.signals import ground, pattern_match


class NoArgs(BaseModel):
    sector: str = Field(description="The sector to inspect.")


class SensorPatternTool(BaseTool):
    name: str = "sensor_pattern_match"
    description: str = ("Embed the sector's sensor readings with Parasail and compare them with labelled reference "
                        "patterns (normal, sensor fault, residual echo, manifestation). Returns embedding_threat and the nearest patterns.")
    args_schema: type[BaseModel] = NoArgs
    _rows: list[dict] = PrivateAttr()

    def __init__(self, sensor_rows: list[dict], **kwargs):
        super().__init__(**kwargs)
        self._rows = sensor_rows

    def _run(self, sector: str) -> str:
        rows = [r for r in self._rows if r["sector"] == sector] or self._rows
        matches = pattern_match(rows)
        if matches is None:
            return json.dumps({"embeddings_available": False, "instruction": "Judge the raw readings yourself."})
        return json.dumps({"embeddings_available": True, **matches})


class GroundSightingInput(BaseModel):
    entity_class: str = Field(description="The sighting's entity_class, exactly as reported.")
    sector: str = Field(description="The sector the sighting was reported in.")


class GroundSightingTool(BaseTool):
    name: str = "ground_sighting"
    description: str = ("Search the web with You.com (highlights) for what an entity class implies: threat level, "
                        "behaviour, known decoys. Returns titles, URLs and query-relevant passages.")
    args_schema: type[BaseModel] = GroundSightingInput

    def _run(self, entity_class: str, sector: str) -> str:
        return json.dumps(ground(entity_class, sector))


class CivilianRegistryTool(BaseTool):
    name: str = "civilian_registry"
    description: str = ("Parse the sector's civilian status into counts: whether it is clear and how many people are "
                        "pinned, trapped, injured, missing or at risk.")
    args_schema: type[BaseModel] = NoArgs
    _rows: list[dict] = PrivateAttr()

    def __init__(self, civilian_rows: list[dict], **kwargs):
        super().__init__(**kwargs)
        self._rows = civilian_rows

    def _run(self, sector: str) -> str:
        rows = [r for r in self._rows if r["sector"] == sector] or self._rows
        return json.dumps([{**r, "clear": civilians_clear(r["civilian_status"]),
                            "at_risk_count": pinned_count(r["civilian_status"])} for r in rows])
