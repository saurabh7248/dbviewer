"""Data models for schema and row differences."""
from dataclasses import dataclass, field
from typing import Optional, Tuple
from src.dbviewer.connectors.base import ColumnInfo


@dataclass
class ColumnDiff:
    column_name: str
    source_type: Optional[str]
    target_type: Optional[str]
    status: str


@dataclass
class SchemaDiff:
    source_table: str
    target_table: str
    column_diffs: list[ColumnDiff] = field(default_factory=list)
    missing_in_target: list[ColumnInfo] = field(default_factory=list)
    extra_in_target: list[ColumnInfo] = field(default_factory=list)
    type_mismatches: list[Tuple[str, str, str]] = field(default_factory=list)


@dataclass
class RowDiff:
    key_values: dict
    action: str
    diff_values: dict


@dataclass
class TableDiffResult:
    schema_diff: SchemaDiff
    key_columns: list[str]
    inserts: list[RowDiff] = field(default_factory=list)
    updates: list[RowDiff] = field(default_factory=list)
    deletes: list[RowDiff] = field(default_factory=list)
