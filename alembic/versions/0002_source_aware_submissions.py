"""Add source-aware submission evidence and durable handoffs.

Revision ID: 0002_source_aware_submissions
Revises: 0001_persistence_foundation
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_source_aware_submissions"
down_revision: str | None = "0001_persistence_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "cat_video_submissions",
        sa.Column("source_channel_name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "cat_video_submissions",
        sa.Column("source_channel_username", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "cat_video_submissions",
        sa.Column(
            "source_identity_status",
            sa.String(length=20),
            server_default="unresolved",
            nullable=False,
        ),
    )
    op.add_column(
        "cat_video_submissions",
        sa.Column("media_origin", sa.String(length=32), server_default="legacy", nullable=False),
    )
    op.add_column(
        "cat_video_submissions",
        sa.Column("media_metadata", sa.JSON(), server_default="{}", nullable=False),
    )
    op.add_column(
        "cat_video_submissions",
        sa.Column("validation_evidence", sa.JSON(), server_default="{}", nullable=False),
    )
    op.add_column(
        "cat_video_submissions",
        sa.Column("provenance", sa.JSON(), server_default="{}", nullable=False),
    )
    op.create_table(
        "media_handoff_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.BigInteger(), nullable=False),
        sa.Column("conversation_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submission_id", sa.String(length=36), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "(consumed_at IS NULL AND submission_id IS NULL) OR "
            "(consumed_at IS NOT NULL AND submission_id IS NOT NULL)",
            name="ck_media_handoff_consumption_pair",
        ),
        sa.ForeignKeyConstraint(
            ["submission_id"], ["cat_video_submissions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_digest", name="uq_media_handoff_token_digest"),
    )
    op.create_index(
        "ix_media_handoff_binding",
        "media_handoff_requests",
        ["actor_id", "conversation_chat_id", "operation"],
        unique=False,
    )
    op.create_index(
        "ix_media_handoff_expiry", "media_handoff_requests", ["expires_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_media_handoff_expiry", table_name="media_handoff_requests")
    op.drop_index("ix_media_handoff_binding", table_name="media_handoff_requests")
    op.drop_table("media_handoff_requests")
    op.drop_column("cat_video_submissions", "provenance")
    op.drop_column("cat_video_submissions", "validation_evidence")
    op.drop_column("cat_video_submissions", "media_metadata")
    op.drop_column("cat_video_submissions", "media_origin")
    op.drop_column("cat_video_submissions", "source_identity_status")
    op.drop_column("cat_video_submissions", "source_channel_username")
    op.drop_column("cat_video_submissions", "source_channel_name")
