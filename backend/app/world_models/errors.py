"""Explicit world-model failures translated at the HTTP boundary."""

from uuid import UUID


class WorldModelError(RuntimeError):
    """Base failure for world-model persistence operations."""


class WorldModelNotFoundError(WorldModelError):
    """Raised when a requested persistent world model does not exist."""


class WorldSnapshotNotFoundError(WorldModelError):
    """Raised when a snapshot is not owned by the requested world model."""


class WorldSnapshotEvidenceNotFoundError(WorldModelError):
    """Raised when a frozen snapshot does not contain a requested article."""


class WorldSnapshotPolicyEvidenceNotFoundError(WorldModelError):
    """Raised when a frozen snapshot does not contain a requested Policy version."""


class SnapshotPolicyEvidenceSelectionError(WorldModelError):
    """Raised when selected immutable Policy versions cannot be frozen exactly."""

    def __init__(
        self,
        missing_policy_version_ids: tuple[UUID, ...],
        mismatched_policy_version_ids: tuple[UUID, ...],
    ) -> None:
        self.missing_policy_version_ids = missing_policy_version_ids
        self.mismatched_policy_version_ids = mismatched_policy_version_ids
        reasons: list[str] = []
        if missing_policy_version_ids:
            reasons.append(
                "missing Policy version IDs: "
                + ", ".join(str(value) for value in missing_policy_version_ids)
            )
        if mismatched_policy_version_ids:
            reasons.append(
                "version_sha256 mismatch for Policy version IDs: "
                + ", ".join(str(value) for value in mismatched_policy_version_ids)
            )
        if not reasons:
            raise ValueError("at least one invalid Policy version ID is required")
        super().__init__("selected Policy evidence is invalid; " + "; ".join(reasons))


class WorldSnapshotRevisionConflictError(WorldModelError):
    """Raised when selected articles changed after a user reviewed media evidence."""

    def __init__(self, stale_article_ids: tuple[UUID, ...]) -> None:
        if not stale_article_ids:
            raise ValueError("at least one stale evidence article ID is required")
        self.stale_article_ids = stale_article_ids
        super().__init__(
            "selected evidence revisions are stale; article IDs whose "
            "evidence_revision_sha256 changed: "
            + ", ".join(str(value) for value in stale_article_ids)
        )


class SnapshotEvidenceLimitError(WorldModelError):
    """Raised when snapshot capture would exceed an explicit resource bound."""

    def __init__(
        self,
        resource: str,
        article_ids: tuple[UUID, ...],
        actual: int,
        limit: int,
    ) -> None:
        if not resource.strip():
            raise ValueError("snapshot evidence limit resource must be non-empty")
        if not article_ids:
            raise ValueError("snapshot evidence limit must identify at least one article")
        if actual <= limit:
            raise ValueError(
                f"snapshot evidence limit requires actual > limit; actual={actual}, limit={limit}"
            )
        self.resource = resource
        self.article_ids = article_ids
        self.actual = actual
        self.limit = limit
        super().__init__(
            "snapshot evidence limit exceeded; "
            f"resource: {resource}; article IDs: "
            + ", ".join(str(value) for value in article_ids)
            + f"; actual: {actual}; limit: {limit}"
        )


class SnapshotEvidenceSelectionError(WorldModelError):
    """Raised when selected media cannot form an exact verified snapshot."""

    def __init__(
        self,
        missing_article_ids: tuple[UUID, ...],
        duplicate_article_ids: tuple[UUID, ...],
    ) -> None:
        self.missing_article_ids = missing_article_ids
        self.duplicate_article_ids = duplicate_article_ids
        reasons: list[str] = []
        if missing_article_ids:
            reasons.append(
                "missing article IDs: " + ", ".join(str(value) for value in missing_article_ids)
            )
        if duplicate_article_ids:
            reasons.append(
                "duplicate media row article IDs: "
                + ", ".join(str(value) for value in duplicate_article_ids)
            )
        if not reasons:
            raise ValueError("at least one invalid evidence article ID is required")
        super().__init__("selected evidence is invalid; " + "; ".join(reasons))
