import io
import logging
import sqlite3
from pathlib import Path

import boto3
import pytest
from botocore.exceptions import ClientError, NoCredentialsError, ReadTimeoutError
from fastapi.testclient import TestClient

from conftest import assert_problem, sqlite_url
from main import app
from routers import plots
from test_plots import NORTH_BLOCK

FARM = "b7e2c0a0-3c1d-4f0a-9a11-0c5d2e6f1001"  # North block's farm
KEY = f"{FARM}/{NORTH_BLOCK}/photo"
UNKNOWN_PLOT = "00000000-0000-4000-8000-000000000000"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


def access_denied(operation: str) -> ClientError:
    return ClientError({"Error": {"Code": "AccessDenied", "Message": "Access Denied"}}, operation)


class FakeS3:
    """Stands in for the boto3 S3 client. `fail_put` / `fail_get` make the next call raise."""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], tuple[bytes, str]] = {}
        self.clients_created = 0
        self.calls: list[str] = []
        self.fail_put: Exception | None = None
        self.fail_get: Exception | None = None
        self.on_put = None

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str) -> dict:
        self.calls.append("put_object")
        if self.fail_put:
            raise self.fail_put
        if self.on_put:
            self.on_put()
        self.objects[(Bucket, Key)] = (Body, ContentType)
        return {}

    def get_object(self, *, Bucket: str, Key: str) -> dict:
        self.calls.append("get_object")
        if self.fail_get:
            raise self.fail_get
        if (Bucket, Key) not in self.objects:
            raise access_denied("GetObject")  # what S3 answers without s3:ListBucket
        body, content_type = self.objects[(Bucket, Key)]
        return {"Body": io.BytesIO(body), "ContentType": content_type}


@pytest.fixture
def s3(monkeypatch) -> FakeS3:
    fake = FakeS3()

    def make_client(settings):
        fake.clients_created += 1
        return fake

    monkeypatch.setattr(plots, "_s3_client", make_client)
    return fake


def upload(client: TestClient, plot_id: str = NORTH_BLOCK, data: bytes = PNG, content_type="image/png"):
    return client.post(
        f"/v1/plots/{plot_id}/photo", files={"file": ("photo", data, content_type)}
    )


def stored(db_file: Path) -> list[tuple]:
    con = sqlite3.connect(db_file)
    try:
        return con.execute("SELECT plot_id, key, content_type FROM plot_photos").fetchall()
    finally:
        con.close()


# --- POST /v1/plots/{id}/photo -------------------------------------------------------


@pytest.mark.parametrize("content_type", ["image/jpeg", "image/png", "image/webp"])
def test_upload_returns_201_and_stores_key(client, db_file, s3, content_type):
    response = upload(client, content_type=content_type)
    assert response.status_code == 201
    assert response.json() == {"plot_id": NORTH_BLOCK, "key": KEY, "content_type": content_type}
    assert s3.objects == {("test-bucket", KEY): (PNG, content_type)}
    assert stored(db_file) == [(NORTH_BLOCK, KEY, content_type)]


def test_reupload_overwrites(client, db_file, s3):
    assert upload(client).status_code == 201
    response = upload(client, data=JPEG, content_type="image/jpeg")
    assert response.status_code == 201
    assert response.json() == {"plot_id": NORTH_BLOCK, "key": KEY, "content_type": "image/jpeg"}
    assert s3.objects == {("test-bucket", KEY): (JPEG, "image/jpeg")}
    assert stored(db_file) == [(NORTH_BLOCK, KEY, "image/jpeg")]


def test_upload_of_exactly_5_mb_is_accepted(client, s3):
    assert upload(client, data=b"x" * plots.MAX_PHOTO_BYTES).status_code == 201


@pytest.mark.parametrize("plot_id", [UNKNOWN_PLOT, "not-a-uuid"])
def test_upload_to_unknown_plot_is_404(client, db_file, s3, plot_id):
    body = assert_problem(upload(client, plot_id=plot_id), 404, "NOT_FOUND")
    assert body["detail"] == "Plot not found"
    assert s3.clients_created == 0
    assert stored(db_file) == []


@pytest.mark.parametrize(
    ("data", "content_type", "detail"),
    [
        (b"", "image/png", "Photo is empty"),
        (PNG, "text/plain", "Photo must be image/jpeg, image/png or image/webp"),
        (PNG, "image/gif", "Photo must be image/jpeg, image/png or image/webp"),
        (b"x" * (plots.MAX_PHOTO_BYTES + 1), "image/png", "Photo is larger than 5 MB"),
    ],
    ids=["empty", "text", "gif", "too-big"],
)
def test_invalid_photo_is_422_without_calling_s3(client, db_file, s3, data, content_type, detail):
    body = assert_problem(upload(client, data=data, content_type=content_type), 422, "VALIDATION")
    assert body["detail"] == detail
    assert s3.clients_created == 0
    assert stored(db_file) == []


def test_missing_file_field_is_422(client, s3):
    response = client.post(f"/v1/plots/{NORTH_BLOCK}/photo", files={"other": ("x", PNG, "image/png")})
    body = assert_problem(response, 422, "VALIDATION")
    assert "file" in body["detail"]
    assert s3.clients_created == 0


@pytest.mark.parametrize(
    "error", [access_denied("PutObject"), NoCredentialsError()], ids=["client-error", "no-credentials"]
)
def test_s3_failure_on_upload_is_503_and_keeps_stored_key(client, db_file, s3, caplog, error):
    assert upload(client).status_code == 201
    s3.fail_put = error
    with caplog.at_level(logging.WARNING, logger="routers.plots"):
        response = upload(client, data=JPEG, content_type="image/jpeg")
    body = assert_problem(response, 503, "UNAVAILABLE")
    assert body["detail"] == "Photo storage unavailable"
    assert response.headers["retry-after"] == "5"
    assert stored(db_file) == [(NORTH_BLOCK, KEY, "image/png")]
    assert "S3 upload failed" in caplog.text
    assert type(error).__name__ in caplog.text


def test_s3_failure_on_first_upload_stores_nothing(client, db_file, s3):
    s3.fail_put = NoCredentialsError()
    assert_problem(upload(client), 503, "UNAVAILABLE")
    assert stored(db_file) == []


def test_plot_deleted_during_upload_is_404(client, db_file, s3):
    def delete_plot() -> None:
        con = sqlite3.connect(db_file)
        con.execute("DELETE FROM plots WHERE id = ?", (NORTH_BLOCK,))
        con.commit()
        con.close()

    s3.on_put = delete_plot
    body = assert_problem(upload(client), 404, "NOT_FOUND")
    assert body["detail"] == "Plot not found"
    assert stored(db_file) == []


def test_other_integrity_error_on_upload_is_not_404(db_file, s3):
    with TestClient(app, raise_server_exceptions=False) as client:
        # After startup, which creates plot_photos: an IntegrityError that is not a FK.
        con = sqlite3.connect(db_file)
        con.execute(
            "CREATE TRIGGER refuse_photo BEFORE INSERT ON plot_photos"
            " BEGIN SELECT RAISE(ABORT, 'refused'); END"
        )
        con.commit()
        con.close()
        response = upload(client)
    assert_problem(response, 500, "UNAVAILABLE")


# --- GET /v1/plots/{id}/photo --------------------------------------------------------


def test_get_returns_the_photo(client, s3):
    upload(client, data=JPEG, content_type="image/jpeg")
    response = client.get(f"/v1/plots/{NORTH_BLOCK}/photo")
    assert response.status_code == 200
    assert response.content == JPEG
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"


def test_get_after_reupload_returns_the_new_photo(client, s3):
    upload(client)
    upload(client, data=JPEG, content_type="image/jpeg")
    response = client.get(f"/v1/plots/{NORTH_BLOCK}/photo")
    assert response.content == JPEG
    assert response.headers["content-type"] == "image/jpeg"


@pytest.mark.parametrize("plot_id", [UNKNOWN_PLOT, "not-a-uuid"])
def test_get_of_unknown_plot_is_404(client, s3, plot_id):
    body = assert_problem(client.get(f"/v1/plots/{plot_id}/photo"), 404, "NOT_FOUND")
    assert body["detail"] == "Plot not found"
    assert s3.clients_created == 0


def test_get_of_plot_without_photo_is_404(client, s3):
    body = assert_problem(client.get(f"/v1/plots/{NORTH_BLOCK}/photo"), 404, "NOT_FOUND")
    assert body["detail"] == "Plot has no photo"
    assert s3.clients_created == 0


def test_missing_object_in_s3_is_503_and_logged(client, s3, caplog):
    upload(client)
    s3.objects.clear()
    with caplog.at_level(logging.WARNING, logger="routers.plots"):
        response = client.get(f"/v1/plots/{NORTH_BLOCK}/photo")
    body = assert_problem(response, 503, "UNAVAILABLE")
    assert body["detail"] == "Photo storage unavailable"
    assert response.headers["retry-after"] == "5"
    assert "S3 download failed" in caplog.text
    assert "AccessDenied" in caplog.text


@pytest.mark.parametrize(
    "error",
    [NoCredentialsError(), ReadTimeoutError(endpoint_url="https://s3")],
    ids=["no-credentials", "read-timeout"],
)
def test_s3_failure_on_get_is_503(client, s3, error):
    upload(client)
    s3.fail_get = error
    response = client.get(f"/v1/plots/{NORTH_BLOCK}/photo")
    assert_problem(response, 503, "UNAVAILABLE")
    assert response.headers["retry-after"] == "5"


# --- Plot deletion -------------------------------------------------------------------


def test_delete_plot_with_photo_is_204_and_removes_the_row(client, db_file, s3):
    upload(client)
    response = client.delete(f"/v1/plots/{NORTH_BLOCK}")
    assert response.status_code == 204
    assert stored(db_file) == []
    assert client.get(f"/v1/plots/{NORTH_BLOCK}").status_code == 404
    # The S3 object stays: the server's IAM policy has no s3:DeleteObject.
    assert ("test-bucket", KEY) in s3.objects


# --- The S3 client -------------------------------------------------------------------


def test_s3_client_uses_region_and_timeouts_from_settings(monkeypatch, client):
    made = {}

    def fake_client(service, **kwargs):
        made.update(service=service, **kwargs)
        return "client"

    monkeypatch.setattr(boto3, "client", fake_client)
    assert plots._s3_client(client.app.state.settings) == "client"
    config = made["config"]
    assert made["service"] == "s3"
    assert made["region_name"] == "us-east-1"
    assert set(made) == {"service", "region_name", "config"}  # never credentials
    assert config.connect_timeout == 3
    assert config.read_timeout == 10
    assert config.retries == {"max_attempts": 3, "mode": "standard"}


# --- plot_photos is created at startup -----------------------------------------------


def _tables(path: Path) -> set[str]:
    con = sqlite3.connect(path)
    try:
        return {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        con.close()


def test_startup_creates_plot_photos_and_keeps_existing_rows(db_file, s3):
    assert "plot_photos" not in _tables(db_file)  # seed_registry.sh does not create it
    with TestClient(app) as client:
        upload(client)
    assert "plot_photos" in _tables(db_file)
    with TestClient(app):  # a second start changes nothing
        pass
    assert stored(db_file) == [(NORTH_BLOCK, KEY, "image/png")]


def test_startup_with_unavailable_database_logs_and_starts(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("DATABASE_URL", sqlite_url(tmp_path / "missing.db"))
    with caplog.at_level(logging.WARNING, logger="db"):
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200
    assert "Could not create plot_photos" in caplog.text
    assert "SQLITE_CANTOPEN" in caplog.text


def test_startup_fails_on_a_database_bug(db_file):
    con = sqlite3.connect(db_file)
    con.execute("CREATE INDEX plot_photos ON farms (name)")  # the name is taken
    con.commit()
    con.close()
    with pytest.raises(Exception, match="already an index named plot_photos"):
        with TestClient(app):
            pass
