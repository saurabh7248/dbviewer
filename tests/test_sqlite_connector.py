"""Tests for BaseDatabaseConnector abstraction and SQLiteConnector implementation."""

import os
import sqlite3
import tempfile
import unittest

from src.dbviewer.connectors.sqlite_connector import SQLiteConnector
from src.dbviewer.connectors.base import (
    BaseDatabaseConnector,
    ColumnInfo,
    QueryResult,
    TableSchema,
)


class TestDataclasses(unittest.TestCase):
    """Unit tests for the connector dataclasses."""

    def test_column_info_defaults(self):
        col = ColumnInfo(name="id", data_type="INTEGER")
        self.assertEqual(col.name, "id")
        self.assertEqual(col.data_type, "INTEGER")
        self.assertTrue(col.nullable)
        self.assertFalse(col.is_primary_key)
        self.assertIsNone(col.default_value)

    def test_column_info_custom(self):
        col = ColumnInfo(
            name="pk",
            data_type="INTEGER",
            nullable=False,
            is_primary_key=True,
            default_value="0",
        )
        self.assertFalse(col.nullable)
        self.assertTrue(col.is_primary_key)
        self.assertEqual(col.default_value, "0")

    def test_table_schema_fields(self):
        cols = [ColumnInfo(name="id", data_type="INTEGER", is_primary_key=True)]
        schema = TableSchema(table_name="users", columns=cols, primary_keys=["id"])
        self.assertEqual(schema.table_name, "users")
        self.assertEqual(len(schema.columns), 1)
        self.assertEqual(schema.primary_keys, ["id"])

    def test_query_result_defaults(self):
        qr = QueryResult(columns=["a", "b"], rows=[[1, 2]], duration_ms=5.0, row_count=1)
        self.assertIsNone(qr.error)

    def test_query_result_with_error(self):
        qr = QueryResult(columns=[], rows=[], duration_ms=1.0, row_count=0, error="syntax error")
        self.assertEqual(qr.error, "syntax error")

    def test_base_connector_is_abstract(self):
        """BaseDatabaseConnector cannot be instantiated directly."""
        with self.assertRaises(TypeError):
            BaseDatabaseConnector()  # type: ignore[abstract]


class TestSQLiteConnectorSetup(unittest.TestCase):
    """Tests for SQLiteConnector using a temp database."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.db_file = os.path.join(self._tmpdir, "sample.db")
        with sqlite3.connect(self.db_file) as conn:
            conn.execute(
                "CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT NOT NULL, price REAL)"
            )
            conn.execute(
                "INSERT INTO products VALUES (1, 'Widget', 19.99), (2, 'Gadget', 29.99)"
            )
            conn.execute(
                "CREATE TABLE customers (cust_id INTEGER PRIMARY KEY, email TEXT)"
            )

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)


class TestSQLiteConnectionAndTables(TestSQLiteConnectorSetup):
    def test_connection_success(self):
        connector = SQLiteConnector({"file_path": self.db_file})
        res = connector.test_connection()
        self.assertIs(res["success"], True)

    def test_get_tables_returns_expected(self):
        connector = SQLiteConnector({"file_path": self.db_file})
        tables = connector.get_tables()
        self.assertIn("products", tables)
        self.assertIn("customers", tables)

    def test_connection_missing_file(self):
        connector = SQLiteConnector({"file_path": "/nonexistent/path/db.sqlite"})
        res = connector.test_connection()
        self.assertIs(res["success"], False)
        self.assertIn("error", res)


class TestSQLiteSchemaInspection(TestSQLiteConnectorSetup):
    def test_products_schema_basic(self):
        connector = SQLiteConnector({"file_path": self.db_file})
        schema = connector.get_table_schema("products")
        self.assertEqual(schema.table_name, "products")
        self.assertEqual(len(schema.columns), 3)
        self.assertEqual(schema.primary_keys, ["id"])

    def test_price_column_type(self):
        connector = SQLiteConnector({"file_path": self.db_file})
        schema = connector.get_table_schema("products")
        price_col = next(c for c in schema.columns if c.name == "price")
        self.assertIn(price_col.data_type.upper(), ["REAL", "FLOAT", "NUMERIC"])

    def test_pk_column_marked_correctly(self):
        connector = SQLiteConnector({"file_path": self.db_file})
        schema = connector.get_table_schema("products")
        id_col = next(c for c in schema.columns if c.name == "id")
        self.assertTrue(id_col.is_primary_key)

    def test_not_null_column_nullable_false(self):
        connector = SQLiteConnector({"file_path": self.db_file})
        schema = connector.get_table_schema("products")
        name_col = next(c for c in schema.columns if c.name == "name")
        self.assertFalse(name_col.nullable)


class TestSQLiteQueryExecution(TestSQLiteConnectorSetup):
    def test_simple_select(self):
        connector = SQLiteConnector({"file_path": self.db_file})
        results = connector.execute_query("SELECT id, name FROM products WHERE id = 1")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].columns, ["id", "name"])
        self.assertEqual(results[0].rows, [[1, "Widget"]])
        self.assertGreaterEqual(results[0].duration_ms, 0)
        self.assertEqual(results[0].row_count, 1)

    def test_multi_statement_with_comments_and_empty(self):
        connector = SQLiteConnector({"file_path": self.db_file})
        sql = """
        -- Diagnostic query
        SELECT id, name FROM products WHERE id = 1;

        /* Another query */
        SELECT count(*) AS total FROM products;
        ;
        """
        results = connector.execute_query(sql)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].columns, ["id", "name"])
        self.assertEqual(results[0].rows, [[1, "Widget"]])
        self.assertEqual(results[1].rows, [[2]])

    def test_max_rows_enforcement(self):
        connector = SQLiteConnector({"file_path": self.db_file})
        results = connector.execute_query("SELECT * FROM products", max_rows=1)
        self.assertEqual(len(results[0].rows), 1)
        self.assertEqual(results[0].row_count, 1)

    def test_invalid_sql_returns_error_result(self):
        connector = SQLiteConnector({"file_path": self.db_file})
        results = connector.execute_query("SELECT * FROM nonexistent_table")
        self.assertEqual(len(results), 1)
        self.assertIsNotNone(results[0].error)

    def test_duration_ms_is_positive(self):
        connector = SQLiteConnector({"file_path": self.db_file})
        results = connector.execute_query("SELECT 1")
        self.assertGreaterEqual(results[0].duration_ms, 0)


class TestFetchTableRows(TestSQLiteConnectorSetup):
    def test_fetch_all_rows(self):
        connector = SQLiteConnector({"file_path": self.db_file})
        rows = connector.fetch_table_rows("products", key_columns=["id"])
        self.assertEqual(len(rows), 2)
        self.assertIn("id", rows[0])
        self.assertIn("name", rows[0])

    def test_fetch_max_rows(self):
        connector = SQLiteConnector({"file_path": self.db_file})
        rows = connector.fetch_table_rows("products", key_columns=["id"], max_rows=1)
        self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
