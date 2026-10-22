"""durable_publication

Revision ID: 0005_durable_publication
Revises: 0004_bot_submission_intake
Create Date: 2026-10-22 08:01:48.167273
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_durable_publication"
down_revision: str | Sequence[str] | None = "0004_bot_submission_intake"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "publications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("post_id", sa.String(length=36), nullable=False),
        sa.Column("destination_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("current_attempt_id", sa.String(length=36), nullable=True),
        sa.Column("error_category", sa.String(length=64), nullable=True),
        sa.Column("markup_status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("markup_token_digest", sa.String(length=64), nullable=True),
        sa.Column("navigation_post_id", sa.String(length=36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "markup_status IN ('pending','installed','failed')", name="ck_publication_markup"
        ),
        sa.CheckConstraint(
            "state IN ('pending','blocked','sending','confirmed','failed','unknown')",
            name="ck_publication_state",
        ),
        sa.CheckConstraint(
            "state NOT IN ('sending','unknown','confirmed','failed') OR current_attempt_id IS NOT NULL",
            name="ck_publication_attempt",
        ),
        sa.CheckConstraint("version >= 0", name="ck_publication_version"),
        sa.ForeignKeyConstraint(["navigation_post_id"], ["cat_posts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["post_id"], ["cat_posts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("post_id", "destination_chat_id", name="uq_publication_post_chat"),
    )
    op.create_table(
        "publication_attempts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("publication_id", sa.String(length=36), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("claim_token", sa.String(length=36), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=True),
        sa.Column("error_category", sa.String(length=64), nullable=True),
        sa.Column("recovery", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN ('confirmed','failed','unknown')",
            name="ck_publication_attempt_outcome",
        ),
        sa.CheckConstraint("number > 0", name="ck_publication_attempt_number"),
        sa.ForeignKeyConstraint(["publication_id"], ["publications.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("claim_token", name="uq_publication_claim"),
        sa.UniqueConstraint("publication_id", "number", name="uq_publication_attempt_number"),
    )
    op.create_index(
        "uq_destination_post_chat",
        "telegram_message_refs",
        ["post_id", "chat_id"],
        unique=True,
        sqlite_where=sa.text("purpose = 'destination' AND post_id IS NOT NULL"),
        postgresql_where=sa.text("purpose = 'destination' AND post_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_destination_post_chat",
        table_name="telegram_message_refs",
        sqlite_where=sa.text("purpose = 'destination' AND post_id IS NOT NULL"),
        postgresql_where=sa.text("purpose = 'destination' AND post_id IS NOT NULL"),
    )
    op.drop_table("publication_attempts")
    op.drop_table("publications")
