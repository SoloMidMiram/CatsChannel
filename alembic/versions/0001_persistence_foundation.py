"""Create the initial persistence foundation.

Revision ID: 0001_persistence_foundation
Revises:
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001_persistence_foundation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cat_threads",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_provider", sa.String(length=32), nullable=False),
        sa.Column("source_channel_id", sa.String(length=255), nullable=False),
        sa.Column("source_channel_name", sa.String(length=255), nullable=True),
        sa.Column("source_channel_username", sa.String(length=255), nullable=True),
        sa.Column("root_post_id", sa.String(length=36), nullable=True),
        sa.Column("tail_post_id", sa.String(length=36), nullable=True),
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "(root_post_id IS NULL AND tail_post_id IS NULL) OR "
            "(root_post_id IS NOT NULL AND tail_post_id IS NOT NULL)",
            name="ck_cat_threads_root_tail_pair",
        ),
        sa.CheckConstraint("version >= 0", name="ck_cat_threads_version_nonnegative"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_provider", "source_channel_id", name="uq_cat_threads_source"),
    )
    op.create_table(
        "cat_video_submissions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_provider", sa.String(length=32), nullable=False),
        sa.Column("source_media_id", sa.String(length=255), nullable=False),
        sa.Column("source_channel_id", sa.String(length=255), nullable=True),
        sa.Column("thread_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["thread_id"], ["cat_threads.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_provider", "source_media_id", name="uq_cat_submissions_source_media"
        ),
    )
    op.create_index(
        op.f("ix_cat_video_submissions_thread_id"),
        "cat_video_submissions",
        ["thread_id"],
        unique=False,
    )
    op.create_table(
        "cat_posts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("submission_id", sa.String(length=36), nullable=False),
        sa.Column("thread_id", sa.String(length=36), nullable=False),
        sa.Column("parent_post_id", sa.String(length=36), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["parent_post_id"], ["cat_posts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["submission_id"], ["cat_video_submissions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["thread_id"], ["cat_threads.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("submission_id", name="uq_cat_posts_submission"),
    )
    op.create_index(
        "ix_cat_posts_thread_parent",
        "cat_posts",
        ["thread_id", "parent_post_id"],
        unique=False,
    )
    op.create_table(
        "telegram_message_refs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("purpose", sa.String(length=20), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("post_id", sa.String(length=36), nullable=True),
        sa.Column("submission_id", sa.String(length=36), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "(post_id IS NOT NULL AND submission_id IS NULL) OR "
            "(post_id IS NULL AND submission_id IS NOT NULL)",
            name="ck_telegram_message_one_owner",
        ),
        sa.CheckConstraint(
            "purpose IN ('destination', 'private', 'moderation')",
            name="ck_telegram_message_purpose",
        ),
        sa.ForeignKeyConstraint(["post_id"], ["cat_posts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["submission_id"], ["cat_video_submissions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chat_id", "message_id", name="uq_telegram_message_coordinates"),
    )
    op.create_index("ix_telegram_message_post", "telegram_message_refs", ["post_id"], unique=False)
    op.create_index(
        "ix_telegram_message_submission",
        "telegram_message_refs",
        ["submission_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_telegram_message_submission", table_name="telegram_message_refs")
    op.drop_index("ix_telegram_message_post", table_name="telegram_message_refs")
    op.drop_table("telegram_message_refs")
    op.drop_index("ix_cat_posts_thread_parent", table_name="cat_posts")
    op.drop_table("cat_posts")
    op.drop_index(op.f("ix_cat_video_submissions_thread_id"), table_name="cat_video_submissions")
    op.drop_table("cat_video_submissions")
    op.drop_table("cat_threads")
