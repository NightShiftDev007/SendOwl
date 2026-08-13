"""Explicit MatrAIx survey domain failures."""


class MatraixSurveyExperimentNotFoundError(LookupError):
    """Raised when a survey experiment does not exist."""


class MatraixSurveyTrialNotFoundError(LookupError):
    """Raised when a survey trial does not exist."""


class MatraixSurveySelectionError(ValueError):
    """Raised when a sealed Scenario/Cohort selection cannot be surveyed."""


class MatraixSurveyUnavailableError(RuntimeError):
    """Raised when no unique live survey worker configuration is available."""
