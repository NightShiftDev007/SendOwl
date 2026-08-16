"""Explicit semantic world graph failures."""


class WorldGraphError(RuntimeError):
    """Base semantic world graph failure."""


class WorldGraphNotFoundError(WorldGraphError):
    """Raised when a requested graph does not exist."""


class WorldGraphNodeNotFoundError(WorldGraphError):
    """Raised when a requested root node does not belong to the graph."""


class WorldGraphEdgeNotFoundError(WorldGraphError):
    """Raised when a requested edge does not belong to the graph."""


class WorldGraphNotReadyError(WorldGraphError):
    """Raised when a graph slice is requested before extraction succeeds."""


class WorldGraphPersonaSelectionError(WorldGraphError):
    """Raised when a cohort includes a Persona outside the verified match result."""


class WorldGraphPersonaOriginPageOutOfRangeError(WorldGraphError):
    """Raised when a requested cohort-origin page is beyond the verified directory."""


class WorldGraphUnavailableError(WorldGraphError):
    """Raised when no graph-capable model worker is ready."""
