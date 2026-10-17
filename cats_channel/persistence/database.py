"""Async engine, session, and explicit application transaction ownership."""

from __future__ import annotations

from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    AsyncTransaction,
    async_sessionmaker,
    create_async_engine,
)

from ..config import Settings
from .models import Base
from .repositories import (
    SqlAlchemyHandoffRepository,
    SqlAlchemyProjectionRepository,
    SqlAlchemySubmissionRepository,
    SqlAlchemyThreadRepository,
)
from .sqlite import configure_sqlite_engine


class SqlAlchemyUnitOfWork:
    """One session and one transaction owned by an application-service call."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._transaction: AsyncTransaction | None = None
        self._submissions: SqlAlchemySubmissionRepository | None = None
        self._threads: SqlAlchemyThreadRepository | None = None
        self._projections: SqlAlchemyProjectionRepository | None = None
        self._handoffs: SqlAlchemyHandoffRepository | None = None

    @property
    def submissions(self) -> SqlAlchemySubmissionRepository:
        if self._submissions is None:
            raise RuntimeError("Unit of work is not active")
        return self._submissions

    @property
    def threads(self) -> SqlAlchemyThreadRepository:
        if self._threads is None:
            raise RuntimeError("Unit of work is not active")
        return self._threads

    @property
    def projections(self) -> SqlAlchemyProjectionRepository:
        if self._projections is None:
            raise RuntimeError("Unit of work is not active")
        return self._projections

    @property
    def handoffs(self) -> SqlAlchemyHandoffRepository:
        if self._handoffs is None:
            raise RuntimeError("Unit of work is not active")
        return self._handoffs

    def _clear_state(self) -> None:
        self._session = None
        self._transaction = None
        self._submissions = None
        self._threads = None
        self._projections = None
        self._handoffs = None

    async def __aenter__(self) -> Self:
        if self._session is not None:
            raise RuntimeError("Unit of work is already active")
        session = self._session_factory(close_resets_only=False)
        self._session = session
        try:
            self._transaction = session.begin()
            await self._transaction.__aenter__()
            self._submissions = SqlAlchemySubmissionRepository(session)
            self._threads = SqlAlchemyThreadRepository(session)
            self._projections = SqlAlchemyProjectionRepository(session)
            self._handoffs = SqlAlchemyHandoffRepository(session)
        except BaseException:
            try:
                await session.close()
            finally:
                self._clear_state()
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        session, transaction = self._session, self._transaction
        if session is None or transaction is None:
            return None
        try:
            return await transaction.__aexit__(exc_type, exc_value, traceback)
        finally:
            try:
                await session.close()
            finally:
                self._clear_state()


class Database:
    """Own the async engine and produce explicit units of work."""

    def __init__(self, url: str, *, echo: bool = False) -> None:
        self.engine: AsyncEngine = create_async_engine(url, echo=echo, pool_pre_ping=True)
        configure_sqlite_engine(self.engine.sync_engine)
        self.session_factory = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
            autoflush=False,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> Database:
        return cls(settings.database_url.get_secret_value())

    def unit_of_work(self) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(self.session_factory)

    async def create_schema_for_tests(self) -> None:
        """Create metadata directly only for isolated repository contract tests."""
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        await self.engine.dispose()
