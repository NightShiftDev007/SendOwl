"""HTTP guard for retired ADC write surfaces kept as read-only archives."""

from fastapi import HTTPException, status

LEGACY_ADC_WRITE_RETIRED_DETAIL = (
    "This legacy ADC write surface is retired. Historical resources remain read-only; "
    "use Research Projects, Simulation Runs, ReportAgent, and Agent Interaction for new work."
)


def reject_legacy_adc_write() -> None:
    """Reject a retired write before opening a database session."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=LEGACY_ADC_WRITE_RETIRED_DETAIL,
    )


__all__ = ["LEGACY_ADC_WRITE_RETIRED_DETAIL", "reject_legacy_adc_write"]
