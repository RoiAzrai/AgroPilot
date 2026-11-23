"""PostgreSQL error handling, tested with fake psycopg errors: no test connects to PostgreSQL."""

import logging
from types import SimpleNamespace

import psycopg
import pytest
import sqlalchemy.exc
from fastapi.testclient import TestClient

import db
from conftest import assert_problem
from main import app
from routers import plots
from test_farms import DEMO_COOPERATIVE
from test_plots import SPEC_BODY
from test_unavailable import assert_internal_error, assert_unavailable

DRIVER_TEXT = "driver-says-something-internal"


def fake_pg_error(
    sqlstate: str | None, constraint_name: str | None = None, base: type | None = None
) -> psycopg.Error:
    """A psycopg error as the driver raises it, without a server.

    psycopg reads sqlstate and diag from the server's result; here both are class
    attributes on a subclass of the class psycopg uses for that SQLSTATE.
    """
    if sqlstate is None:
        parent = base or psycopg.OperationalError
    else:
        parent = psycopg.errors.lookup(sqlstate)
    fake = type(
        f"Fake{parent.__name__}",
        (parent,),
        {"sqlstate": sqlstate, "diag": SimpleNamespace(constraint_name=constraint_name)},
    )
    return fake(f"{DRIVER_TEXT} {sqlstate}")


def operational(orig: psycopg.Error) -> sqlalchemy.exc.OperationalError:
    return sqlalchemy.exc.OperationalError("SELECT 1", {}, orig)


def integrity(orig: psycopg.Error) -> sqlalchemy.exc.IntegrityError:
    return sqlalchemy.exc.IntegrityError("INSERT INTO plots ...", {}, orig)


@pytest.mark.parametrize(
    ("sqlstate", "base", "unavailable"),
    [
        # No connection at all.
        (None, psycopg.OperationalError, True),
        (None, psycopg.InterfaceError, False),
        # The environment: 503.
        ("08006", None, True),
        ("08001", None, True),
        ("53100", None, True),
        ("53300", None, True),
        ("57P01", None, True),
        ("57P03", None, True),
        ("58030", None, True),
        ("55P03", None, True),
        ("40P01", None, True),
        ("25006", None, True),
        ("XX001", None, True),
        ("XX002", None, True),
        ("3D000", None, True),
        ("28P01", None, True),
        ("28000", None, True),
        ("42501", None, True),
        # Bugs: 500.
        (None, psycopg.DataError, False),
        (None, psycopg.ProgrammingError, False),
        ("42P01", None, False),
        ("42601", None, False),
        ("42703", None, False),
        ("23505", None, False),
        ("23503", None, False),
        ("22021", None, False),
    ],
)
def test_postgres_classification(sqlstate, base, unavailable):
    assert db.is_unavailable(fake_pg_error(sqlstate, base=base)) is unavailable


def raising(exc: Exception):
    def dependency():
        raise exc
        yield  # a generator, like get_db

    return dependency


@pytest.fixture
def override_db():
    """Replace get_db on the app; the override is always removed afterwards."""

    def override(dependency) -> None:
        app.dependency_overrides[db.get_db] = dependency

    yield override
    app.dependency_overrides.pop(db.get_db, None)


@pytest.fixture
def server() -> TestClient:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_postgres_unavailable_is_503_over_http(server, override_db, caplog):
    override_db(raising(operational(fake_pg_error("57P01"))))
    with caplog.at_level(logging.WARNING, logger="errors"):
        response = server.get("/v1/farms")
    assert_unavailable(response)
    assert "SQLSTATE=57P01" in caplog.text
    assert DRIVER_TEXT not in response.text
    assert "57P01" not in response.text


def test_postgres_no_connection_is_503_and_logged(server, override_db, caplog):
    override_db(raising(operational(fake_pg_error(None))))
    with caplog.at_level(logging.WARNING, logger="errors"):
        response = server.get("/v1/farms")
    assert_unavailable(response)
    assert "SQLSTATE=None" in caplog.text


def test_postgres_bug_is_500(server, override_db):
    override_db(raising(operational(fake_pg_error("42P01"))))
    response = server.get("/v1/farms")
    assert_internal_error(response)
    assert DRIVER_TEXT not in response.text


def test_pool_exhausted_is_503(server, override_db, caplog):
    override_db(raising(sqlalchemy.exc.TimeoutError("QueuePool limit reached")))
    with caplog.at_level(logging.WARNING, logger="errors"):
        response = server.get("/v1/farms")
    assert_unavailable(response)
    assert "pool exhausted" in caplog.text
    assert "QueuePool" not in response.text


class StubConnection:
    """A connection whose every statement fails with the given error."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    def execute(self, *args, **kwargs):
        raise self.error

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


@pytest.fixture
def failing_writes(server, override_db, monkeypatch):
    """Every statement raises the given error; reference checks are skipped."""
    monkeypatch.setattr(plots, "check_references", lambda conn, values: None)

    def fail_with(error: Exception) -> TestClient:
        def stub():
            yield StubConnection(error)

        override_db(stub)
        return server

    return fail_with


def test_postgres_unique_violation_is_409(failing_writes):
    error = integrity(fake_pg_error("23505", constraint_name="plots_farm_id_name_key"))
    response = failing_writes(error).post("/v1/plots", json=SPEC_BODY)
    body = assert_problem(response, 409, "CONFLICT")
    assert body["detail"] == "A plot with this name already exists in this farm"


def test_postgres_fk_on_plot_write_is_422(failing_writes):
    response = failing_writes(integrity(fake_pg_error("23503"))).post("/v1/plots", json=SPEC_BODY)
    body = assert_problem(response, 422, "VALIDATION")
    assert body["detail"] == "Unknown farm, crop, soil or emitter"


def test_postgres_fk_on_farm_delete_is_409(failing_writes):
    response = failing_writes(integrity(fake_pg_error("23503"))).delete(
        f"/v1/farms/{DEMO_COOPERATIVE}"
    )
    body = assert_problem(response, 409, "CONFLICT")
    assert body["detail"] == "Farm has plots; delete or move them first"


@pytest.mark.parametrize(
    ("orig", "key"),
    [
        (
            fake_pg_error("23505", constraint_name="plots_farm_id_name_key"),
            "plots.farm_id, plots.name",
        ),
        (fake_pg_error("23505", constraint_name="some_other_key"), ""),
        (fake_pg_error("23503", constraint_name="plots_farm_id_fkey"), None),
        (fake_pg_error(None), None),
    ],
)
def test_postgres_unique_violation_key(orig, key):
    assert db.unique_violation_key(orig) == key


def test_farm_delete_with_other_integrity_error_is_not_a_conflict(failing_writes):
    # Only a foreign-key failure means "farm has plots"; any other one must surface as a 500.
    error = integrity(fake_pg_error("23502"))
    response = failing_writes(error).delete(f"/v1/farms/{DEMO_COOPERATIVE}")
    assert_internal_error(response)
