"""Version and limitation facts shared by the OASIS control-plane projection."""

OASIS_ENGINE_VERSION = "0.2.5"
CAMEL_ENGINE_VERSION = "0.2.78"
WORKER_HEARTBEAT_MAX_AGE_SECONDS = 30

PLATFORM_SMOKE_LIMITATIONS = (
    "This run verifies OASIS 0.2.5 Reddit platform wiring, SQLite persistence, "
    "and ordered manual CREATE_POST actions only.",
    "CAMEL StubModel is used: no LLM inference, audience behavior, social evolution, "
    "scenario comparison, or decision conclusion is produced.",
    "Intervention offset_minutes values are preserved as input metadata; this manual smoke "
    "executes posts in order without simulating elapsed time.",
    "The seed is fixed and recorded, but OASIS writes runtime timestamps, so separate runs "
    "are not expected to produce byte-identical SQLite files.",
)

OASIS_READINESS_LIMITATIONS = (
    "Readiness proves that a correctly pinned worker recently reached PostgreSQL.",
    "reddit_manual_smoke exercises one controllable company actor and manual CREATE_POST only.",
    "Semantic simulation remains unavailable: no LLM inference, audience agents, social "
    "evolution, comparison, or decision conclusion is produced.",
)
