"""Durable discovery scan state and expiring observations."""

import sqlalchemy as sa

from alembic import op

revision = "0009_discovery_ledger"
down_revision = "0008_discovery_watchlist"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "discovery_candidates",
        sa.Column("provider", sa.String(32), primary_key=True),
        sa.Column("video_id", sa.String(11), primary_key=True),
        sa.Column(
            "watchlist_id", sa.String(36), sa.ForeignKey("watched_channels.id"), nullable=False
        ),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current", sa.JSON(), nullable=False),
    )
    op.create_table(
        "discovery_observations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("video_id", sa.String(11), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["provider", "video_id"],
            ["discovery_candidates.provider", "discovery_candidates.video_id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("provider", "video_id", "observed_at", name="uq_discovery_observation"),
    )
    op.create_table(
        "discovery_scan_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "watchlist_id", sa.String(36), sa.ForeignKey("watched_channels.id"), nullable=False
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("cycle", sa.String(36), nullable=False),
        sa.Column("owner", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("watchlist_version", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("items", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("requests", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("watchlist_id", "provider", "cycle", name="uq_discovery_scan_cycle"),
    )
    op.create_table(
        "discovery_checkpoints",
        sa.Column(
            "watchlist_id", sa.String(36), sa.ForeignKey("watched_channels.id"), primary_key=True
        ),
        sa.Column("provider", sa.String(32), primary_key=True),
        sa.Column(
            "run_id", sa.String(36), sa.ForeignKey("discovery_scan_runs.id", ondelete="SET NULL")
        ),
        sa.Column("cursor", sa.String(2048)),
        sa.Column("seen_cursors", sa.JSON(), nullable=False),
        sa.Column("coverage_through", sa.DateTime(timezone=True)),
        sa.Column("last_full_scan_at", sa.DateTime(timezone=True)),
    )


def downgrade():
    op.drop_table("discovery_checkpoints")
    op.drop_table("discovery_scan_runs")
    op.drop_table("discovery_observations")
    op.drop_table("discovery_candidates")
