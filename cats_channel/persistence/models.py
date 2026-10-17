"""Single SQLAlchemy model owner for the initial CatsChannel schema."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


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
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    source_media_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_channel_id: Mapped[str | None] = mapped_column(String(255))
    thread_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("cat_threads.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")


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
