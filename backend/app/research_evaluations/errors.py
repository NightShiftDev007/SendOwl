"""Research evaluation workspace failures."""


class ResearchEvaluationScopeError(LookupError):
    """Raised when Project and Run do not form one evaluable native scope."""


class ResearchEvaluationRetryError(ValueError):
    """Raised when a Harbor Job cannot create another immutable attempt."""
