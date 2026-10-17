"""Async engine, session, and explicit application transaction ownership."""

from __future__ import annotations

from types import TracebackType
from typing import Self

from sqlalchemy import event
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
    SqlAlchemyProjectionRepository,
    SqlAlchemySubmissionRepository,
    SqlAlchemyThreadRepository,
)


class SqlAlchemyUnitOfWork:
    """One session and one transaction owned by an application-service call."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._transaction: AsyncTransaction | None = None

    async def __aenter__(self) -> Self:
        self._session = self._session_factory()
        self._transaction = self._session.begin()
        await self._transaction.__aenter__()
        self.submissions = SqlAlchemySubmissionRepository(self._session)
        self.threads = SqlAlchemyThreadRepository(self._session)
        self.projections = SqlAlchemyProjectionRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        if self._session is None or self._transaction is None:
            return None
        try:
            return await self._transaction.__aexit__(exc_type, exc_value, traceback)
        finally:
            await self._session.close()


class Database:
    """Own the async engine and produce explicit units of work."""

    def __init__(self, url: str, *, echo: bool = False) -> None:
        self.engine: AsyncEngine = create_async_engine(url, echo=echo, pool_pre_ping=True)
        if self.engine.url.get_backend_name() == "sqlite":

            @event.listens_for(self.engine.sync_engine, "connect")
            def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
                # Python 3.11 sqlite3 uses legacy transaction control, where a
                # SAVEPOINT can escape the surrounding Session transaction.
                # SQLAlchemy owns BEGIN explicitly so nested repository
                # savepoints retain real unit-of-work rollback semantics.
                dbapi_connection.isolation_level = None
                cursor = dbapi_connection.cursor()
                try:
                    cursor.execute("PRAGMA foreign_keys=ON")
                finally:
                    cursor.close()

            @event.listens_for(self.engine.sync_engine, "begin")
            def _begin_sqlite_transaction(connection) -> None:
                connection.exec_driver_sql("BEGIN")

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
