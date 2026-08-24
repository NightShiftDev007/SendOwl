"""Deterministic graph-memory snapshots derived from typed research-run events."""

import hashlib
import json
from collections.abc import Sequence

from oasis_worker.research_contracts import (
    ResearchRunGraphMemoryState,
    ResearchRunMemoryEdge,
    ResearchRunMemoryNode,
)
from oasis_worker.semantic_contracts import SemanticEvent


def graph_memory_sha256(memory: ResearchRunGraphMemoryState) -> str:
    canonical = json.dumps(
        memory.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _clip_label(value: str, limit: int = 500) -> str:
    normalized = " ".join(value.split())
    return normalized if len(normalized) <= limit else normalized[: limit - 1] + "…"


def _actor(event: SemanticEvent) -> tuple[str, str, str]:
    if event.actor_kind == "scenario":
        return "actor:scenario", "scenario", "合成情境发布者"
    if event.persona_id is None:
        raise RuntimeError("Persona graph-memory event has no persona identity")
    return f"actor:persona:{event.persona_id}", "persona", f"Persona {event.agent_position}"


def build_graph_memory(
    run_spec_sha256: str,
    round_number: int,
    first_sequence: int,
    events: Sequence[SemanticEvent],
    previous: ResearchRunGraphMemoryState | None,
    previous_sha256: str | None,
) -> ResearchRunGraphMemoryState:
    """Extend one immutable cumulative graph using only observed typed events."""
    if not events:
        raise ValueError("graph memory requires at least one event")
    if (previous is None) != (round_number == 1):
        raise ValueError("graph memory predecessor does not match the requested round")
    if previous is not None and (
        previous.round != round_number - 1
        or previous.run_spec_sha256 != run_spec_sha256
        or previous_sha256 is None
    ):
        raise ValueError("graph memory predecessor is not contiguous")

    nodes = {item.key: (item.kind, item.label) for item in previous.nodes} if previous else {}
    edges = (
        [
            (item.sequence, item.source_key, item.relation, item.target_key)
            for item in previous.edges
        ]
        if previous
        else []
    )

    def add_node(key: str, kind: str, label: str) -> None:
        if key not in nodes:
            nodes[key] = (kind, _clip_label(label))

    for offset, event in enumerate(events):
        sequence = first_sequence + offset
        actor_key, actor_kind, actor_label = _actor(event)
        add_node(actor_key, actor_kind, actor_label)
        if event.action_type == "create_post":
            if event.post_id is None or event.content is None:
                raise RuntimeError("post graph-memory event is incomplete")
            target_key = f"post:{event.post_id}"
            add_node(target_key, "post", event.content)
            edges.append((sequence, actor_key, "authored", target_key))
        elif event.action_type == "create_comment":
            if event.comment_id is None or event.target_post_id is None or event.content is None:
                raise RuntimeError("comment graph-memory event is incomplete")
            comment_key = f"comment:{event.comment_id}"
            target_key = f"post:{event.target_post_id}"
            add_node(comment_key, "comment", event.content)
            add_node(target_key, "post", f"被引用帖子 {event.target_post_id}")
            edges.append((sequence, actor_key, "authored", comment_key))
            edges.append((sequence, comment_key, "commented_on", target_key))
        elif event.action_type in {"like_post", "dislike_post"}:
            if event.target_post_id is None:
                raise RuntimeError("reaction graph-memory event is incomplete")
            target_key = f"post:{event.target_post_id}"
            add_node(target_key, "post", f"被引用帖子 {event.target_post_id}")
            relation = "liked" if event.action_type == "like_post" else "disliked"
            edges.append((sequence, actor_key, relation, target_key))

    return ResearchRunGraphMemoryState(
        schema_version="sandowl-run-graph-memory/v1",
        run_spec_sha256=run_spec_sha256,
        round=round_number,
        previous_sha256=previous_sha256,
        cumulative_event_count=(previous.cumulative_event_count if previous else 0) + len(events),
        nodes=tuple(
            ResearchRunMemoryNode(position=position, key=key, kind=kind, label=label)
            for position, (key, (kind, label)) in enumerate(nodes.items())
        ),
        edges=tuple(
            ResearchRunMemoryEdge(
                position=position,
                sequence=sequence,
                source_key=source_key,
                relation=relation,
                target_key=target_key,
            )
            for position, (sequence, source_key, relation, target_key) in enumerate(edges)
        ),
    )


__all__ = ["build_graph_memory", "graph_memory_sha256"]
