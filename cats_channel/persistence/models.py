"""Single SQLAlchemy model owner for the initial CatsChannel schema."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class WatchlistControlModel(Base):
    __tablename__ = "watchlist_control"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class WatchlistFields:
    """Columns shared by canonical identities and unresolved requests."""

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    reference: Mapped[str] = mapped_column(String(64), nullable=False)
    handle: Mapped[str | None] = mapped_column(String(64))
    display_name: Mapped[str | None] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(nullable=False, default=False)
    retired: Mapped[bool] = mapped_column(nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence: Mapped[str] = mapped_column(String(32), nullable=False)
    retry_after_seconds: Mapped[int | None] = mapped_column(Integer)
    last_resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    page_budget: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    lookback_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class WatchedChannelModel(WatchlistFields, TimestampMixin, Base):
    __tablename__ = "watched_channels"
    __table_args__ = (
        UniqueConstraint("provider", "channel_id", name="uq_watched_channel_identity"),
        CheckConstraint("provider = 'youtube'", name="ck_watchlist_provider"),
        CheckConstraint("page_budget > 0 AND lookback_days > 0", name="ck_watchlist_policy"),
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="youtube")
    channel_id: Mapped[str] = mapped_column(String(24), nullable=False)


class WatchlistRequestModel(WatchlistFields, TimestampMixin, Base):
    __tablename__ = "watchlist_requests"
    __table_args__ = (
        Index(
            "uq_watchlist_pending_request",
            "reference",
            unique=True,
            sqlite_where=text("channel_entry_id IS NULL"),
            postgresql_where=text("channel_entry_id IS NULL"),
        ),
    )
    channel_entry_id: Mapped[str | None] = mapped_column(ForeignKey("watched_channels.id"))


class WatchlistEventModel(Base):
    __tablename__ = "watchlist_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entry_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    operator: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    handle: Mapped[str | None] = mapped_column(String(64))
    evidence: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False)
    retired: Mapped[bool] = mapped_column(nullable=False)
    page_budget: Mapped[int] = mapped_column(Integer, nullable=False)
    lookback_days: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CatThreadModel(TimestampMixin, Base):
    __tablename__ = "cat_threads"
    __table_args__ = (
        UniqueConstraint("source_provider", "source_channel_id", name="uq_cat_threads_source"),
        CheckConstraint(
            "(root_post_id IS NULL AND tail_post_id IS NULL) OR "
            "(root_post_id IS NOT NULL AND tail_post_id IS NOT NULL)",
            name="ck_cat_threads_root_tail_pair",
        ),
        CheckConstraint("version >= 0", name="ck_cat_threads_version_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    source_channel_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_channel_name: Mapped[str | None] = mapped_column(String(255))
    source_channel_username: Mapped[str | None] = mapped_column(String(255))
    # These are checked by repository membership rules. They intentionally avoid a
    # circular DDL dependency between cat_threads and cat_posts.
    root_post_id: Mapped[str | None] = mapped_column(String(36))
    tail_post_id: Mapped[str | None] = mapped_column(String(36))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class CatVideoSubmissionModel(TimestampMixin, Base):
    __tablename__ = "cat_video_submissions"
    __table_args__ = (
        UniqueConstraint(
            "source_provider", "source_media_id", name="uq_cat_submissions_source_media"
        ),
        CheckConstraint(
            "(placement_mode IS NULL AND selected_parent_post_id IS NULL) OR "
            "(placement_mode = 'normal_append' AND selected_parent_post_id IS NULL) OR "
            "(placement_mode = 'interactive_reply' AND selected_parent_post_id IS NOT NULL)",
            name="ck_cat_submissions_placement",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    source_media_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_channel_id: Mapped[str | None] = mapped_column(String(255))
    source_channel_name: Mapped[str | None] = mapped_column(String(255))
    source_channel_username: Mapped[str | None] = mapped_column(String(255))
    source_identity_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unresolved", server_default="unresolved"
    )
    thread_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("cat_threads.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    media_origin: Mapped[str] = mapped_column(
        String(32), nullable=False, default="legacy", server_default="legacy"
    )
    media_metadata: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    validation_evidence: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    provenance: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    placement_mode: Mapped[str | None] = mapped_column(String(24))
    selected_parent_post_id: Mapped[str | None] = mapped_column(String(36))


class MediaHandoffRequestModel(Base):
    __tablename__ = "media_handoff_requests"
    __table_args__ = (
        UniqueConstraint("token_digest", name="uq_media_handoff_token_digest"),
        CheckConstraint(
            "(consumed_at IS NULL AND submission_id IS NULL) OR "
            "(consumed_at IS NOT NULL AND submission_id IS NOT NULL)",
            name="ck_media_handoff_consumption_pair",
        ),
        Index(
            "ix_media_handoff_binding",
            "actor_id",
            "conversation_chat_id",
            "operation",
        ),
        Index("ix_media_handoff_expiry", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    token_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    conversation_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submission_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("cat_video_submissions.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CatPostModel(Base):
    __tablename__ = "cat_posts"
    __table_args__ = (
        UniqueConstraint("submission_id", name="uq_cat_posts_submission"),
        Index("ix_cat_posts_thread_parent", "thread_id", "parent_post_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    submission_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cat_video_submissions.id", ondelete="RESTRICT"), nullable=False
    )
    thread_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cat_threads.id", ondelete="RESTRICT"), nullable=False
    )
    parent_post_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("cat_posts.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TelegramMessageRefModel(Base):
    __tablename__ = "telegram_message_refs"
    __table_args__ = (
        UniqueConstraint("chat_id", "message_id", name="uq_telegram_message_coordinates"),
        CheckConstraint(
            "purpose IN ('destination', 'private', 'moderation')",
            name="ck_telegram_message_purpose",
        ),
        CheckConstraint(
            "(post_id IS NOT NULL AND submission_id IS NULL) OR "
            "(post_id IS NULL AND submission_id IS NOT NULL)",
            name="ck_telegram_message_one_owner",
        ),
        Index("ix_telegram_message_post", "post_id"),
        Index("ix_telegram_message_submission", "submission_id"),
        Index(
            "uq_destination_post_chat",
            "post_id",
            "chat_id",
            unique=True,
            sqlite_where=text("purpose = 'destination' AND post_id IS NOT NULL"),
            postgresql_where=text("purpose = 'destination' AND post_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    post_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("cat_posts.id", ondelete="RESTRICT")
    )
    submission_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("cat_video_submissions.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PostIntentModel(Base):
    __tablename__ = "post_intents"
    __table_args__ = (
        UniqueConstraint("submission_id", name="uq_post_intents_submission"),
        CheckConstraint(
            "(mode = 'normal_append' AND selected_parent_post_id IS NULL) OR "
            "(mode = 'interactive_reply' AND selected_parent_post_id IS NOT NULL)",
            name="ck_post_intents_mode_parent",
        ),
        Index("ix_post_intents_thread", "thread_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    submission_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cat_video_submissions.id", ondelete="RESTRICT"), nullable=False
    )
    thread_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cat_threads.id", ondelete="RESTRICT"), nullable=False
    )
    mode: Mapped[str] = mapped_column(String(24), nullable=False)
    selected_parent_post_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("cat_posts.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReplyEntryTokenModel(Base):
    __tablename__ = "reply_entry_tokens"
    __table_args__ = (Index("ix_reply_entry_tokens_post", "post_id"),)
    token_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    post_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cat_posts.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PublicationModel(TimestampMixin, Base):
    __tablename__ = "publications"
    __table_args__ = (
        UniqueConstraint("post_id", "destination_chat_id", name="uq_publication_post_chat"),
        CheckConstraint(
            "state IN ('pending','blocked','sending','confirmed','failed','unknown')",
            name="ck_publication_state",
        ),
        CheckConstraint("version >= 0", name="ck_publication_version"),
        CheckConstraint(
            "markup_status IN ('pending','installed','failed')", name="ck_publication_markup"
        ),
        CheckConstraint(
            "state NOT IN ('sending','unknown','confirmed','failed') OR current_attempt_id IS NOT NULL",
            name="ck_publication_attempt",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    post_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cat_posts.id", ondelete="RESTRICT"), nullable=False
    )
    destination_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # Avoid circular DDL; finish always checks publication ID and claim token.
    current_attempt_id: Mapped[str | None] = mapped_column(String(36))
    error_category: Mapped[str | None] = mapped_column(String(64))
    markup_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    markup_token_digest: Mapped[str | None] = mapped_column(String(64))
    navigation_post_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("cat_posts.id", ondelete="RESTRICT")
    )


class ReviewItemModel(TimestampMixin, Base):
    __tablename__ = "review_items"
    __table_args__ = (
        UniqueConstraint("submission_id", "review_chat_id", name="uq_review_submission_chat"),
        UniqueConstraint("review_chat_id", "message_id", name="uq_review_message"),
        CheckConstraint(
            "delivery_state IN ('pending','sending','confirmed','failed','unknown')",
            name="ck_review_delivery",
        ),
        CheckConstraint(
            "decision_state IN ('pending','approving','approved','blocked','needs_reconciliation','rejected')",
            name="ck_review_decision",
        ),
        CheckConstraint("version > 0", name="ck_review_version"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    submission_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cat_video_submissions.id", ondelete="RESTRICT"), nullable=False
    )
    review_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    destination_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    delivery_state: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="pending"
    )
    decision_state: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default="pending"
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    reviewer_id: Mapped[int | None] = mapped_column(BigInteger)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publication_id: Mapped[str | None] = mapped_column(String(36))
    error_category: Mapped[str | None] = mapped_column(String(64))
    decision_action: Mapped[str | None] = mapped_column(String(16))
    rejection_reason: Mapped[str | None] = mapped_column(String(32))


class PublicationAttemptModel(Base):
    __tablename__ = "publication_attempts"
    __table_args__ = (
        UniqueConstraint("publication_id", "number", name="uq_publication_attempt_number"),
        UniqueConstraint("claim_token", name="uq_publication_claim"),
        CheckConstraint("number > 0", name="ck_publication_attempt_number"),
        CheckConstraint(
            "outcome IS NULL OR outcome IN ('confirmed','failed','unknown')",
            name="ck_publication_attempt_outcome",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    publication_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("publications.id", ondelete="RESTRICT"), nullable=False
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    claim_token: Mapped[str] = mapped_column(String(36), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(String(16))
    error_category: Mapped[str | None] = mapped_column(String(64))
    recovery: Mapped[str | None] = mapped_column(String(64))
