"""Explicit company-domain failures translated by the HTTP boundary."""


class CompanyError(RuntimeError):
    """Base error for company persistence and coverage operations."""


class CompanyAliasConflictError(CompanyError):
    """Raised when a normalized match name is already owned by another company."""


class CompanyNotFoundError(CompanyError):
    """Raised when a requested monitored company does not exist."""
