"""Add a monotonic transport cursor to MatrAIx Chat messages.

Revision ID: 20260816_core_0036
Revises: 20260816_core_0035
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260816_core_0036"
down_revision: str | None = "20260816_core_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "matraix_chat_messages",
        sa.Column(
            "event_sequence",
            sa.BigInteger(),
            sa.Identity(always=True),
            nullable=False,
        ),
    )
    op.create_index(
        "uq_chat_messages_event_sequence",
        "matraix_chat_messages",
        ["event_sequence"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_chat_messages_event_sequence",
        table_name="matraix_chat_messages",
    )
    op.drop_column("matraix_chat_messages", "event_sequence")
