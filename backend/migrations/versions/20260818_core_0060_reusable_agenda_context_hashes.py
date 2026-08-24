"""Allow multiple projects to reuse the same frozen Agenda context.

Revision ID: 20260818_core_0060
Revises: 20260818_core_0059
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260818_core_0060"
down_revision: str | None = "20260818_core_0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "research_project_agenda_contexts_context_sha256_key",
        "research_project_agenda_contexts",
        type_="unique",
    )


def downgrade() -> None:
    op.create_unique_constraint(
        "research_project_agenda_contexts_context_sha256_key",
        "research_project_agenda_contexts",
        ["context_sha256"],
    )
