"""Shared helpers for DB-API based connectors."""
import time
from typing import Any

from src.dbviewer.connectors.base import BaseDatabaseConnector, ColumnInfo, QueryResult, TableSchema


class DBAPIConnector(BaseDatabaseConnector):
    """Common execution and metadata plumbing; subclasses define SQL and connect."""
    dialect = ""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = dict(config)

    def _get_connection(self):
        raise NotImplementedError

    def _identifier(self, name: str) -> str:
        if self.dialect == "mssql":
            return "[" + name.replace("]", "]]" ) + "]"
        return '"' + name.replace('"', '""') + '"'

    def test_connection(self) -> dict:
        try:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                cursor.fetchone()
            finally:
                conn.close()
            return {"success": True}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def execute_query(self, sql: str, max_rows: int = 5000) -> list[QueryResult]:
        # DB drivers differ in multi-result handling; execute statements one at a time.
        from src.dbviewer.connectors.sqlite_connector import _split_statements
        output = []
        statements = _split_statements(sql)
        if not statements: return output
        conn = self._get_connection()
        failed = False
        try:
            for statement in statements:
                started = time.perf_counter()
                try:
                    cursor = conn.cursor()
                    cursor.execute(statement)
                    columns = [d[0] for d in cursor.description] if cursor.description else []
                    rows = cursor.fetchmany(max(0, int(max_rows))) if columns else []
                    output.append(QueryResult(columns, [list(r) for r in rows], (time.perf_counter()-started)*1000, len(rows)))
                except Exception as exc:
                    failed = True
                    output.append(QueryResult([], [], (time.perf_counter()-started)*1000, 0, str(exc)))
                    break
            if failed: conn.rollback()
            else: conn.commit()
        finally:
            conn.close()
        return output

    def get_tables(self) -> list[str]:
        raise NotImplementedError

    def get_table_schema(self, table_name: str) -> TableSchema:
        raise NotImplementedError

    def fetch_table_rows(self, table_name: str, key_columns: list[str], max_rows: int = 100_000) -> list[dict]:
        table = self._identifier(table_name)
        ordering = " ORDER BY " + ", ".join(self._identifier(c) for c in key_columns) if key_columns else ""
        limit = f" FETCH FIRST {int(max_rows)} ROWS ONLY"
        if self.dialect == "mssql":
            query = f"SELECT TOP ({int(max_rows)}) * FROM {table}" + ordering
        elif self.dialect == "sqlite":
            query = f"SELECT * FROM {table}" + ordering + f" LIMIT {int(max_rows)}"
        else:
            query = f"SELECT * FROM {table}" + ordering + limit
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query)
            names = [d[0] for d in cursor.description or []]
            return [dict(zip(names, row)) for row in cursor.fetchmany(max(0, int(max_rows)))]
        finally:
            conn.close()
