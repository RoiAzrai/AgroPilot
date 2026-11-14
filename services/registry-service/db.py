import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).parent / "registry.db"

# How long a connection waits for another process's lock before SQLITE_BUSY.
# Read at connect time, so tests can lower it.
BUSY_TIMEOUT_SECONDS = 5.0

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


def is_unavailable(exc: sqlite3.Error) -> bool:
    # sqlite_errorname is the extended name (SQLITE_IOERR_SHORT_READ); keep the primary part.
    name = exc.sqlite_errorname or ""
    return "_".join(name.split("_")[:2]) in _UNAVAILABLE_ERRORS


def db_path() -> Path:
    return Path(os.environ.get("REGISTRY_DB_PATH", DEFAULT_DB_PATH))


def connect() -> sqlite3.Connection:
    # mode=rw fails on a missing file instead of silently creating an empty database.
    # check_same_thread=False: FastAPI may run the dependency and the endpoint on
    # different threadpool threads; the connection is still used by one request only.
    conn = sqlite3.connect(
        f"{db_path().resolve().as_uri()}?mode=rw",
        uri=True,
        timeout=BUSY_TIMEOUT_SECONDS,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    # SQLite turns foreign keys off for every new connection.
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
