"""Schema normalization and key-indexed cross-database row comparison."""
import re
from src.dbviewer.connectors.base import BaseDatabaseConnector, TableSchema
from src.dbviewer.diff.models import ColumnDiff, RowDiff, SchemaDiff, TableDiffResult


class MissingPrimaryKeyError(ValueError):
    """Raised when no safe row identity can be established for a diff."""


def _normalized_type(value: str) -> str:
    value = re.sub(r"\s*\([^)]*\)", "", (value or "").strip().upper())
    aliases = {"INT": "INTEGER", "INT4": "INTEGER", "INT8": "BIGINT", "DECIMAL": "NUMERIC", "CHARACTER VARYING": "VARCHAR", "DOUBLE PRECISION": "DOUBLE", "BOOL": "BOOLEAN", "DATETIME": "TIMESTAMP", "TIMESTAMP WITHOUT TIME ZONE": "TIMESTAMP"}
    return aliases.get(value, value)


class TableComparator:
    def compare_schemas(self, source_schema: TableSchema, target_schema: TableSchema) -> SchemaDiff:
        src = {c.name.casefold(): c for c in source_schema.columns}
        tgt = {c.name.casefold(): c for c in target_schema.columns}
        missing = [c for k, c in src.items() if k not in tgt]
        extra = [c for k, c in tgt.items() if k not in src]
        diffs, mismatches = [], []
        for key in src.keys() | tgt.keys():
            left, right = src.get(key), tgt.get(key)
            if left is None:
                diffs.append(ColumnDiff(right.name, None, right.data_type, "REMOVED_IN_SOURCE"))
            elif right is None:
                diffs.append(ColumnDiff(left.name, left.data_type, None, "ADDED_IN_SOURCE"))
            elif _normalized_type(left.data_type) != _normalized_type(right.data_type):
                diffs.append(ColumnDiff(left.name, left.data_type, right.data_type, "TYPE_MISMATCH"))
                mismatches.append((left.name, left.data_type, right.data_type))
            else:
                diffs.append(ColumnDiff(left.name, left.data_type, right.data_type, "MATCH"))
        return SchemaDiff(source_schema.table_name, target_schema.table_name, diffs, missing, extra, mismatches)

    def resolve_keys(self, source_schema: TableSchema, target_schema: TableSchema, user_keys=None) -> list[str]:
        if user_keys:
            keys = list(user_keys)
        else:
            source_keys, target_keys = source_schema.primary_keys, target_schema.primary_keys
            keys = source_keys if source_keys and source_keys == target_keys else []
        if not keys:
            raise MissingPrimaryKeyError("No matching primary key; provide user-selected key columns")
        source_names = {c.name.casefold() for c in source_schema.columns}
        target_names = {c.name.casefold() for c in target_schema.columns}
        invalid = [k for k in keys if k.casefold() not in source_names or k.casefold() not in target_names]
        if invalid:
            raise MissingPrimaryKeyError("Key columns are missing from one or both tables: " + ", ".join(invalid))
        return keys

    def compare_data(self, source_rows, target_rows, key_columns):
        if not key_columns:
            raise MissingPrimaryKeyError("At least one key column is required")
        def index(rows, label):
            result = {}
            for row in rows:
                missing = [key for key in key_columns if key not in row]
                if missing: raise MissingPrimaryKeyError(f"{label} row is missing key columns: {', '.join(missing)}")
                key = tuple(row[k] for k in key_columns)
                if key in result: raise ValueError(f"Duplicate key in {label} rows: {key!r}")
                result[key] = row
            return result
        src, tgt = index(source_rows, "source"), index(target_rows, "target")
        key_dict = lambda key: dict(zip(key_columns, key))
        inserts, updates, deletes = [], [], []
        for key, row in src.items():
            if key not in tgt:
                inserts.append(RowDiff(key_dict(key), "INSERT", dict(row)))
            else:
                target_row = tgt[key]
                changed = {col: (target_row.get(col), value) for col, value in row.items() if col not in key_columns and target_row.get(col) != value}
                if changed: updates.append(RowDiff(key_dict(key), "UPDATE", changed))
        for key, row in tgt.items():
            if key not in src: deletes.append(RowDiff(key_dict(key), "DELETE", dict(row)))
        return inserts, updates, deletes

    def compare_tables(self, source_conn: BaseDatabaseConnector, source_table: str, target_conn: BaseDatabaseConnector, target_table: str, user_keys=None) -> TableDiffResult:
        source_schema = source_conn.get_table_schema(source_table)
        target_schema = target_conn.get_table_schema(target_table)
        keys = self.resolve_keys(source_schema, target_schema, user_keys)
        source_rows = source_conn.fetch_table_rows(source_table, keys)
        target_rows = target_conn.fetch_table_rows(target_table, keys)
        inserts, updates, deletes = self.compare_data(source_rows, target_rows, keys)
        return TableDiffResult(self.compare_schemas(source_schema, target_schema), keys, inserts, updates, deletes)
