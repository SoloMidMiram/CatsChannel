"""Audited terminal rejection using the existing review decision owner."""

import sqlalchemy as sa

from alembic import op

revision = "0007_review_rejection"
down_revision = "0006_review_approval"
branch_labels = None
depends_on = None

OLD = "decision_state IN ('pending','approving','approved','blocked','needs_reconciliation')"
NEW = "decision_state IN ('pending','approving','approved','blocked','needs_reconciliation','rejected')"


def upgrade():
    with op.batch_alter_table("review_items") as batch:
        batch.add_column(sa.Column("decision_action", sa.String(16)))
        batch.add_column(sa.Column("rejection_reason", sa.String(32)))
        batch.drop_constraint("ck_review_decision", type_="check")
        batch.create_check_constraint("ck_review_decision", NEW)
    op.execute("UPDATE review_items SET decision_action='approve' WHERE reviewer_id IS NOT NULL")


def downgrade():
    connection = op.get_bind()
    if connection.scalar(
        sa.text("SELECT count(*) FROM review_items WHERE decision_state='rejected'")
    ):
        raise RuntimeError("Cannot downgrade while audited rejections exist")
    with op.batch_alter_table("review_items") as batch:
        batch.drop_constraint("ck_review_decision", type_="check")
        batch.create_check_constraint("ck_review_decision", OLD)
        batch.drop_column("rejection_reason")
        batch.drop_column("decision_action")
