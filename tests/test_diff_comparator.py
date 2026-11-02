import pytest

from src.dbviewer.connectors.base import ColumnInfo, TableSchema
from src.dbviewer.diff.comparator import MissingPrimaryKeyError, TableComparator


def test_schema_comparison_tracks_missing_extra_and_type_mismatch():
    source = TableSchema("users", [
        ColumnInfo("id", "INTEGER", False, True),
        ColumnInfo("name", "VARCHAR(100)", False),
        ColumnInfo("age", "INTEGER"),
    ], ["id"])
    target = TableSchema("users_copy", [
        ColumnInfo("id", "INT", False, True),
        ColumnInfo("name", "TEXT", False),
        ColumnInfo("created_at", "TIMESTAMP"),
    ], ["id"])

    diff = TableComparator().compare_schemas(source, target)

    assert [col.name for col in diff.missing_in_target] == ["age"]
    assert [col.name for col in diff.extra_in_target] == ["created_at"]
    assert any(d.column_name == "id" and d.status == "MATCH" for d in diff.column_diffs)
    assert diff.type_mismatches == [("name", "VARCHAR(100)", "TEXT")]


def test_all_column_fallback_when_no_pk_and_no_keys():
    source = TableSchema("items", [
        ColumnInfo("a", "INTEGER", False),
        ColumnInfo("b", "TEXT", False),
    ], [])
    target = TableSchema("items", [
        ColumnInfo("a", "INT", False),
        ColumnInfo("b", "TEXT", False),
    ], [])
    comparator = TableComparator()
    keys = comparator.resolve_keys(source, target, user_keys=None)
    assert keys == ["a", "b"]


def test_all_column_fallback_raises_when_target_missing_column():
    source = TableSchema("items", [
        ColumnInfo("a", "INTEGER", False),
        ColumnInfo("b", "TEXT", False),
    ], [])
    target = TableSchema("items", [
        ColumnInfo("a", "INT", False),
    ], [])
    comparator = TableComparator()
    with pytest.raises(ValueError) as exc_info:
        comparator.resolve_keys(source, target, user_keys=None)
    assert "missing" in str(exc_info.value)


def test_data_comparison_finds_inserts_updates_and_target_only_deletes():
    source = [
        {"id": 1, "name": "same", "role": "Admin"},
        {"id": 2, "name": "Bob", "role": "User"},
        {"id": 3, "name": "New", "role": "Guest"},
    ]
    target = [
        {"id": 1, "name": "same", "role": "Admin"},
        {"id": 2, "name": "Bob", "role": "Manager"},
        {"id": 4, "name": "Old", "role": "User"},
    ]

    inserts, updates, deletes = TableComparator().compare_data(source, target, ["id"])

    assert [item.key_values for item in inserts] == [{"id": 3}]
    assert updates[0].key_values == {"id": 2}
    assert updates[0].diff_values == {"role": ("Manager", "User")}
    assert [item.key_values for item in deletes] == [{"id": 4}]


def test_missing_primary_key_fallback_to_all_columns_and_validates_them():
    schema = TableSchema("logs", [ColumnInfo("msg", "TEXT")], [])
    comparator = TableComparator()

    # Fallback to all columns when no PK/user keys
    assert comparator.resolve_keys(schema, schema) == ["msg"]
    assert comparator.resolve_keys(schema, schema, ["msg"]) == ["msg"]
    with pytest.raises(MissingPrimaryKeyError, match="missing from one or both"):
        comparator.resolve_keys(schema, schema, ["unknown"])


def test_none_values_compare_equal_without_an_update():
    result = TableComparator().compare_data(
        [{"id": 1, "note": None}], [{"id": 1, "note": None}], ["id"]
    )
    assert result == ([], [], [])


@pytest.mark.parametrize(
    ("source_rows", "target_rows", "message"),
    [
        ([{"value": "source"}], [], "source row is missing key columns"),
        ([], [{"value": "target"}], "target row is missing key columns"),
    ],
)
def test_data_comparison_rejects_rows_missing_key_fields(source_rows, target_rows, message):
    with pytest.raises(MissingPrimaryKeyError, match=message):
        TableComparator().compare_data(source_rows, target_rows, ["id"])
