"""Evidence gathered in code before any LLM runs: sensor pattern matching (Parasail embeddings) and
sighting grounding (You.com search). Agents receive the results in their prompts, so they spend one
LLM call judging evidence instead of several calling tools."""

import hashlib
import json
import math
from concurrent.futures import ThreadPoolExecutor

from halloween_swarm.config import DATA_DIR, EMBED_MODEL
from halloween_swarm.partners import parasail_embed, you_search

CACHE_FILE = DATA_DIR / ".embed_cache.json"
_grounding_cache: dict[str, dict] = {}


def describe_reading(sensors: dict, containment_state: str) -> str:
    """Readings as text for the embedding model, with coarse words so it has more than digits to go on."""
    emf, temp, motion = sensors.get("emf_milligauss", 0), sensors.get("temp_c", 0), sensors.get("motion_events", 0)
    emf_word = "very high" if emf >= 80 else "high" if emf >= 35 else "elevated" if emf >= 15 else "low"
    temp_word = "freezing" if temp <= 0 else "cold" if temp <= 14 else "normal"
    motion_word = "heavy" if motion >= 25 else "moderate" if motion >= 8 else "little"
    return (f"EMF {emf} milligauss ({emf_word}); temperature {temp} C ({temp_word}); "
            f"{motion} motion events ({motion_word} movement); containment {containment_state}")


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)) or 1.0)


def _key(text: str) -> str:
    return hashlib.sha256(f"{EMBED_MODEL}|{text}".encode()).hexdigest()


def embed_cached(texts: list[str]) -> list[list[float]]:
    """One batched embeddings call for whatever is not cached yet (the reference set is cached after the first run)."""
    cache = json.loads(CACHE_FILE.read_text()) if CACHE_FILE.exists() else {}
    missing = list(dict.fromkeys(t for t in texts if _key(t) not in cache))
    if missing:
        for t, vec in zip(missing, parasail_embed(missing)):
            cache[_key(t)] = vec
        CACHE_FILE.write_text(json.dumps(cache))
    return [cache[_key(t)] for t in texts]


def pattern_match(sector_reports: list[dict]) -> dict[str, dict] | None:
    """Per sector: embedding-weighted threat (0-1) and the nearest labelled patterns. None if embeddings fail."""
    patterns = json.loads((DATA_DIR / "sensor_patterns.json").read_text())["patterns"]
    ref_texts = [describe_reading(p["sensors"], p["containment_state"]) for p in patterns]
    live_texts = [describe_reading(r["sensors"], r["containment_state"]) for r in sector_reports]
    try:
        vecs = embed_cached(ref_texts + live_texts)
    except Exception:
        return None
    ref_vecs, live_vecs = vecs[: len(patterns)], vecs[len(patterns):]

    out = {}
    for report, vec in zip(sector_reports, live_vecs):
        ranked = sorted(((cosine(vec, rv), p) for rv, p in zip(ref_vecs, patterns)), key=lambda x: -x[0])[:3]
        weights = [max(sim, 0.0) ** 4 for sim, _ in ranked]
        threat = sum(w * p["threat"] for w, (_, p) in zip(weights, ranked)) / (sum(weights) or 1.0)
        out[report["sector"]] = {
            "embedding_threat": round(threat, 2),
            "nearest": [{"label": p["label"], "similarity": round(sim, 3)} for sim, p in ranked],
        }
    return out


def ground(entity_class: str, sector: str) -> dict:
    """You.com search with highlights for what an entity class implies. Cached per entity class."""
    key = entity_class.strip().lower()
    if key not in _grounding_cache:
        query = f"{key.replace('-', ' ')} paranormal entity threat {sector.replace('_', ' ')}"
        try:
            _grounding_cache[key] = {"query": query, "results": you_search(query, count=3)}
        except Exception as e:
            return {"query": query, "error": f"{type(e).__name__}: {str(e)[:120]}"}
    return _grounding_cache[key]


def ground_many(sightings: list[tuple[str, str]]) -> dict[str, dict]:
    """Ground several (entity_class, sector) pairs concurrently; keyed by entity class."""
    unique = {e.strip().lower(): (e, s) for e, s in sightings}
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = pool.map(lambda pair: ground(*pair), unique.values())
    return dict(zip(unique, results))
