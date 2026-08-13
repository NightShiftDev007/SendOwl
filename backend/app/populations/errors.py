"""Explicit population-domain failures translated at the HTTP boundary."""

from uuid import UUID


class PopulationDatasetNotFoundError(LookupError):
    """Raised when a frozen persona dataset does not exist."""


class PopulationCohortNotFoundError(LookupError):
    """Raised when an immutable cohort does not exist."""


class PopulationPersonaSelectionError(ValueError):
    """Raised when selected personas do not belong to the requested dataset."""

    def __init__(self, dataset_id: UUID, missing_persona_ids: tuple[UUID, ...]) -> None:
        if not missing_persona_ids:
            raise ValueError("at least one missing persona ID is required")
        self.dataset_id = dataset_id
        self.missing_persona_ids = missing_persona_ids
        super().__init__(
            f"selected personas are invalid for dataset {dataset_id}; missing persona IDs: "
            + ", ".join(str(persona_id) for persona_id in missing_persona_ids)
        )
