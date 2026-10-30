"""Abstract base classes and shared dataclasses for database connectors."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, List, Optional


@dataclass
class ColumnInfo:
    """Metadata for a single table column."""

    name: str
    data_type: str
    nullable: bool = True
    is_primary_key: bool = False
    default_value: Optional[str] = None


@dataclass
class TableSchema:
    """Schema description for a database table."""

    table_name: str
    columns: List[ColumnInfo]
    primary_keys: List[str]


@dataclass
class QueryResult:
    """Result of executing a single SQL statement."""

    columns: List[str]
    rows: List[List[Any]]
    duration_ms: float
    row_count: int
    error: Optional[str] = None


class BaseDatabaseConnector(ABC):
    """Abstract base class that every database connector must implement."""

    @abstractmethod
    def test_connection(self) -> dict:
        """
        Verify the connection is reachable and return a status dict.

        Returns:
            dict with at least ``{"success": bool}``; on failure also
            includes ``{"error": str}``.
        """

    @abstractmethod
    def execute_query(self, sql: str, max_rows: int = 5000) -> List[QueryResult]:
        """
        Execute one or more SQL statements and return their results.

        Multi-statement SQL (separated by ``;``) is split and each
        non-empty statement is executed individually.  Comments
        (``--`` line comments and ``/* */`` block comments) are
        stripped before splitting so they do not produce phantom empty
        statements.

        Args:
            sql: Raw SQL string, may contain multiple statements and/or comments.
            max_rows: Maximum number of rows to return per statement.

        Returns:
            A list of :class:`QueryResult` objects, one per executed statement.
        """

    @abstractmethod
    def get_tables(self) -> List[str]:
        """Return a list of user table names in the connected database."""

    @abstractmethod
    def get_table_schema(self, table_name: str) -> TableSchema:
        """
        Return the schema (columns, primary keys) for *table_name*.

        Args:
            table_name: Name of the table to inspect.

        Returns:
            :class:`TableSchema` with column metadata and primary-key list.
        """

    @abstractmethod
    def fetch_table_rows(
        self,
        table_name: str,
        key_columns: List[str],
        max_rows: int = 100_000,
    ) -> List[dict]:
        """
        Fetch rows from *table_name* as a list of dicts.

        Args:
            table_name: Name of the table to read.
            key_columns: Columns to use for ordering (ORDER BY hint); may
                be ignored by connectors that do not support ordering.
            max_rows: Maximum number of rows to return.

        Returns:
            List of row dicts mapping column name → value.
        """
