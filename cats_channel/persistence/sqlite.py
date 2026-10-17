"""Shared SQLite transaction control for application and migration engines."""

from sqlalchemy import Engine, event


def configure_sqlite_engine(engine: Engine) -> None:
    """Let SQLAlchemy own BEGIN, including DDL and nested savepoints."""
    if engine.url.get_backend_name() != "sqlite":
        return

    @event.listens_for(engine, "connect")
    def _configure_connection(dbapi_connection, _connection_record) -> None:
        # Disable sqlite3's legacy transaction control on Python 3.11 too.
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    @event.listens_for(engine, "begin")
    def _begin_transaction(connection) -> None:
        connection.exec_driver_sql("BEGIN")
