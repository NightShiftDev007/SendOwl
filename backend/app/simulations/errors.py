"""Explicit platform-smoke domain failures."""

from uuid import UUID


class PlatformSmokeRunNotFoundError(LookupError):
    """Raised when a requested run resource does not exist."""


class PlatformSmokeVariantError(ValueError):
    """Raised when a Scenario variant cannot be compiled as an alternative."""


class PlatformSmokeUnavailableError(RuntimeError):
    """Raised when no recent correctly pinned worker can accept a new run."""


def unknown_variant_error(scenario_id: UUID, variant_id: UUID) -> PlatformSmokeVariantError:
    return PlatformSmokeVariantError(
        f"variant {variant_id} was not found in scenario {scenario_id}"
    )


def baseline_variant_error(scenario_id: UUID, variant_id: UUID) -> PlatformSmokeVariantError:
    return PlatformSmokeVariantError(
        f"variant {variant_id} is the baseline of scenario {scenario_id}; "
        "platform-smoke runs require an alternative"
    )
