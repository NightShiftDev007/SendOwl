"""Common runtime-validation policy for cross-domain data."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints


class ContractModel(BaseModel):
    """Immutable strict model used at every external and domain boundary."""

    model_config = ConfigDict(
        extra="ignore",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
        revalidate_instances="always",
    )


Identifier = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
        strip_whitespace=True,
    ),
]
NonEmptyText = Annotated[
    str,
    StringConstraints(min_length=1, strip_whitespace=True),
]
LanguageCode = Annotated[
    str,
    StringConstraints(
        min_length=2,
        max_length=16,
        pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$",
        strip_whitespace=True,
    ),
]
Sha256Digest = Annotated[
    str,
    StringConstraints(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
        strip_whitespace=True,
    ),
]
