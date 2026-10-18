"""Persist requested placement for restart-safe bot intake recovery.

Revision ID: 0004_bot_submission_intake
Revises: 0003_reply_chain_domain
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_bot_submission_intake"
down_revision: str | None = "0003_reply_chain_domain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("cat_video_submissions") as batch:
        batch.add_column(sa.Column("placement_mode", sa.String(length=24), nullable=True))
        batch.add_column(sa.Column("selected_parent_post_id", sa.String(length=36), nullable=True))
        batch.create_check_constraint(
            "ck_cat_submissions_placement",
            "(placement_mode IS NULL AND selected_parent_post_id IS NULL) OR "
            "(placement_mode = 'normal_append' AND selected_parent_post_id IS NULL) OR "
            "(placement_mode = 'interactive_reply' AND selected_parent_post_id IS NOT NULL)",
        )


def downgrade() -> None:
    with op.batch_alter_table("cat_video_submissions") as batch:
        batch.drop_constraint("ck_cat_submissions_placement", type_="check")
        batch.drop_column("selected_parent_post_id")
        batch.drop_column("placement_mode")
