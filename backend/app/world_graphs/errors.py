"""Explicit semantic world graph failures."""


class WorldGraphError(RuntimeError):
    """Base semantic world graph failure."""


class WorldGraphNotFoundError(WorldGraphError):
    """Raised when a requested graph does not exist."""


class WorldGraphNodeNotFoundError(WorldGraphError):
    """Raised when a requested root node does not belong to the graph."""


class WorldGraphNotReadyError(WorldGraphError):
    """Raised when a graph slice is requested before extraction succeeds."""


class WorldGraphUnavailableError(WorldGraphError):
    """Raised when no graph-capable model worker is ready."""
