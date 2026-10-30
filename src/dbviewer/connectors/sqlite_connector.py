"""SQLite implementation of BaseDatabaseConnector."""

import os
import re
import sqlite3
import time
from typing import Any, Dict, List, Optional

from src.dbviewer.connectors.base import (
    BaseDatabaseConnector,
    ColumnInfo,
    QueryResult,
    TableSchema,
)

# Regex that matches a single-line (--) or block (/* */) SQL comment.
_COMMENT_RE = re.compile(
    r"--[^\r\n]*"           # line comment: -- to end of line
    r"|/\*.*?\*/",          # block comment: /* ... */
    re.DOTALL,
)


def _split_statements(sql: str) -> List[str]:
    """Strip SQL comments then split on semicolons, discarding empty chunks."""
    stripped = _COMMENT_RE.sub("", sql)
    parts = stripped.split(";")
    return [p.strip() for p in parts if p.strip()]


class SQLiteConnector(BaseDatabaseConnector):
    """Database connector for local SQLite files.

    Args:
        config: Dict with key ``"file_path"`` pointing at the SQLite database
                file, or ``":memory:"`` for an in-memory database.
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        self._file_path: str = config["file_path"]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Open and return a new SQLite connection with row_factory set."""
        conn = sqlite3.connect(self._file_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------
    # BaseDatabaseConnector interface
    # ------------------------------------------------------------------

    def test_connection(self) -> dict:
        """Check that the SQLite file exists and is a valid database."""
        # For file-backed databases, verify the file is reachable first.
        if self._file_path != ":memory:" and not os.path.isfile(self._file_path):
            return {
                "success": False,
                "error": f"Database file not found: {self._file_path}",
            }
        try:
            with self._connect() as conn:
                conn.execute("SELECT 1")
            return {"success": True}
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": str(exc)}

    def get_tables(self) -> List[str]:
        """Return names of all user-created tables (excludes sqlite_* internals)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        return [row["name"] for row in rows]

    def get_table_schema(self, table_name: str) -> TableSchema:
        """Inspect *table_name* via ``PRAGMA table_info`` and return its schema."""
        with self._connect() as conn:
            pragma_rows = conn.execute(
                f"PRAGMA table_info({table_name})"  # noqa: S608 – table name is not user SQL
            ).fetchall()

        columns: List[ColumnInfo] = []
        primary_keys: List[str] = []

        for row in pragma_rows:
            # PRAGMA table_info columns: cid, name, type, notnull, dflt_value, pk
            is_pk = bool(row["pk"])
            col = ColumnInfo(
                name=row["name"],
                data_type=row["type"] if row["type"] else "TEXT",
                nullable=not bool(row["notnull"]),
                is_primary_key=is_pk,
                default_value=row["dflt_value"],
            )
            columns.append(col)
            if is_pk:
                primary_keys.append(row["name"])

        return TableSchema(
            table_name=table_name,
            columns=columns,
            primary_keys=primary_keys,
        )

    def execute_query(self, sql: str, max_rows: int = 5000) -> List[QueryResult]:
        """Execute one or more SQL statements and return a list of QueryResults.

        Multi-statement input is split on ``;`` after stripping ``--`` and
        ``/* */`` comments so that blank or comment-only "statements" are
        ignored.
        """
        statements = _split_statements(sql)
        results: List[QueryResult] = []

        with self._connect() as conn:
            for stmt in statements:
                start = time.perf_counter()
                try:
                    cursor = conn.execute(stmt)
                    col_names: List[str] = (
                        [desc[0] for desc in cursor.description]
                        if cursor.description
                        else []
                    )
                    raw_rows = cursor.fetchmany(max_rows)
                    rows = [list(r) for r in raw_rows]
                    duration_ms = (time.perf_counter() - start) * 1000
                    results.append(
                        QueryResult(
                            columns=col_names,
                            rows=rows,
                            duration_ms=duration_ms,
                            row_count=len(rows),
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    duration_ms = (time.perf_counter() - start) * 1000
                    results.append(
                        QueryResult(
                            columns=[],
                            rows=[],
                            duration_ms=duration_ms,
                            row_count=0,
                            error=str(exc),
                        )
                    )

        return results

    def fetch_table_rows(
        self,
        table_name: str,
        key_columns: List[str],
        max_rows: int = 100_000,
    ) -> List[dict]:
        """Fetch up to *max_rows* rows from *table_name* ordered by *key_columns*.

        Args:
            table_name: Name of the table to read.
            key_columns: Column names to use in ORDER BY (ignored if empty).
            max_rows: Maximum number of rows to return.

        Returns:
            List of row dicts mapping column name → value.
        """
        order_clause = ""
        if key_columns:
            # Sanitise column names: keep only word characters to prevent injection.
            safe_cols = [re.sub(r"[^\w]", "", c) for c in key_columns]
            safe_cols = [c for c in safe_cols if c]
            if safe_cols:
                order_clause = " ORDER BY " + ", ".join(safe_cols)

        # Sanitise table name similarly.
        safe_table = re.sub(r"[^\w]", "", table_name)
        query = f"SELECT * FROM {safe_table}{order_clause} LIMIT {int(max_rows)}"  # noqa: S608

        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query).fetchall()

        return [dict(r) for r in rows]
