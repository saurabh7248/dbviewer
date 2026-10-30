"""Generate reviewed, target-dialect SQL scripts from a table diff."""
import datetime
import decimal
import re


class SQLSyncGenerator:
    DIALECTS = {"sqlite", "postgres", "postgresql", "mssql", "sqlserver", "oracle", "h2"}

    def _dialect(self, engine):
        name = (engine or "").lower()
        if name not in self.DIALECTS: raise ValueError(f"Unsupported target engine: {engine}")
        return {"postgresql": "postgres", "sqlserver": "mssql"}.get(name, name)

    def _identifier(self, value, dialect):
        if dialect == "mssql": return "[" + str(value).replace("]", "]]" ) + "]"
        return '"' + str(value).replace('"', '""') + '"'

    def _literal(self, value, dialect):
        if value is None: return "NULL"
        if isinstance(value, bool): return ("1" if value else "0") if dialect in {"sqlite", "mssql"} else ("TRUE" if value else "FALSE")
        if isinstance(value, (int, float, decimal.Decimal)):
            if isinstance(value, float) and (value != value or abs(value) == float("inf")): raise ValueError("NaN and infinity cannot be emitted as SQL literals")
            return str(value)
        if isinstance(value, (datetime.date, datetime.datetime, datetime.time)): value = value.isoformat()
        return "'" + str(value).replace("'", "''") + "'"

    def _where(self, values, dialect):
        if not values: raise ValueError("Cannot generate a statement without key values")
        return " AND ".join(f"{self._identifier(k,dialect)} IS NULL" if v is None else f"{self._identifier(k,dialect)} = {self._literal(v,dialect)}" for k,v in values.items())

    def _safe_type(self, data_type):
        value = (data_type or "TEXT").strip()
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_ ]*(?:\(\s*\d+(?:\s*,\s*\d+)?\s*\))?", value):
            raise ValueError(f"Unsafe or unsupported column type: {data_type!r}")
        return value

    def generate_sync_script(self, diff_result, target_engine, include_deletes=True):
        d = self._dialect(target_engine)
        table = self._identifier(diff_result.schema_diff.target_table, d)
        lines = ["-- Review this synchronization script before execution."]
        if d == "mssql": lines.append("BEGIN TRANSACTION;")
        elif d == "oracle": lines.append("-- Oracle starts DML transactions implicitly; DDL statements commit implicitly.")
        else: lines.append("BEGIN TRANSACTION;")
        for col in diff_result.schema_diff.missing_in_target:
            add = f"ADD ({self._identifier(col.name,d)} {self._safe_type(col.data_type)})" if d == "oracle" else f"ADD {self._identifier(col.name,d)} {self._safe_type(col.data_type)}"
            if d in {"sqlite", "postgres", "h2"}: add = f"ADD COLUMN {self._identifier(col.name,d)} {self._safe_type(col.data_type)}"
            lines.append(f"ALTER TABLE {table} {add};")
        for item in diff_result.inserts:
            values = item.diff_values
            if not values: continue
            names = list(values)
            lines.append(f"INSERT INTO {table} ({', '.join(self._identifier(k,d) for k in names)}) VALUES ({', '.join(self._literal(values[k],d) for k in names)});")
        for item in diff_result.updates:
            changes = item.diff_values
            if changes:
                sets = ", ".join(f"{self._identifier(k,d)} = {self._literal(v[1] if isinstance(v, (tuple,list)) and len(v)==2 else v,d)}" for k,v in changes.items())
                lines.append(f"UPDATE {table} SET {sets} WHERE {self._where(item.key_values,d)};")
        if include_deletes:
            for item in diff_result.deletes:
                lines.append(f"DELETE FROM {table} WHERE {self._where(item.key_values,d)};")
        lines.append("COMMIT;")
        return "\n".join(lines) + "\n"
