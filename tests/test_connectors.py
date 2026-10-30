"""Tests for multi-engine connectors and factory (Task 3).

Third-party drivers (psycopg, pymssql, python-oracledb) are not installed.
Temporary MagicMock stubs satisfy imports without leaving entries in the
process-wide sys.modules mapping.
"""

import sys
from types import ModuleType
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch
import pytest

# ---------------------------------------------------------------------------
# Inject mock driver modules BEFORE any connector is imported.
# ---------------------------------------------------------------------------
_CONNECTOR_PREFIX = "src.dbviewer.connectors"
_CONNECTOR_MODULES_BEFORE_TEST_IMPORT = {
    name for name in sys.modules
    if name == _CONNECTOR_PREFIX or name.startswith(_CONNECTOR_PREFIX + ".")
}
MOCK_PSYCOPG = MagicMock()
MOCK_PYMSSQL = MagicMock()
MOCK_ORACLEDB = MagicMock()
_CONNECTOR_DRIVERS = {
    "src.dbviewer.connectors.postgres_connector": ("psycopg", MOCK_PSYCOPG),
    "src.dbviewer.connectors.mssql_connector": ("pymssql", MOCK_PYMSSQL),
    "src.dbviewer.connectors.oracle_connector": ("oracledb", MOCK_ORACLEDB),
}


@contextmanager
def _temporary_driver_modules():
    stubs = {"psycopg": MOCK_PSYCOPG, "pymssql": MOCK_PYMSSQL, "oracledb": MOCK_ORACLEDB}
    previous = {name: sys.modules.get(name) for name in stubs}
    present = {name for name in stubs if name in sys.modules}
    sys.modules.update(stubs)
    try:
        yield
    finally:
        for name in stubs:
            if name in present:
                sys.modules[name] = previous[name]
            else:
                sys.modules.pop(name, None)


def _replace_connector_driver_globals(modules):
    """Install test drivers on cached modules and return their original globals."""
    originals = []
    for module_name, (attribute, stub) in _CONNECTOR_DRIVERS.items():
        module = modules.get(module_name)
        if module is not None and hasattr(module, attribute):
            originals.append((module, attribute, getattr(module, attribute)))
            setattr(module, attribute, stub)
    return originals


def _restore_connector_driver_globals(originals):
    for module, attribute, original in originals:
        setattr(module, attribute, original)


with _temporary_driver_modules():
    from src.dbviewer.connectors.factory import get_connector  # noqa: E402
    from src.dbviewer.connectors.h2_connector import H2Connector  # noqa: E402
    from src.dbviewer.connectors.mssql_connector import MSSQLConnector  # noqa: E402
    from src.dbviewer.connectors.oracle_connector import OracleConnector  # noqa: E402
    from src.dbviewer.connectors.postgres_connector import PostgresConnector  # noqa: E402
    from src.dbviewer.connectors.sqlite_connector import SQLiteConnector  # noqa: E402

_ORIGINAL_CONNECTOR_DRIVER_GLOBALS = _replace_connector_driver_globals(
    {name: sys.modules[name] for name in _CONNECTOR_DRIVERS if name in sys.modules}
)


@pytest.fixture(scope="module", autouse=True)
def _remove_connector_modules_imported_for_tests():
    yield
    _restore_connector_driver_globals(_ORIGINAL_CONNECTOR_DRIVER_GLOBALS)
    imported_for_tests = {
        name for name in sys.modules
        if (name == _CONNECTOR_PREFIX or name.startswith(_CONNECTOR_PREFIX + "."))
        and name not in _CONNECTOR_MODULES_BEFORE_TEST_IMPORT
    }
    for name in sorted(imported_for_tests, key=lambda item: item.count("."), reverse=True):
        module = sys.modules.pop(name, None)
        parent_name, _, child_name = name.rpartition(".")
        parent = sys.modules.get(parent_name)
        if parent is not None and getattr(parent, child_name, None) is module:
            delattr(parent, child_name)
    remaining = {
        name for name in sys.modules
        if (name == _CONNECTOR_PREFIX or name.startswith(_CONNECTOR_PREFIX + "."))
        and name not in _CONNECTOR_MODULES_BEFORE_TEST_IMPORT
    }
    assert not remaining, f"connector modules leaked after tests: {sorted(remaining)}"


# ---------------------------------------------------------------------------
# Factory tests
# ---------------------------------------------------------------------------


class TestFactory(unittest.TestCase):

    def test_preimported_connector_driver_globals_are_restored(self):
        module_name = "src.dbviewer.connectors.postgres_connector"
        module = ModuleType(module_name)
        original_driver = object()
        module.psycopg = original_driver
        was_present = module_name in sys.modules
        previous_module = sys.modules.get(module_name)
        sys.modules[module_name] = module
        try:
            saved = _replace_connector_driver_globals({module_name: module})
            self.assertIs(module.psycopg, MOCK_PSYCOPG)
            self.assertIs(sys.modules[module_name], module)
            _restore_connector_driver_globals(saved)
            self.assertIs(module.psycopg, original_driver)
            self.assertIs(sys.modules[module_name], module)
        finally:
            if was_present:
                sys.modules[module_name] = previous_module
            else:
                sys.modules.pop(module_name, None)

    def test_import_driver_stubs_do_not_remain_in_sys_modules(self):
        self.assertIsNot(sys.modules.get("psycopg"), MOCK_PSYCOPG)
        self.assertIsNot(sys.modules.get("pymssql"), MOCK_PYMSSQL)
        self.assertIsNot(sys.modules.get("oracledb"), MOCK_ORACLEDB)

    def test_factory_creates_sqlite(self):
        conn = get_connector({"engine_type": "sqlite", "file_path": ":memory:"})
        self.assertIsInstance(conn, SQLiteConnector)

    def test_factory_creates_postgres(self):
        conn = get_connector(
            {
                "engine_type": "postgres",
                "host": "localhost",
                "port": 5432,
                "database": "db",
                "user": "u",
                "password": "p",
            }
        )
        self.assertIsInstance(conn, PostgresConnector)

    def test_factory_creates_mssql(self):
        conn = get_connector(
            {
                "engine_type": "mssql",
                "host": "localhost",
                "port": 1433,
                "database": "db",
                "user": "u",
                "password": "p",
            }
        )
        self.assertIsInstance(conn, MSSQLConnector)

    def test_factory_creates_oracle(self):
        conn = get_connector(
            {
                "engine_type": "oracle",
                "host": "localhost",
                "port": 1521,
                "database": "orcl",
                "user": "u",
                "password": "p",
            }
        )
        self.assertIsInstance(conn, OracleConnector)

    def test_factory_creates_h2(self):
        conn = get_connector({"engine_type": "h2", "file_path": "/tmp/test"})
        self.assertIsInstance(conn, H2Connector)

    def test_factory_unsupported_engine_raises_value_error(self):
        with self.assertRaises(ValueError) as ctx:
            get_connector({"engine_type": "unsupported_db"})
        self.assertIn("Unsupported engine type", str(ctx.exception))

    def test_factory_unsupported_engine_message_contains_name(self):
        with self.assertRaises(ValueError) as ctx:
            get_connector({"engine_type": "mongodb"})
        self.assertIn("mongodb", str(ctx.exception))


# ---------------------------------------------------------------------------
# H2Connector tests
# ---------------------------------------------------------------------------


class TestH2Connector(unittest.TestCase):

    def test_jdbc_url_contains_jdbc_h2(self):
        conn = H2Connector({"file_path": "/tmp/mydb"})
        url = conn.build_jdbc_url()
        self.assertIn("jdbc:h2:", url)

    def test_jdbc_url_contains_file_path(self):
        conn = H2Connector({"file_path": "/tmp/mydb"})
        url = conn.build_jdbc_url()
        self.assertIn("/tmp/mydb", url)

    def test_jdbc_url_format3_mv_db(self, tmp_path=None):
        """Mirrors the brief's test_h2_connector_format3_jdbc_bridge_command."""
        import tempfile, os

        with tempfile.TemporaryDirectory() as tmp:
            h2_file = os.path.join(tmp, "test.mv.db")
            with open(h2_file, "wb") as f:
                f.write(b"H2 format 3 dummy header")
            connector = H2Connector({"file_path": os.path.join(tmp, "test"), "format": 3})
            jdbc_url = connector.build_jdbc_url()
            self.assertIn("jdbc:h2:", jdbc_url)
            self.assertIn(os.path.join(tmp, "test"), jdbc_url)

    def test_h2_subclasses_base(self):
        from src.dbviewer.connectors.base import BaseDatabaseConnector

        conn = H2Connector({"file_path": "/tmp/mydb"})
        self.assertIsInstance(conn, BaseDatabaseConnector)


# ---------------------------------------------------------------------------
# PostgresConnector tests (fully mocked)
# ---------------------------------------------------------------------------


class TestPostgresConnector(unittest.TestCase):

    def _make_connector(self):
        return PostgresConnector(
            {
                "host": "localhost",
                "port": 5432,
                "database": "bi_db",
                "user": "admin",
                "password": "secret",
            }
        )

    def test_subclasses_base(self):
        from src.dbviewer.connectors.base import BaseDatabaseConnector

        self.assertIsInstance(self._make_connector(), BaseDatabaseConnector)

    def test_get_tables_returns_list(self):
        conn = self._make_connector()
        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [("users",), ("sales",)]
        mock_cursor.description = [("table_name",)]
        mock_connection.cursor.return_value = mock_cursor
        with patch.object(conn, "_get_connection", return_value=mock_connection):
            tables = conn.get_tables()
        self.assertEqual(tables, ["users", "sales"])

    def test_test_connection_success(self):
        conn = self._make_connector()
        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_connection.cursor.return_value.__enter__ = MagicMock(
            return_value=mock_cursor
        )
        mock_connection.cursor.return_value.__exit__ = MagicMock(return_value=False)
        with patch.object(conn, "_get_connection", return_value=mock_connection):
            result = conn.test_connection()
        self.assertTrue(result["success"])

    def test_test_connection_failure(self):
        conn = self._make_connector()
        with patch.object(
            conn, "_get_connection", side_effect=Exception("connection refused")
        ):
            result = conn.test_connection()
        self.assertFalse(result["success"])
        self.assertIn("connection refused", result["error"])

    def test_execute_query_returns_columns_limited_rows_and_commits(self):
        conn = self._make_connector()
        mock_connection = MagicMock()
        cursor = mock_connection.cursor.return_value
        cursor.description = [("id",), ("name",)]
        cursor.fetchmany.return_value = [(1, "Ada"), (2, "Lin")]
        with patch.object(conn, "_get_connection", return_value=mock_connection):
            results = conn.execute_query("SELECT id, name FROM users", max_rows=2)
        self.assertEqual(results[0].columns, ["id", "name"])
        self.assertEqual(results[0].rows, [[1, "Ada"], [2, "Lin"]])
        self.assertEqual(results[0].row_count, 2)
        cursor.fetchmany.assert_called_once_with(2)
        mock_connection.commit.assert_called_once()
        mock_connection.close.assert_called_once()

    def test_execute_query_returns_error_and_rolls_back_on_failure(self):
        conn = self._make_connector()
        mock_connection = MagicMock()
        mock_connection.cursor.return_value.execute.side_effect = RuntimeError("bad SQL")
        with patch.object(conn, "_get_connection", return_value=mock_connection):
            results = conn.execute_query("SELECT broken")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].rows, [])
        self.assertEqual(results[0].error, "bad SQL")
        mock_connection.rollback.assert_called_once()
        mock_connection.commit.assert_not_called()
        mock_connection.close.assert_called_once()

    def test_connection_uses_postgres_config_and_options(self):
        conn = self._make_connector()
        with patch.object(MOCK_PSYCOPG, "connect") as connect:
            conn._get_connection()
        connect.assert_called_once_with(
            host="localhost", port=5432, dbname="bi_db", user="admin",
            password="secret"
        )

    def test_schema_maps_nullability_defaults_and_primary_keys(self):
        conn = self._make_connector()
        mock_connection = MagicMock()
        mock_connection.cursor.return_value.fetchall.return_value = [
            ("id", "integer", "NO", None, 1),
            ("name", "character varying", "YES", "'guest'::character varying", 0),
        ]
        with patch.object(conn, "_get_connection", return_value=mock_connection):
            schema = conn.get_table_schema("users")
        self.assertEqual(schema.primary_keys, ["id"])
        self.assertEqual(schema.columns[0].nullable, False)
        self.assertEqual(schema.columns[0].is_primary_key, True)
        self.assertEqual(schema.columns[1].default_value, "'guest'::character varying")
        mock_connection.close.assert_called_once()

    def test_fetch_table_rows_quotes_identifiers_and_closes_connection(self):
        conn = self._make_connector()
        mock_connection = MagicMock()
        cursor = mock_connection.cursor.return_value
        cursor.description = [("id",), ("name",)]
        cursor.fetchmany.return_value = [(1, "Ada")]
        with patch.object(conn, "_get_connection", return_value=mock_connection):
            rows = conn.fetch_table_rows('odd"table', ["id"], max_rows=7)
        self.assertEqual(rows, [{"id": 1, "name": "Ada"}])
        self.assertIn('SELECT * FROM "odd""table"', cursor.execute.call_args.args[0])
        self.assertIn('ORDER BY "id" FETCH FIRST 7 ROWS ONLY', cursor.execute.call_args.args[0])
        mock_connection.close.assert_called_once()


# ---------------------------------------------------------------------------
# MSSQLConnector tests (fully mocked)
# ---------------------------------------------------------------------------


class TestMSSQLConnector(unittest.TestCase):

    def _make_connector(self):
        return MSSQLConnector(
            {
                "host": "localhost",
                "port": 1433,
                "database": "testdb",
                "user": "sa",
                "password": "pass",
            }
        )

    def test_subclasses_base(self):
        from src.dbviewer.connectors.base import BaseDatabaseConnector

        self.assertIsInstance(self._make_connector(), BaseDatabaseConnector)

    def test_get_tables_returns_list(self):
        conn = self._make_connector()
        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [("orders",), ("products",)]
        mock_connection.cursor.return_value = mock_cursor
        with patch.object(conn, "_get_connection", return_value=mock_connection):
            tables = conn.get_tables()
        self.assertEqual(tables, ["orders", "products"])

    def test_test_connection_failure(self):
        conn = self._make_connector()
        with patch.object(
            conn, "_get_connection", side_effect=Exception("timeout")
        ):
            result = conn.test_connection()
        self.assertFalse(result["success"])

    def test_connection_uses_mssql_config(self):
        conn = self._make_connector()
        with patch.object(MOCK_PYMSSQL, "connect") as connect:
            conn._get_connection()
        connect.assert_called_once_with(
            server="localhost", port="1433", database="testdb", user="sa", password="pass"
        )

    def test_schema_maps_primary_key_columns(self):
        conn = self._make_connector()
        mock_connection = MagicMock()
        mock_connection.cursor.return_value.fetchall.return_value = [
            ("id", "int", "NO", None, 1), ("label", "varchar", "YES", None, 0)
        ]
        with patch.object(conn, "_get_connection", return_value=mock_connection):
            schema = conn.get_table_schema("items")
        self.assertEqual(schema.primary_keys, ["id"])
        self.assertFalse(schema.columns[0].nullable)
        self.assertTrue(schema.columns[0].is_primary_key)
        mock_connection.close.assert_called_once()

    def test_schema_qualified_primary_key_metadata_is_filtered_by_schema(self):
        conn = self._make_connector()
        mock_connection = MagicMock()
        mock_connection.cursor.return_value.fetchall.return_value = [
            ("id", "int", "NO", None, 1)
        ]
        with patch.object(conn, "_get_connection", return_value=mock_connection):
            schema = conn.get_table_schema("sales.orders")
        self.assertEqual(schema.primary_keys, ["id"])
        sql, params = mock_connection.cursor.return_value.execute.call_args.args
        self.assertIn("TABLE_SCHEMA", sql)
        self.assertEqual(params, ("orders", "sales", "sales", "orders", "sales", "sales"))

    def test_fetch_table_rows_uses_top_and_bracket_quoting(self):
        conn = self._make_connector()
        mock_connection = MagicMock()
        cursor = mock_connection.cursor.return_value
        cursor.description = [("id",)]
        cursor.fetchmany.return_value = [(1,)]
        with patch.object(conn, "_get_connection", return_value=mock_connection):
            rows = conn.fetch_table_rows("odd]table", ["key"], max_rows=3)
        self.assertEqual(rows, [{"id": 1}])
        self.assertEqual(cursor.execute.call_args.args[0], "SELECT TOP (3) * FROM [odd]]table] ORDER BY [key]")


# ---------------------------------------------------------------------------
# OracleConnector tests (fully mocked)
# ---------------------------------------------------------------------------


class TestOracleConnector(unittest.TestCase):

    def _make_connector(self):
        return OracleConnector(
            {
                "host": "localhost",
                "port": 1521,
                "database": "orcl",
                "user": "sys",
                "password": "pass",
            }
        )

    def test_subclasses_base(self):
        from src.dbviewer.connectors.base import BaseDatabaseConnector

        self.assertIsInstance(self._make_connector(), BaseDatabaseConnector)

    def test_get_tables_returns_list(self):
        conn = self._make_connector()
        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [("EMPLOYEES",), ("DEPARTMENTS",)]
        mock_connection.cursor.return_value = mock_cursor
        with patch.object(conn, "_get_connection", return_value=mock_connection):
            tables = conn.get_tables()
        self.assertEqual(tables, ["EMPLOYEES", "DEPARTMENTS"])

    def test_test_connection_failure(self):
        conn = self._make_connector()
        with patch.object(
            conn, "_get_connection", side_effect=Exception("ORA-12541")
        ):
            result = conn.test_connection()
        self.assertFalse(result["success"])

    def test_connection_builds_service_name_dsn(self):
        conn = self._make_connector()
        driver = MOCK_ORACLEDB
        with patch.object(driver, "makedsn", return_value="made-dsn") as makedsn, patch.object(driver, "connect") as connect:
            conn._get_connection()
        makedsn.assert_called_once_with("localhost", 1521, service_name="orcl")
        connect.assert_called_once_with(user="sys", password="pass", dsn="made-dsn")

    def test_schema_maps_primary_key_columns(self):
        conn = self._make_connector()
        mock_connection = MagicMock()
        mock_connection.cursor.return_value.fetchall.return_value = [
            ("ID", "NUMBER", "N", None, 1), ("NAME", "VARCHAR2", "Y", None, 0)
        ]
        with patch.object(conn, "_get_connection", return_value=mock_connection):
            schema = conn.get_table_schema("EMPLOYEES")
        self.assertEqual(schema.primary_keys, ["ID"])
        self.assertFalse(schema.columns[0].nullable)
        self.assertTrue(schema.columns[0].is_primary_key)
        self.assertEqual(mock_connection.cursor.return_value.execute.call_args.kwargs, {"table_name": "EMPLOYEES"})


class TestH2ConnectorExecution(unittest.TestCase):

    def test_fetch_table_rows_preserves_numeric_boolean_and_date_values(self):
        from datetime import date

        conn = H2Connector({"file_path": "/tmp/example"})
        with patch.object(
            conn,
            "_command",
            side_effect=(
                "COLUMN_NAME | DATA_TYPE\n------------+----------\nID | INTEGER\nACTIVE | BOOLEAN\nCREATED | DATE\n(3 rows)\n",
                "ID | ACTIVE | CREATED\n---+--------+----------\n42 | TRUE | 2024-05-06\n(1 row, 9 ms)\n",
            ),
        ):
            rows = conn.fetch_table_rows("records", [], max_rows=10)
        self.assertEqual(rows, [{"ID": 42, "ACTIVE": True, "CREATED": date(2024, 5, 6)}])

    def test_tcp_jdbc_url_includes_host_port_and_database(self):
        conn = H2Connector({"host": "db.example", "port": 9123, "database": "analytics"})
        self.assertEqual(conn.build_jdbc_url(), "jdbc:h2:tcp://db.example:9123/analytics")

    def test_shell_command_contains_credentials_and_sql(self):
        import os
        import tempfile
        conn = H2Connector({"file_path": "/tmp/example", "jar_path": "/tmp/h2.jar", "user": "sa", "password": "pw"})
        with patch("src.dbviewer.connectors.h2_connector.os.path.isfile", return_value=True), \
             patch("src.dbviewer.connectors.h2_connector.shutil.which", return_value="/usr/bin/java"), \
             patch("src.dbviewer.connectors.h2_connector.subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = "1\n"
            conn._command("SELECT 1")
        command = run.call_args.args[0]
        self.assertIn("org.h2.tools.Shell", command)
        self.assertIn("jdbc:h2:file:/tmp/example", command)
        self.assertEqual(command[command.index("-sql") + 1], "SELECT 1")
        run.assert_called_once()

    def test_shell_failure_includes_process_error(self):
        conn = H2Connector({"file_path": "/tmp/example", "jar_path": "/tmp/h2.jar"})
        with patch("src.dbviewer.connectors.h2_connector.os.path.isfile", return_value=True), \
             patch("src.dbviewer.connectors.h2_connector.shutil.which", return_value="java"), \
             patch("src.dbviewer.connectors.h2_connector.subprocess.run") as run:
            run.return_value.returncode = 1
            run.return_value.stderr = "bad credentials"
            run.return_value.stdout = ""
            with self.assertRaisesRegex(RuntimeError, "bad credentials"):
                conn._command("SELECT 1")


if __name__ == "__main__":
    unittest.main()
