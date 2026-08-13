"""Deterministic scenario-preference instrument assembly."""

from app.matraix_surveys.contracts import (
    SurveyInstrument,
    SurveyOption,
    SurveyQuestion,
    SurveyVariantRef,
)

INSTRUMENT_SCHEMA_VERSION = "scenario-preference/v1"
PROMPT_SCHEMA_VERSION = "matraix-survey-scenario-preference/v1"
RUNNER_VERSION = "1.0.0"


def instrument_without_digest(
    baseline: SurveyVariantRef,
    alternative: SurveyVariantRef,
) -> dict[str, object]:
    """Return the exact output-affecting questionnaire content."""
    if baseline.role != "baseline" or alternative.role != "alternative":
        raise ValueError("scenario-preference instrument requires baseline then alternative")
    return {
        "schema_version": INSTRUMENT_SCHEMA_VERSION,
        "title": "Scenario preference",
        "description": (
            "Answer as the supplied synthetic persona. Compare the sealed baseline and "
            "alternative; this records a simulated response, not a prediction of real people."
        ),
        "questions": [
            {
                "position": 0,
                "id": "preferred_variant",
                "type": "single_choice",
                "prompt": "Which path would you prefer in this decision scenario?",
                "required": True,
                "options": [
                    {
                        "id": "baseline",
                        "label": baseline.name,
                        "description": baseline.hypothesis,
                    },
                    {
                        "id": "alternative",
                        "label": alternative.name,
                        "description": alternative.hypothesis,
                    },
                ],
                "min_value": None,
                "max_value": None,
            },
            {
                "position": 1,
                "id": "alternative_support",
                "type": "likert",
                "prompt": (
                    f"How strongly would you support the alternative “{alternative.name}”? "
                    "Use 1 for strongly oppose and 5 for strongly support."
                ),
                "required": True,
                "options": [],
                "min_value": 1,
                "max_value": 5,
            },
            {
                "position": 2,
                "id": "primary_reason",
                "type": "free_text",
                "prompt": "What is the main reason for your preference and support rating?",
                "required": True,
                "options": [],
                "min_value": None,
                "max_value": None,
            },
        ],
    }


def build_survey_instrument(
    baseline: SurveyVariantRef,
    alternative: SurveyVariantRef,
) -> SurveyInstrument:
    """Build and content-address the fixed three-question instrument."""
    from app.matraix_surveys.hashing import calculate_survey_instrument_sha256

    payload = instrument_without_digest(baseline, alternative)
    return SurveyInstrument(
        schema_version=INSTRUMENT_SCHEMA_VERSION,
        instrument_sha256=calculate_survey_instrument_sha256(baseline, alternative),
        title="Scenario preference",
        description=str(payload["description"]),
        questions=tuple(
            SurveyQuestion(
                position=int(question["position"]),
                id=str(question["id"]),
                type=str(question["type"]),
                prompt=str(question["prompt"]),
                required=True,
                options=tuple(
                    SurveyOption.model_validate(option) for option in question["options"]
                ),
                min_value=question["min_value"],
                max_value=question["max_value"],
            )
            for question in payload["questions"]
        ),
    )
