"""Exercise the UI files through the same HTTP routes used by the frontend."""

from pathlib import Path
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.dbviewer.api.app import create_app
from src.dbviewer.storage.metadata_store import MetadataStore


@pytest.fixture
def client(tmp_path):
    store = MetadataStore(db_path=tmp_path / "ui-metadata.sqlite")
    app = create_app(store)
    app.config.update(TESTING=True)
    yield app.test_client()
    store.close()


def test_ui_entrypoint_and_assets_are_served(client):
    root = Path(__file__).parents[1] / "src" / "dbviewer" / "ui"
    index = client.get("/")
    assert index.status_code == 200
    html = index.get_data(as_text=True)
    assert "DBViewer" in html
    assert "/static/css/styles.css" in html

    assets = (
        ("/static/css/styles.css", "text/css"),
        ("/static/js/app.js", "javascript"),
        ("/static/js/grid.js", "javascript"),
        ("/static/js/editor.js", "javascript"),
        ("/static/js/diff.js", "javascript"),
    )
    for url, content_type in assets:
        response = client.get(url)
        assert response.status_code == 200, url
        assert content_type in response.content_type, url
        assert response.data, url
        assert (root / "static" / url.removeprefix("/static/")).is_file(), url


def test_index_references_groupable_tabulator_results_and_editor(client):
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True).lower()
    assert "tabulator" in html
    assert 'id="group-columns"' in html
    assert 'id="result-grid"' in html
    assert 'id="sql-editor"' in html


def test_unknown_static_asset_returns_not_found(client):
    response = client.get("/static/js/not-present.js")
    assert response.status_code == 404
