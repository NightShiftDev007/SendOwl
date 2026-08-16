"""Explicit domain errors for MatrAIx chatbot evaluations."""


class MatraixChatEvaluationNotFoundError(LookupError):
    """A sealed chatbot evaluation does not exist."""


class MatraixChatTrialNotFoundError(LookupError):
    """A chatbot trial does not exist."""


class MatraixChatSelectionError(ValueError):
    """The requested task or Cohort cannot be evaluated by this slice."""


class MatraixChatUnavailableError(RuntimeError):
    """No unambiguous live worker can execute the source-sample task."""
