"""Canonical content addressing for immutable population resources."""

import json
from hashlib import sha256

from app.populations.contracts import CohortTitle, StoredPersonaProfile


def canonical_persona_profile_json(profile: StoredPersonaProfile) -> str:
    """Serialize one validated persona independently of input key order."""
    return json.dumps(
        profile.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def calculate_persona_profile_sha256(profile: StoredPersonaProfile) -> str:
    """Calculate the lowercase SHA-256 address of one persona profile."""
    return sha256(canonical_persona_profile_json(profile).encode("utf-8")).hexdigest()


def canonical_cohort_json(
    title: CohortTitle,
    dataset_sha256: str,
    members: tuple[tuple[str, str], ...],
) -> str:
    """Serialize cohort content while excluding generated storage identities."""
    if not 1 <= len(members) <= 100:
        raise ValueError("cohort members must contain 1..100 personas")
    persona_ids = tuple(persona_id for persona_id, _profile_sha256 in members)
    if len(set(persona_ids)) != len(persona_ids):
        raise ValueError("cohort member persona IDs must be unique")
    payload = {
        "schema": "matraix-cohort/v1",
        "title": title,
        "dataset_sha256": dataset_sha256,
        "persona_count": len(members),
        "members": [
            {
                "persona_id": persona_id,
                "profile_sha256": profile_sha256,
            }
            for persona_id, profile_sha256 in members
        ],
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def calculate_cohort_sha256(
    title: CohortTitle,
    dataset_sha256: str,
    members: tuple[tuple[str, str], ...],
) -> str:
    """Calculate the lowercase SHA-256 address of canonical cohort content."""
    canonical_json = canonical_cohort_json(title, dataset_sha256, members)
    return sha256(canonical_json.encode("utf-8")).hexdigest()
