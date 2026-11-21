import sqlite3
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import psycopg
from fastapi import FastAPI, Request
from sqlalchemy import Connection, Engine, create_engine, event, make_url
from sqlalchemy.pool import NullPool

from config import Settings, get_settings

DEFAULT_DB_PATH = Path(__file__).parent / "registry.db"

# Primary SQLite error codes caused by the database's environment, not by our code:
# waiting or an operations fix (restore the file, free disk, fix permissions) helps.
_UNAVAILABLE_ERRORS = {
    "SQLITE_CANTOPEN",
    "SQLITE_BUSY",
    "SQLITE_LOCKED",
    "SQLITE_IOERR",
    "SQLITE_NOTADB",
    "SQLITE_CORRUPT",
    "SQLITE_FULL",
    "SQLITE_READONLY",
}

_UNIQUE_PREFIX = "UNIQUE constraint failed: "

# PostgreSQL SQLSTATE classes and codes caused by the database's environment, not by
# our code (connection, resources, operator, system I/O, authorization).
_UNAVAILABLE_SQLSTATE_CLASSES = {"08", "53", "57", "58", "28"}
_UNAVAILABLE_SQLSTATES = {"55P03", "40P01", "25006", "XX001", "XX002", "3D000", "42501"}

# PostgreSQL constraint name -> the same key SQLite reports, so the 409 detail matches.
_UNIQUE_CONSTRAINTS = {"plots_farm_id_name_key": "plots.farm_id, plots.name"}


def is_unavailable(exc: BaseException) -> bool:
    """True when the driver error comes from the database's environment, not our code."""
    if isinstance(exc, sqlite3.Error):
        # sqlite_errorname is the extended name (SQLITE_IOERR_SHORT_READ); keep the primary part.
        name = exc.sqlite_errorname or ""
        return "_".join(name.split("_")[:2]) in _UNAVAILABLE_ERRORS
    if isinstance(exc, psycopg.Error):
        sqlstate = exc.sqlstate
        if sqlstate is None:
            # No SQLSTATE: no connection at all (OperationalError) is an outage; any other
            # client-side error, InterfaceError included (e.g. a closed cursor), is a bug.
            return isinstance(exc, psycopg.OperationalError)
        return sqlstate[:2] in _UNAVAILABLE_SQLSTATE_CLASSES or sqlstate in _UNAVAILABLE_SQLSTATES
    return False


def driver_code(exc: BaseException) -> str:
    """The driver's error code, for the operations log."""
    if isinstance(exc, sqlite3.Error):
        return exc.sqlite_errorname
    if isinstance(exc, psycopg.Error):
        return f"SQLSTATE={exc.sqlstate}"
    return "unknown"


def is_foreign_key_violation(exc: BaseException) -> bool:
    if isinstance(exc, psycopg.Error):
        return exc.sqlstate == "23503"
    return isinstance(exc, sqlite3.Error) and "FOREIGN KEY" in str(exc)


def unique_violation_key(exc: BaseException) -> str | None:
    """The violated UNIQUE columns as "table.col, table.col", or None if not a UNIQUE failure.

    An unknown PostgreSQL UNIQUE constraint gives "", which renders the generic detail.
    """
    if isinstance(exc, psycopg.Error):
        if exc.sqlstate != "23505":
            return None
        return _UNIQUE_CONSTRAINTS.get(exc.diag.constraint_name, "")
    message = str(exc)
    if isinstance(exc, sqlite3.Error) and message.startswith(_UNIQUE_PREFIX):
        return message.removeprefix(_UNIQUE_PREFIX)
    return None


def engine_kwargs(settings: Settings) -> dict[str, Any]:
    backend = make_url(settings.database_url).get_backend_name()
    if backend == "sqlite":
        # NullPool: every request opens the file, so a file deleted or corrupted while
        # the service runs is noticed on the next request. check_same_thread=False:
        # FastAPI may run the dependency and the endpoint on different threadpool
        # threads; the connection is still used by one request only.
        return {
            "poolclass": NullPool,
            "connect_args": {
                "timeout": settings.db_busy_timeout_seconds,
                "check_same_thread": False,
            },
        }
    if backend == "postgresql":
        # Default QueuePool. pre_ping replaces connections the server dropped.
        # lock_timeout is the PostgreSQL counterpart of SQLite's busy timeout.
        return {
            "pool_pre_ping": True,
            "pool_timeout": settings.db_pool_timeout_seconds,
            "connect_args": {
                "connect_timeout": settings.db_connect_timeout_seconds,
                "options": f"-c lock_timeout={round(settings.db_busy_timeout_seconds * 1000)}",
            },
        }
    raise ValueError(f"Unsupported database backend: {backend}")


def make_engine(settings: Settings) -> Engine:
    engine = create_engine(settings.database_url, **engine_kwargs(settings))
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, connection_record) -> None:
            # SQLite turns foreign keys off for every new connection.
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.close()

    return engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Settings are read here, not at import, so tests can set the environment first.
    app.state.engine = make_engine(get_settings())
    yield
    app.state.engine.dispose()


def get_db(request: Request) -> Iterator[Connection]:
    with request.app.state.engine.connect() as conn:
        yield conn
