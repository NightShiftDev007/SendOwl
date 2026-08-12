"""Canonical content address for complete OASIS platform-smoke inputs."""

import json
from hashlib import sha256

from app.simulations.contracts import CompiledPlatformSmokeInput


def canonical_platform_smoke_input_json(compiled: CompiledPlatformSmokeInput) -> str:
    """Serialize every immutable worker input while excluding resource identity and paths."""
    payload = {
        "schema_version": "oasis-platform-smoke/v1",
        "mode": compiled.mode,
        "scenario": {
            "id": str(compiled.scenario.id),
            "scenario_sha256": compiled.scenario.scenario_sha256,
            "variant_id": str(compiled.scenario.variant_id),
            "variant_name": compiled.scenario.variant_name,
            "world_snapshot_id": str(compiled.scenario.world_snapshot_id),
            "snapshot_sha256": compiled.scenario.snapshot_sha256,
            "company_name": compiled.scenario.company_name,
        },
        "seed": compiled.seed,
        "actor": {
            "agent_id": 0,
            "user_name": compiled.actor_user_name,
            "name": compiled.actor_name,
            "bio": compiled.actor_bio,
        },
        "posts": [
            {
                "position": post.position,
                "content": post.content,
                "offset_minutes": post.offset_minutes,
            }
            for post in compiled.posts
        ],
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def calculate_platform_smoke_input_sha256(compiled: CompiledPlatformSmokeInput) -> str:
    canonical_json = canonical_platform_smoke_input_json(compiled)
    return sha256(canonical_json.encode()).hexdigest()
