import pytest

from src.dbviewer.connectors.base import ColumnInfo
from src.dbviewer.diff.models import RowDiff, SchemaDiff, TableDiffResult
from src.dbviewer.diff.sql_generator import SQLSyncGenerator


def _diff(*, inserts=(), updates=(), deletes=(), missing=(), table="users"):
    return TableDiffResult(
        SchemaDiff(table, table, [], list(missing), [], []),
        ["id"], list(inserts), list(updates), list(deletes),
    )


def test_sqlite_script_includes_schema_and_data_changes_in_transaction():
    diff = _diff(
        missing=[ColumnInfo("age", "INTEGER")],
        inserts=[RowDiff({"id": 10}, "INSERT", {"id": 10, "name": "New User", "age": 25})],
        updates=[RowDiff({"id": 2}, "UPDATE", {"name": ("Old Name", "Updated Name")})],
        deletes=[RowDiff({"id": 5}, "DELETE", {"id": 5})],
    )

    sql = SQLSyncGenerator().generate_sync_script(diff, "sqlite")

    assert "BEGIN TRANSACTION;" in sql
    assert 'ALTER TABLE "users" ADD COLUMN "age" INTEGER;' in sql
    assert 'INSERT INTO "users"' in sql
    assert 'UPDATE "users" SET "name" = \'Updated Name\' WHERE "id" = 2;' in sql
    assert 'DELETE FROM "users" WHERE "id" = 5;' in sql
    assert sql.rstrip().endswith("COMMIT;")


def test_string_literals_escape_apostrophes_and_preserve_newlines():
    diff = _diff(inserts=[RowDiff(
        {"id": 1}, "INSERT", {"id": 1, "author": "O'Reilly", "bio": "line1\nline2"}
    )], table="authors")

    sql = SQLSyncGenerator().generate_sync_script(diff, "postgres")

    assert "'O''Reilly'" in sql
    assert "'line1\nline2'" in sql


def test_mssql_uses_bracket_quoted_identifiers_and_escapes_closing_bracket():
    diff = _diff(inserts=[RowDiff(
        {"id": 1}, "INSERT", {"id": 1, "odd]name": "Shipped"}
    )], table="order]items")

    sql = SQLSyncGenerator().generate_sync_script(diff, "mssql")

    assert "[order]]items]" in sql
    assert "[odd]]name]" in sql
    assert "BEGIN TRANSACTION;" in sql


def test_null_values_use_null_literals_and_is_null_predicates():
    diff = _diff(
        inserts=[RowDiff({"id": 1}, "INSERT", {"id": 1, "note": None})],
        updates=[RowDiff({"id": 1}, "UPDATE", {"note": ("old", None)})],
        deletes=[RowDiff({"id": None}, "DELETE", {})],
    )

    sql = SQLSyncGenerator().generate_sync_script(diff, "sqlite")

    assert 'VALUES (1, NULL);' in sql
    assert 'SET "note" = NULL WHERE "id" = 1;' in sql
    assert 'DELETE FROM "users" WHERE "id" IS NULL;' in sql


def test_include_deletes_false_omits_delete_statements():
    diff = _diff(deletes=[RowDiff({"id": 4}, "DELETE", {"id": 4})])

    sql = SQLSyncGenerator().generate_sync_script(diff, "sqlite", include_deletes=False)

    assert "DELETE FROM" not in sql


def test_rejects_unsafe_column_types_before_emitting_ddl():
    diff = _diff(missing=[ColumnInfo("extra", "INTEGER); DROP TABLE users; --")])

    with pytest.raises(ValueError, match="Unsafe or unsupported column type"):
        SQLSyncGenerator().generate_sync_script(diff, "sqlite")


@pytest.mark.parametrize(
    ("dialect", "expected_ddl", "transaction_start"),
    [
        ("oracle", 'ALTER TABLE "users" ADD ("age" INTEGER);',
         "-- Oracle starts DML transactions implicitly; DDL statements commit implicitly."),
        ("h2", 'ALTER TABLE "users" ADD COLUMN "age" INTEGER;', "BEGIN TRANSACTION;"),
    ],
)
def test_oracle_and_h2_scripts_use_target_ddl_and_transaction_semantics(
    dialect, expected_ddl, transaction_start
):
    diff = _diff(missing=[ColumnInfo("age", "INTEGER")])

    sql = SQLSyncGenerator().generate_sync_script(diff, dialect)

    assert transaction_start in sql
    assert expected_ddl in sql
    assert sql.rstrip().endswith("COMMIT;")


def test_oracle_string_literals_escape_apostrophes():
    diff = _diff(inserts=[RowDiff(
        {"id": 1}, "INSERT", {"id": 1, "name": "O'Reilly"}
    )])

    sql = SQLSyncGenerator().generate_sync_script(diff, "oracle")

    assert "'O''Reilly'" in sql


@pytest.mark.parametrize(
    ("dialect", "quote"),
    [("oracle", '"'), ("h2", '"')],
)
def test_oracle_and_h2_generate_insert_update_delete_with_null_predicates(dialect, quote):
    diff = _diff(
        inserts=[RowDiff({"id": 1}, "INSERT", {"id": 1, "note": None})],
        updates=[RowDiff({"id": None}, "UPDATE", {"note": ("old", "O'Reilly")})],
        deletes=[RowDiff({"id": None}, "DELETE", {"id": None})],
        table="notes",
    )

    sql = SQLSyncGenerator().generate_sync_script(diff, dialect)

    assert f'INSERT INTO {quote}notes{quote} ({quote}id{quote}, {quote}note{quote}) VALUES (1, NULL);' in sql
    assert f"UPDATE {quote}notes{quote} SET {quote}note{quote} = 'O''Reilly' WHERE {quote}id{quote} IS NULL;" in sql
    assert f"DELETE FROM {quote}notes{quote} WHERE {quote}id{quote} IS NULL;" in sql
