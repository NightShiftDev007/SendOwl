"""Strict bounded pagination parsing shared by HTTP list routes."""

from typing import Annotated

from fastapi import HTTPException, Request, status
from pydantic import Field

from app.shared.contracts import ContractModel

PAGINATION_QUERY_FIELDS = frozenset({"page", "page_size"})


class PageRequest(ContractModel):
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1, le=50)]


def _query_integer(
    request: Request,
    field: str,
    fallback: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = request.query_params.get(field)
    if raw is None:
        return fallback
    if not raw.isdecimal():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{field} must be an integer",
        )
    value = int(raw)
    if not minimum <= value <= maximum:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{field} must be between {minimum} and {maximum}",
        )
    return value


def parse_page_request(
    request: Request,
    default_page_size: int,
    maximum_page_size: int,
) -> PageRequest:
    unknown = sorted(set(request.query_params) - PAGINATION_QUERY_FIELDS)
    repeated = [
        field
        for field in sorted(PAGINATION_QUERY_FIELDS)
        if len(request.query_params.getlist(field)) > 1
    ]
    if unknown or repeated:
        fragments: list[str] = []
        if unknown:
            fragments.append(f"unknown query fields: {', '.join(unknown)}")
        if repeated:
            fragments.append(f"repeated query fields: {', '.join(repeated)}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="; ".join(fragments),
        )
    return PageRequest(
        page=_query_integer(request, "page", 1, 1, 2_147_483_647),
        page_size=_query_integer(
            request,
            "page_size",
            default_page_size,
            1,
            maximum_page_size,
        ),
    )


__all__ = ["PageRequest", "parse_page_request"]
