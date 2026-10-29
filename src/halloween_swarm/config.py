"""Environment, model ids and the Parasail LLM factory."""

import os
from pathlib import Path

from crewai import LLM
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

PARASAIL_BASE = "https://api.parasail.io/v1"
BRAIN_MODEL = os.getenv("BRAIN_MODEL", "parasail-glm-53")
FAST_MODEL = os.getenv("FAST_MODEL", "parasail-minimax-m31-flash")
EMBED_MODEL = os.getenv("EMBED_MODEL", "parasail-bge-m3")

DATA_DIR = ROOT / "data"
DOCS_DIR = ROOT / "docs"
RUNS_DIR = ROOT / "runs"
QUEUE_FILE = ROOT / "queue" / "pending_submissions.jsonl"


def env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is empty in .env")
    return value


def parasail_llm(model: str, **kwargs) -> LLM:
    # The OpenAI SDK under CrewAI retries 429s itself and honours Retry-After.
    return LLM(
        model=f"openai/{model}",
        base_url=PARASAIL_BASE,
        api_key=env("PARASAIL_API_KEY"),
        temperature=0,
        max_retries=1,
        **kwargs,
    )


def doctrine() -> str:
    """The distilled doctrine section of docs/doctrine.md (the commander's rulebook)."""
    text = (DOCS_DIR / "doctrine.md").read_text()
    marker = "# Distilled doctrine"
    return text[text.index(marker):] if marker in text else text
