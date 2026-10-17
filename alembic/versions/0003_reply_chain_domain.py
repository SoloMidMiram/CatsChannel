"""Durable placement intents and reusable opaque reply entries."""

import sqlalchemy as sa

from alembic import op

revision = "0003_reply_chain_domain"
down_revision = "0002_source_aware_submissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "post_intents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "submission_id",
            sa.String(36),
            sa.ForeignKey("cat_video_submissions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "thread_id",
            sa.String(36),
            sa.ForeignKey("cat_threads.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("mode", sa.String(24), nullable=False),
        sa.Column(
            "selected_parent_post_id",
            sa.String(36),
            sa.ForeignKey("cat_posts.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("submission_id", name="uq_post_intents_submission"),
        sa.CheckConstraint(
            "(mode = 'normal_append' AND selected_parent_post_id IS NULL) OR "
            "(mode = 'interactive_reply' AND selected_parent_post_id IS NOT NULL)",
            name="ck_post_intents_mode_parent",
        ),
    )
    op.create_index("ix_post_intents_thread", "post_intents", ["thread_id"])
    op.create_table(
        "reply_entry_tokens",
        sa.Column("token_digest", sa.String(64), primary_key=True),
        sa.Column(
            "post_id",
            sa.String(36),
            sa.ForeignKey("cat_posts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_reply_entry_tokens_post", "reply_entry_tokens", ["post_id"])


def downgrade() -> None:
    op.drop_index("ix_reply_entry_tokens_post", table_name="reply_entry_tokens")
    op.drop_table("reply_entry_tokens")
    op.drop_index("ix_post_intents_thread", table_name="post_intents")
    op.drop_table("post_intents")
