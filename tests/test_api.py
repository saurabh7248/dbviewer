"""Integration tests for the Flask API using temporary metadata and SQLite DBs."""

import sqlite3
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.dbviewer.api.app import create_app
from src.dbviewer.storage.metadata_store import MetadataStore


@pytest.fixture
def api(tmp_path):
    store = MetadataStore(db_path=tmp_path / "metadata.sqlite")
    app = create_app(store)
    app.config.update(TESTING=True)
    yield app.test_client(), store
    store.close()


def make_project(client, name="Project"):
    response = client.post("/api/projects", json={"name": name})
    assert response.status_code == 201
    return response.get_json()


def make_sqlite_connection(client, project_id, path, name="SQLite"):
    response = client.post(
        f"/api/projects/{project_id}/connections",
        json={"name": name, "engine_type": "sqlite", "file_path": str(path)},
    )
    assert response.status_code == 201
    return response.get_json()


def test_projects_connections_and_query_run_store_history(api, tmp_path):
    client, _ = api
    db_path = tmp_path / "analytics.sqlite"
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, label TEXT)")
        db.execute("INSERT INTO items VALUES (1, 'first'), (2, 'second'), (3, 'third')")

    project = make_project(client, "BI Staging")
    connection = make_sqlite_connection(client, project["id"], db_path)
    listed = client.get(f"/api/projects/{project['id']}/connections")
    assert listed.status_code == 200
    assert listed.get_json()[0]["id"] == connection["id"]
    assert "password_encrypted" not in listed.get_json()[0]

    result = client.post(
        "/api/query/run",
        json={
            "project_id": project["id"],
            "connection_id": connection["id"],
            "sql": "SELECT id, label FROM items ORDER BY id",
            "max_rows": 2,
        },
    )
    assert result.status_code == 200
    assert result.get_json()["results"][0]["rows"] == [[1, "first"], [2, "second"]]
    assert result.get_json()["row_count"] == 2

    frequent = client.get(f"/api/projects/{project['id']}/queries/frequent")
    history = client.get(f"/api/projects/{project['id']}/queries/history")
    assert frequent.get_json()[0]["sql_text"] == "SELECT id, label FROM items ORDER BY id"
    assert history.get_json()[0]["row_count"] == 2
    assert history.get_json()[0]["status"] == "SUCCESS"


def test_project_and_connection_ownership_errors(api, tmp_path):
    client, _ = api
    first = make_project(client, "First")
    second = make_project(client, "Second")
    conn = make_sqlite_connection(client, first["id"], tmp_path / "one.sqlite")

    absent_project = client.get("/api/projects/999/connections")
    assert absent_project.status_code == 404
    foreign_query = client.post(
        "/api/query/run",
        json={"project_id": second["id"], "connection_id": conn["id"], "sql": "SELECT 1"},
    )
    assert foreign_query.status_code == 404
    foreign_update = client.post(
        f"/api/projects/{second['id']}/connections",
        json={"id": conn["id"], "name": "steal", "engine_type": "sqlite"},
    )
    assert foreign_update.status_code == 400
    assert client.delete("/api/projects/999").status_code == 404


def test_connection_test_and_table_listing(api, tmp_path):
    client, _ = api
    db_path = tmp_path / "catalog.sqlite"
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE customers (id INTEGER PRIMARY KEY)")

    successful = client.post(
        "/api/connections/test", json={"engine_type": "sqlite", "file_path": str(db_path)}
    )
    assert successful.status_code == 200
    assert successful.get_json()["success"] is True

    project = make_project(client)
    conn = make_sqlite_connection(client, project["id"], db_path)
    tables = client.get(f"/api/connections/{conn['id']}/tables")
    assert tables.status_code == 200
    assert tables.get_json() == ["customers"]


def test_diff_can_be_compared_and_generated_sql(api, tmp_path):
    client, _ = api
    source_path, target_path = tmp_path / "source.sqlite", tmp_path / "target.sqlite"
    with sqlite3.connect(source_path) as db:
        db.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT)")
        db.execute("INSERT INTO records VALUES (1, 'updated'), (2, 'new')")
    with sqlite3.connect(target_path) as db:
        db.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT)")
        db.execute("INSERT INTO records VALUES (1, 'old'), (3, 'removed')")

    project = make_project(client)
    source = make_sqlite_connection(client, project["id"], source_path, "source")
    target = make_sqlite_connection(client, project["id"], target_path, "target")
    compared = client.post(
        "/api/diff/compare",
        json={
            "source_connection_id": source["id"],
            "source_table": "records",
            "target_connection_id": target["id"],
            "target_table": "records",
        },
    )
    assert compared.status_code == 200
    assert len(compared.get_json()["diff"]["inserts"]) == 1
    assert len(compared.get_json()["diff"]["updates"]) == 1
    assert len(compared.get_json()["diff"]["deletes"]) == 1

    generated = client.post(
        "/api/diff/generate-sql", json={"diff_id": compared.get_json()["diff_id"]}
    )
    assert generated.status_code == 200
    assert "UPDATE" in generated.get_json()["sql"]
    assert "INSERT" in generated.get_json()["sql"]
    assert "DELETE" in generated.get_json()["sql"]


def test_execute_sync_requires_explicit_true_confirmation(api, tmp_path):
    client, _ = api
    project = make_project(client)
    conn = make_sqlite_connection(client, project["id"], tmp_path / "target.sqlite")
    response = client.post(
        "/api/diff/execute-sync",
        json={"target_connection_id": conn["id"], "sql": "CREATE TABLE should_not_run (id INT)"},
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "Explicit confirmation is required"
    with sqlite3.connect(tmp_path / "target.sqlite") as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name='should_not_run'").fetchone() is None


def test_invalid_or_missing_diff_ids_and_query_input_are_rejected(api):
    client, _ = api
    assert client.post("/api/diff/generate-sql", json={"diff_id": "unknown"}).status_code == 404
    assert client.post("/api/diff/execute-sync", json={"confirmed": True}).status_code == 404
    assert client.post("/api/query/run", json={"sql": "SELECT 1"}).status_code == 400


def test_pin_endpoint_rejects_non_boolean_pin_values(api):
    client, _ = api
    project = make_project(client)
    conn = make_sqlite_connection(client, project["id"], ":memory:")
    client.post(
        "/api/query/run",
        json={"project_id": project["id"], "connection_id": conn["id"], "sql": "SELECT 1"},
    )
    query_id = client.get(f"/api/projects/{project['id']}/queries/frequent").get_json()[0]["id"]

    response = client.post(f"/api/queries/{query_id}/pin", json={"is_pinned": "false"})

    assert response.status_code == 400
    assert response.get_json()["error"] == "is_pinned must be a boolean"


def test_pin_endpoint_accepts_boolean_pin_and_unpin_values(api):
    client, _ = api
    project = make_project(client)
    conn = make_sqlite_connection(client, project["id"], ":memory:")
    client.post(
        "/api/query/run",
        json={"project_id": project["id"], "connection_id": conn["id"], "sql": "SELECT 1"},
    )
    query_id = client.get(f"/api/projects/{project['id']}/queries/frequent").get_json()[0]["id"]

    pinned = client.post(f"/api/queries/{query_id}/pin", json={"is_pinned": True})
    assert pinned.status_code == 200
    assert client.get(f"/api/projects/{project['id']}/queries/frequent").get_json()[0]["is_pinned"] is True

    unpinned = client.post(f"/api/queries/{query_id}/pin", json={"is_pinned": False})
    assert unpinned.status_code == 200
    assert client.get(f"/api/projects/{project['id']}/queries/frequent").get_json()[0]["is_pinned"] is False


@pytest.mark.parametrize("route", ["frequent", "history"])
def test_query_listing_routes_return_404_for_missing_project(api, route):
    client, _ = api
    response = client.get(f"/api/projects/999/queries/{route}")
    assert response.status_code == 404
    assert response.get_json()["error"] == "Project not found"


def test_confirmed_sync_executes_sql_against_target(api, tmp_path):
    client, _ = api
    db_path = tmp_path / "sync-target.sqlite"
    project = make_project(client)
    conn = make_sqlite_connection(client, project["id"], db_path)

    response = client.post(
        "/api/diff/execute-sync",
        json={
            "target_connection_id": conn["id"],
            "sql": "CREATE TABLE synced (id INTEGER PRIMARY KEY); INSERT INTO synced VALUES (7)",
            "confirmed": True,
        },
    )

    assert response.status_code == 200
    assert response.get_json()["success"] is True
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT id FROM synced").fetchall() == [(7,)]


def test_query_execution_error_is_returned_and_recorded(api, tmp_path):
    client, _ = api
    project = make_project(client)
    conn = make_sqlite_connection(client, project["id"], tmp_path / "query-errors.sqlite")

    response = client.post(
        "/api/query/run",
        json={"project_id": project["id"], "connection_id": conn["id"], "sql": "SELECT * FROM missing_table"},
    )

    assert response.status_code == 200
    assert "no such table" in response.get_json()["results"][0]["error"]
    history = client.get(f"/api/projects/{project['id']}/queries/history").get_json()
    assert history[0]["status"] == "ERROR"
    assert "no such table" in history[0]["error_message"]
