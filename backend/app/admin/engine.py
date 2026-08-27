"""SQLAlchemy engine for the SQLAdmin console.

The engine must talk to the SAME SQLite database the business API uses, with
the same connection behavior (WAL, foreign keys, busy timeout) so the two
access paths don't diverge on lock/wait semantics.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings


def create_admin_engine():
    """Build an engine + session factory against the app's SQLite database."""
    settings = get_settings()
    url = f"sqlite:///{settings.database_path}"
    engine = create_engine(
        url,
        # SQLAlchemy may hand the DB to worker threads; mirror business config.
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
        future=True,
    )

    # Match the pragmas used by the native connection in db.get_connection().
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA busy_timeout = 5000")
        cursor.close()

    session_maker = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return engine, session_maker
