"""Frozen MatrAIx Playwright quote-choice task definition."""

from app.matraix_web.contracts import MatraixWebTask

TASK_ID = "matraix/quotes-playwright-choice"
TASK_VERSION = "1.0.0"
TASK_SCHEMA_VERSION = "matraix-web-task/quote-choice-v1"
PROMPT_SCHEMA_VERSION = "matraix-web-quotes-choice/v1"
RUNNER_VERSION = "1.0.0"
EXECUTOR_SCHEMA_VERSION = "matraix-web-browser-executor/v1"
EXECUTOR_SPEC_SHA256 = "36402fa66241124551503d9998cdef6d73e3b08ee05abca6b6d05a99709a9dc7"
TARGET_ORIGIN = "https://quotes.toscrape.com"
TASK_INSTRUCTION = (
    "Explore the observed public quote catalog as the frozen synthetic Persona and select "
    "the one quote you would most want to save, share, or revisit. Use only text and author "
    "values captured by the fixed Playwright executor."
)
TASK_CONTEXT = (
    "The browser executor reads three consecutive pages from the public Quotes to Scrape "
    "catalog and records exact DOM text plus page screenshots before the Persona chooses."
)
LIMITATIONS = (
    "Quotes to Scrape and this task are source samples, not a production website or "
    "real-user study.",
    "Navigation is a fixed three-page Playwright observation, not a general-purpose "
    "autonomous browser agent.",
    "The final choice and rating are synthetic Persona outputs, not benchmark reward or "
    "human preference data.",
)


def task_without_digest() -> dict[str, object]:
    return {
        "task_id": TASK_ID,
        "version": TASK_VERSION,
        "schema_version": TASK_SCHEMA_VERSION,
        "title": "Quote to save",
        "domain": "arts-culture",
        "source": {
            "kind": "source_sample",
            "project": "MatrAIx",
            "canonical_path": "application/tasks/example-web-playwright_quote-choice",
            "production_sut": False,
        },
        "transport": "playwright_chromium",
        "target_origin": TARGET_ORIGIN,
        "instruction": TASK_INSTRUCTION,
        "context": TASK_CONTEXT,
        "page_count": 3,
        "maximum_quote_count": 60,
        "executor_schema_version": EXECUTOR_SCHEMA_VERSION,
        "executor_spec_sha256": EXECUTOR_SPEC_SHA256,
        "limitations": LIMITATIONS,
    }


def build_web_task() -> MatraixWebTask:
    from app.matraix_web.hashing import calculate_task_spec_sha256

    payload = task_without_digest()
    return MatraixWebTask(
        **payload,
        task_spec_sha256=calculate_task_spec_sha256(payload),
    )
