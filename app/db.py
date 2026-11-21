"""SQLAlchemy engine. SQLite by default, Postgres when DATABASE_URL is set."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

_engine: Engine | None = None
_engine_url: str | None = None
_Session: sessionmaker[Session] | None = None


class Base(DeclarativeBase):
    pass


def reset_engine() -> None:
    global _engine, _engine_url, _Session
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _engine_url = None
    _Session = None


def get_engine() -> Engine:
    global _engine, _engine_url, _Session
    from app.config import get_settings

    url = get_settings().database_url
    if _engine is not None and _engine_url == url:
        return _engine
    if _engine is not None:
        _engine.dispose()
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    elif url.startswith("postgresql") and (":6543" in url or "pgbouncer=true" in url):
        # Supabase's transaction pooler cannot use prepared statements. The
        # session pooler (port 5432) does not need this.
        connect_args["prepare_threshold"] = None
    engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _fk(conn, _record):  # type: ignore[no-untyped-def]
            conn.execute("PRAGMA foreign_keys=ON")

    _engine = engine
    _engine_url = url
    _Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return engine


def get_sessionmaker() -> sessionmaker[Session]:
    get_engine()
    assert _Session is not None
    return _Session


@contextmanager
def session_scope() -> Iterator[Session]:
    db = get_sessionmaker()()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db() -> Iterator[Session]:
    db = get_sessionmaker()()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text, title, clause, content='chunks', content_rowid='pk'
);
"""

FTS_TRIGGERS = [
    """
    CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
        INSERT INTO chunks_fts(rowid, text, title, clause)
        VALUES (new.pk, new.text, new.title, new.clause);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
        INSERT INTO chunks_fts(chunks_fts, rowid, text, title, clause)
        VALUES ('delete', old.pk, old.text, old.title, old.clause);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
        INSERT INTO chunks_fts(chunks_fts, rowid, text, title, clause)
        VALUES ('delete', old.pk, old.text, old.title, old.clause);
        INSERT INTO chunks_fts(rowid, text, title, clause)
        VALUES (new.pk, new.text, new.title, new.clause);
    END;
    """,
]


def _ensure_column(conn, table: str, column: str, ddl: str) -> None:
    dialect = conn.dialect.name
    if dialect == "sqlite":
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        present = {row[1] for row in rows}
    else:
        rows = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = :table"
            ),
            {"table": table},
        ).fetchall()
        present = {row[0] for row in rows}
    if column not in present:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


def init_db() -> None:
    from app import models  # noqa: F401

    engine = get_engine()
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        _ensure_column(conn, "users", "drive_refresh_token", "TEXT DEFAULT ''")
        _ensure_column(conn, "documents", "drive_file_id", "VARCHAR(128) DEFAULT ''")
        _ensure_column(conn, "documents", "storage", "VARCHAR(20) DEFAULT ''")
        _ensure_column(conn, "projects", "equipment", "VARCHAR(120) DEFAULT ''")
        _ensure_column(conn, "chunks", "owner_id", "VARCHAR(36)")
        _ensure_column(conn, "documents", "folder_id", "VARCHAR(36)")
        _ensure_column(conn, "folders", "role", "VARCHAR(40) DEFAULT ''")
        _ensure_column(conn, "folders", "drive_folder_id", "VARCHAR(128) DEFAULT ''")
        _ensure_column(conn, "folders", "owner_id", "VARCHAR(36)")
        _ensure_column(conn, "projects", "drive_folder_id", "VARCHAR(128) DEFAULT ''")
        _ensure_column(conn, "chunks", "folder_role", "VARCHAR(40) DEFAULT ''")
        _ensure_column(conn, "claims", "folder_role", "VARCHAR(40) DEFAULT ''")
    if str(engine.url).startswith("sqlite"):
        with engine.begin() as conn:
            conn.execute(text(FTS_SQL))
            for stmt in FTS_TRIGGERS:
                conn.execute(text(stmt))
    else:
        # Postgres has no FTS5. A GIN index on text would be ideal; for the
        # prototype the lexical path uses ILIKE token search on chunks.
        pass
