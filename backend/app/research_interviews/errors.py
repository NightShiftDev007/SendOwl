"""Domain errors for run-grounded Persona interviews."""


class ResearchInterviewNotFoundError(LookupError):
    """The requested interview resource does not exist in its frozen scope."""


class ResearchInterviewUnavailableError(ValueError):
    """The requested interview cannot be created from the current run state."""
