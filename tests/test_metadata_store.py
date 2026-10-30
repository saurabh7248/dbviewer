import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure repo root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.dbviewer.config import DEFAULT_DB_PATH
from src.dbviewer.storage.metadata_store import MetadataStore


class TestMetadataStore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_dbviewer.db")
        self.store = MetadataStore(db_path=self.db_path)

    def tearDown(self):
        if hasattr(self, "store") and self.store:
            self.store.close()
        self.temp_dir.cleanup()

    def test_project_crud(self):
        project = self.store.create_project("BI Diagnostic", "Troubleshooting project")
        self.assertIsNotNone(project["id"])
        self.assertEqual(project["name"], "BI Diagnostic")
        self.assertEqual(project["description"], "Troubleshooting project")
        self.assertIn("created_at", project)
        self.assertIn("updated_at", project)

        # Get project
        fetched = self.store.get_project(project["id"])
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["name"], "BI Diagnostic")

        # List projects
        projects = self.store.list_projects()
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0]["name"], "BI Diagnostic")

        # Delete project
        self.assertTrue(self.store.delete_project(project["id"]))
        self.assertEqual(len(self.store.list_projects()), 0)
        self.assertIsNone(self.store.get_project(project["id"]))

        # Delete non-existent project returns False
        self.assertFalse(self.store.delete_project(99999))

    def test_connection_storage(self):
        p = self.store.create_project("Project A")
        conn = self.store.save_connection(
            p["id"],
            {
                "name": "Local SQLite",
                "engine_type": "sqlite",
                "file_path": "/tmp/test.db",
                "connection_options": {"timeout": 30},
            },
        )
        self.assertIsNotNone(conn["id"])
        self.assertEqual(conn["name"], "Local SQLite")
        self.assertEqual(conn["engine_type"], "sqlite")
        self.assertEqual(conn["file_path"], "/tmp/test.db")
        self.assertEqual(conn["project_id"], p["id"])
        parsed_opts = json.loads(conn["connection_options_json"])
        self.assertEqual(parsed_opts.get("timeout"), 30)

        # List connections
        conns = self.store.list_connections(p["id"])
        self.assertEqual(len(conns), 1)
        self.assertEqual(conns[0]["name"], "Local SQLite")

        # Get connection
        fetched = self.store.get_connection(conn["id"])
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["name"], "Local SQLite")

        # Update existing connection
        updated = self.store.save_connection(
            p["id"],
            {
                "id": conn["id"],
                "name": "Updated SQLite",
                "engine_type": "sqlite",
                "file_path": "/tmp/updated.db",
            },
        )
        self.assertEqual(updated["id"], conn["id"])
        self.assertEqual(updated["name"], "Updated SQLite")
        self.assertEqual(updated["file_path"], "/tmp/updated.db")

        # Delete connection
        self.assertTrue(self.store.delete_connection(conn["id"]))
        self.assertEqual(len(self.store.list_connections(p["id"])), 0)
        self.assertIsNone(self.store.get_connection(conn["id"]))

        # Delete non-existent connection returns False
        self.assertFalse(self.store.delete_connection(99999))

    def test_connection_update_preserves_omitted_fields(self):
        p = self.store.create_project("Project Preserve")
        conn = self.store.save_connection(
            p["id"],
            {
                "name": "Original Name",
                "engine_type": "sqlite",
                "file_path": "/tmp/orig.db",
                "host": "localhost",
                "port": 5432,
                "connection_options": {"timeout": 45},
            },
        )

        # Update only the name, leaving engine_type, file_path, etc. omitted
        updated = self.store.save_connection(
            p["id"],
            {
                "id": conn["id"],
                "name": "Only Name Changed",
            },
        )

        self.assertEqual(updated["id"], conn["id"])
        self.assertEqual(updated["name"], "Only Name Changed")
        self.assertEqual(updated["engine_type"], "sqlite")
        self.assertEqual(updated["file_path"], "/tmp/orig.db")
        self.assertEqual(updated["host"], "localhost")
        self.assertEqual(updated["port"], 5432)
        parsed_opts = json.loads(updated["connection_options_json"])
        self.assertEqual(parsed_opts.get("timeout"), 45)

    def test_connection_project_mismatch_raises_value_error(self):
        p1 = self.store.create_project("Project 1")
        p2 = self.store.create_project("Project 2")

        conn = self.store.save_connection(
            p1["id"],
            {
                "name": "Conn in P1",
                "engine_type": "sqlite",
            },
        )

        # Attempting to save/update under p2 with conn["id"] must raise ValueError
        with self.assertRaises(ValueError) as ctx:
            self.store.save_connection(
                p2["id"],
                {
                    "id": conn["id"],
                    "name": "Hijacked Conn",
                },
            )

        self.assertIn(f"Connection {conn['id']} does not belong to project {p2['id']}", str(ctx.exception))


    def test_frequent_and_pinned_queries(self):
        p = self.store.create_project("Project B")
        conn = self.store.save_connection(p["id"], {"name": "Conn", "engine_type": "sqlite"})
        r1 = self.store.record_query_execution(p["id"], conn["id"], "SELECT * FROM sales", 12.5, 100, "SUCCESS")
        self.assertIsNotNone(r1["id"])
        self.assertEqual(r1["status"], "SUCCESS")

        self.store.record_query_execution(p["id"], conn["id"], "SELECT * FROM sales", 10.0, 100, "SUCCESS")
        self.store.record_query_execution(p["id"], conn["id"], "SELECT count(*) FROM orders", 5.0, 1, "SUCCESS")

        frequent = self.store.list_frequent_queries(p["id"])
        self.assertEqual(len(frequent), 2)
        self.assertEqual(frequent[0]["sql_text"], "SELECT * FROM sales")
        self.assertEqual(frequent[0]["execution_count"], 2)
        self.assertEqual(frequent[1]["sql_text"], "SELECT count(*) FROM orders")
        self.assertEqual(frequent[1]["execution_count"], 1)

        # Pin the second query and verify it jumps ahead
        second_query_id = frequent[1]["id"]
        pinned_ok = self.store.pin_query(second_query_id, True)
        self.assertTrue(pinned_ok)

        frequent_after_pin = self.store.list_frequent_queries(p["id"])
        self.assertEqual(frequent_after_pin[0]["id"], second_query_id)
        self.assertTrue(bool(frequent_after_pin[0]["is_pinned"]))

        # Verify get_query returns query details
        q = self.store.get_query(second_query_id)
        self.assertIsNotNone(q)
        self.assertTrue(q["is_pinned"])

        # Unpin it
        unpinned_ok = self.store.pin_query(second_query_id, False)
        self.assertTrue(unpinned_ok)
        frequent_after_unpin = self.store.list_frequent_queries(p["id"])
        self.assertEqual(frequent_after_unpin[0]["sql_text"], "SELECT * FROM sales")

        # Pin non-existent query returns False
        self.assertFalse(self.store.pin_query(99999, True))

    def test_query_history_tracking(self):
        p = self.store.create_project("Project History")
        conn = self.store.save_connection(p["id"], {"name": "Conn", "engine_type": "sqlite"})

        self.store.record_query_execution(p["id"], conn["id"], "SELECT 1", 2.0, 1, "SUCCESS")
        self.store.record_query_execution(p["id"], conn["id"], "SELECT 2", 3.0, 1, "ERROR", "syntax error")

        history = self.store.list_query_history(p["id"])
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["sql_text"], "SELECT 2")
        self.assertEqual(history[0]["status"], "ERROR")
        self.assertEqual(history[0]["error_message"], "syntax error")
        self.assertEqual(history[1]["sql_text"], "SELECT 1")

    def test_cascade_delete_project(self):
        p = self.store.create_project("Project Cascade")
        conn = self.store.save_connection(p["id"], {"name": "Conn", "engine_type": "sqlite"})
        self.store.record_query_execution(p["id"], conn["id"], "SELECT 1", 1.0, 1, "SUCCESS")

        self.assertEqual(len(self.store.list_connections(p["id"])), 1)
        self.assertEqual(len(self.store.list_frequent_queries(p["id"])), 1)
        self.assertEqual(len(self.store.list_query_history(p["id"])), 1)

        # Delete project should cascade
        self.assertTrue(self.store.delete_project(p["id"]))
        self.assertEqual(len(self.store.list_connections(p["id"])), 0)
        self.assertEqual(len(self.store.list_frequent_queries(p["id"])), 0)
        self.assertEqual(len(self.store.list_query_history(p["id"])), 0)
        self.assertIsNone(self.store.get_connection(conn["id"]))

    def test_context_manager(self):
        db_path = os.path.join(self.temp_dir.name, "cm_test.db")
        with MetadataStore(db_path=db_path) as store:
            p = store.create_project("CM Project")
            self.assertIsNotNone(p["id"])
        # Should be closed
        self.assertIsNone(store._conn)

    def test_default_db_path(self):
        with tempfile.TemporaryDirectory() as fake_home:
            mock_default_dir = Path(fake_home) / ".dbviewer"
            mock_default_file = mock_default_dir / "dbviewer.db"
            with patch("src.dbviewer.config.DEFAULT_DB_DIR", mock_default_dir), \
                 patch("src.dbviewer.config.DEFAULT_DB_PATH", mock_default_file):
                store = MetadataStore()
                self.assertEqual(store.db_path, str(mock_default_file))
                p = store.create_project("Default Path Project")
                self.assertIsNotNone(p["id"])
                store.close()
                self.assertTrue(mock_default_file.exists())


if __name__ == "__main__":
    unittest.main()
