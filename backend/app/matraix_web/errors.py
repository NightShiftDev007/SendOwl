"""Explicit failures for MatrAIx Web control-plane operations."""


class MatraixWebUnavailableError(RuntimeError):
    pass


class MatraixWebSelectionError(ValueError):
    pass


class MatraixWebEvaluationNotFoundError(LookupError):
    pass


class MatraixWebTrialNotFoundError(LookupError):
    pass


class MatraixWebScreenshotNotFoundError(LookupError):
    pass
