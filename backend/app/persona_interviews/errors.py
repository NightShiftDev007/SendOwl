"""Explicit Persona interview domain errors."""


class PersonaInterviewNotFoundError(LookupError):
    """The requested interview or Persona does not exist in the report Cohort."""


class PersonaInterviewUnavailableError(ValueError):
    """The interview cannot be queued because a required runtime is unavailable."""
