"""Explicit failures for single-run research projects."""


class ResearchProjectNotFoundError(LookupError):
    """Raised when a research project does not exist."""


class ResearchSimulationRunNotFoundError(LookupError):
    """Raised when a configured research simulation run does not exist."""
