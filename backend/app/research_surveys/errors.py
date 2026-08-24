"""Domain errors for native research surveys."""


class ResearchSurveyNotFoundError(LookupError):
    pass


class ResearchSurveyUnavailableError(RuntimeError):
    pass


class ResearchSurveySelectionError(ValueError):
    pass
