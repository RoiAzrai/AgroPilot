import sqlite3
from pathlib import Path

import boto3

from conftest import assert_problem
from routers import plots
from test_plots import DEMO_COOPERATIVE, NORTH_BLOCK

EAST_BLOCK = "d9a4e2c1-5e3f-4b6a-9c33-2e7f4a803003"  # Demo cooperative
WEST_BLOCK = "e0b5f3d2-6f40-4c7b-8d44-3f8a5b914004"  # the other farm
OTHER_FARM = "a9c1e4b2-6f70-4d8e-a144-3f8b5c904004"
UNKNOWN_FARM = "00000000-0000-4000-8000-000000000000"


def add_photos(db_file: Path, *plot_ids: str) -> None:
    con = sqlite3.connect(db_file)
    try:
        con.executemany(
            "INSERT INTO plot_photos (plot_id, key, content_type) VALUES (?, ?, 'image/png')",
            [(plot_id, f"k/{plot_id}") for plot_id in plot_ids],
        )
        con.commit()
    finally:
        con.close()


def get(client, farm_id: str = DEMO_COOPERATIVE):
    return client.get("/v1/plot-photos", params={"farm_id": farm_id})


def test_farm_with_photos(client, db_file):
    add_photos(db_file, EAST_BLOCK, NORTH_BLOCK)
    response = get(client)
    assert response.status_code == 200
    assert response.json() == {"plot_ids": [NORTH_BLOCK, EAST_BLOCK]}  # plot creation order


def test_only_plots_with_photos_are_listed(client, db_file):
    add_photos(db_file, EAST_BLOCK)
    assert get(client).json() == {"plot_ids": [EAST_BLOCK]}


def test_farm_without_photos(client):
    response = get(client)
    assert response.status_code == 200
    assert response.json() == {"plot_ids": []}


def test_unknown_farm_is_empty_like_plots_filter(client, db_file):
    add_photos(db_file, NORTH_BLOCK)
    response = get(client, UNKNOWN_FARM)
    assert response.status_code == 200
    assert response.json() == {"plot_ids": []}


def test_only_requested_farm_is_returned(client, db_file):
    add_photos(db_file, NORTH_BLOCK, WEST_BLOCK)
    assert get(client).json() == {"plot_ids": [NORTH_BLOCK]}
    assert get(client, OTHER_FARM).json() == {"plot_ids": [WEST_BLOCK]}


def test_deleted_plot_is_not_listed(client, db_file):
    add_photos(db_file, NORTH_BLOCK)
    assert client.delete(f"/v1/plots/{NORTH_BLOCK}").status_code == 204
    assert get(client).json() == {"plot_ids": []}


def test_invalid_farm_id_is_422(client):
    assert_problem(get(client, "abc"), 422, "VALIDATION")


def test_missing_farm_id_is_422(client):
    assert_problem(client.get("/v1/plot-photos"), 422, "VALIDATION")


def test_no_s3_client_is_created(client, db_file, monkeypatch):
    created = []
    monkeypatch.setattr(boto3, "client", lambda *a, **k: created.append(1))
    monkeypatch.setattr(plots, "_s3_client", lambda settings: created.append(1))
    add_photos(db_file, NORTH_BLOCK)
    assert get(client).status_code == 200
    assert created == []


def test_openapi_documents_the_endpoint(client):
    operation = client.get("/openapi.json").json()["paths"]["/v1/plot-photos"]["get"]
    assert [p["name"] for p in operation["parameters"]] == ["farm_id"]
    assert operation["parameters"][0]["required"] is True
