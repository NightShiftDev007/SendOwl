"""Content addressing for persisted research-run graph memory."""

import json
from hashlib import sha256

from app.research_projects.contracts import ResearchRunGraphMemoryState


def calculate_graph_memory_sha256(memory: ResearchRunGraphMemoryState) -> str:
    canonical = json.dumps(
        memory.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


__all__ = ["calculate_graph_memory_sha256"]
