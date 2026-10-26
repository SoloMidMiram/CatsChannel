"""Durable review delivery and explicit approval audit."""

import sqlalchemy as sa

from alembic import op

revision = "0006_review_approval"
down_revision = "0005_durable_publication"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "review_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "submission_id",
            sa.String(36),
            sa.ForeignKey("cat_video_submissions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("review_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("destination_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger()),
        sa.Column("delivery_state", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("decision_state", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("reviewer_id", sa.BigInteger()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("publication_id", sa.String(36)),
        sa.Column("error_category", sa.String(64)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("submission_id", "review_chat_id", name="uq_review_submission_chat"),
        sa.UniqueConstraint("review_chat_id", "message_id", name="uq_review_message"),
        sa.CheckConstraint(
            "delivery_state IN ('pending','sending','confirmed','failed','unknown')",
            name="ck_review_delivery",
        ),
        sa.CheckConstraint(
            "decision_state IN ('pending','approving','approved','blocked','needs_reconciliation')",
            name="ck_review_decision",
        ),
        sa.CheckConstraint("version > 0", name="ck_review_version"),
    )


def downgrade():
    op.drop_table("review_items")
