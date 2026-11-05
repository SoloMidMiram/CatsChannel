"""Canonical approved source registry, unresolved requests and bounded audit."""

import sqlalchemy as sa

from alembic import op

revision = "0008_discovery_watchlist"
down_revision = "0007_review_rejection"
branch_labels = None
depends_on = None


def fields():
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("reference", sa.String(64), nullable=False),
        sa.Column("handle", sa.String(64)),
        sa.Column("display_name", sa.String(255)),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("retired", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("evidence", sa.String(32), nullable=False),
        sa.Column("retry_after_seconds", sa.Integer()),
        sa.Column("last_resolved_at", sa.DateTime(timezone=True)),
        sa.Column("page_budget", sa.Integer(), nullable=False),
        sa.Column("lookback_days", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    ]


def upgrade():
    op.create_table(
        "watchlist_control",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.execute("INSERT INTO watchlist_control (id, version) VALUES (1, 0)")
    op.create_table(
        "watched_channels",
        *fields(),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("channel_id", sa.String(24), nullable=False),
        sa.UniqueConstraint("provider", "channel_id", name="uq_watched_channel_identity"),
        sa.CheckConstraint("provider = 'youtube'", name="ck_watchlist_provider"),
        sa.CheckConstraint("page_budget > 0 AND lookback_days > 0", name="ck_watchlist_policy"),
    )
    op.create_table(
        "watchlist_requests",
        *fields(),
        sa.Column("channel_entry_id", sa.String(36), sa.ForeignKey("watched_channels.id")),
    )
    op.create_index(
        "uq_watchlist_pending_request",
        "watchlist_requests",
        ["reference"],
        unique=True,
        sqlite_where=sa.text("channel_entry_id IS NULL"),
        postgresql_where=sa.text("channel_entry_id IS NULL"),
    )
    op.create_table(
        "watchlist_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entry_id", sa.String(36), nullable=False),
        sa.Column("operator", sa.String(64), nullable=False),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("handle", sa.String(64)),
        sa.Column("evidence", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("retired", sa.Boolean(), nullable=False),
        sa.Column("page_budget", sa.Integer(), nullable=False),
        sa.Column("lookback_days", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_watchlist_events_entry_id", "watchlist_events", ["entry_id"])


def downgrade():
    op.drop_table("watchlist_events")
    op.drop_table("watchlist_requests")
    op.drop_table("watched_channels")
    op.drop_table("watchlist_control")
