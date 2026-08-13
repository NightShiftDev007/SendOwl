"""Canonical content addressing for immutable scenarios."""

import json
from hashlib import sha256

from app.scenarios.contracts import ScenarioSnapshotRef, ScenarioVariant


def canonical_scenario_json(
    title: str,
    decision_question: str,
    snapshot: ScenarioSnapshotRef,
    baseline: ScenarioVariant,
    alternatives: tuple[ScenarioVariant, ...],
) -> str:
    """Serialize decision content while excluding generated storage identities."""
    if baseline.position != 0 or baseline.interventions:
        raise ValueError("baseline must be at position zero and contain no interventions")
    if not 1 <= len(alternatives) <= 5:
        raise ValueError("alternatives must contain 1..5 variants")
    alternative_positions = tuple(item.position for item in alternatives)
    if alternative_positions != tuple(range(1, len(alternatives) + 1)):
        raise ValueError("alternative positions must be contiguous and start at one")
    if any(not 1 <= len(item.interventions) <= 20 for item in alternatives):
        raise ValueError("each alternative must contain 1..20 interventions")
    payload = {
        "schema_version": "scenario/v2",
        "title": title,
        "decision_question": decision_question,
        "snapshot": {
            "world_model_id": str(snapshot.world_model_id),
            "world_snapshot_id": str(snapshot.world_snapshot_id),
            "version": snapshot.version,
            "snapshot_sha256": snapshot.snapshot_sha256,
            "evidence_count": snapshot.evidence_count,
        },
        "baseline": {
            "position": baseline.position,
            "name": baseline.name,
            "hypothesis": baseline.hypothesis,
            "interventions": [],
        },
        "alternatives": [
            {
                "position": alternative.position,
                "name": alternative.name,
                "hypothesis": alternative.hypothesis,
                "interventions": [
                    {
                        "position": intervention.position,
                        "kind": intervention.kind,
                        "actor": intervention.actor,
                        "channel": intervention.channel,
                        "content": intervention.content,
                        "offset_minutes": intervention.offset_minutes,
                    }
                    for intervention in alternative.interventions
                ],
            }
            for alternative in alternatives
        ],
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def calculate_scenario_sha256(
    title: str,
    decision_question: str,
    snapshot: ScenarioSnapshotRef,
    baseline: ScenarioVariant,
    alternatives: tuple[ScenarioVariant, ...],
) -> str:
    """Calculate the lowercase SHA-256 address of canonical scenario content."""
    canonical_json = canonical_scenario_json(
        title,
        decision_question,
        snapshot,
        baseline,
        alternatives,
    )
    return sha256(canonical_json.encode("utf-8")).hexdigest()
