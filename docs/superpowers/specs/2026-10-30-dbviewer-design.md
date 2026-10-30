# System Design: Multi-Database Diagnostic Viewer & Table Diff Desktop App

* **Date:** 2026-10-30
* **Status:** Final Proposed (Awaiting User Approval)
* **Author:** Antigravity & User

---

## 1. Intent and the "Why"

Business Intelligence (BI) platforms often rely on multiple operational and analytical database backends (PostgreSQL, Microsoft SQL Server, Oracle, SQLite, H2). Diagnosing data consistency issues, inspecting pipeline stage tables, verifying metrics, and troubleshooting anomalies currently requires juggling disparate, heavyweight database administration tools. 

Furthermore, development, staging, and diagnostic workflows frequently require synchronizing tables between different databases (e.g. SQLite, H2, PostgreSQL, Oracle, MSSQL). There is an acute need for a lightweight, focused desktop tool that:
1. Organizes database connections by project.
2. Tracks, surfaces, and quickly re-runs frequent diagnostic queries per project.
3. Provides an interactive datagrid supporting dynamic column sorting and multi-column grouping.
4. Performs cross-connection table diffing (schema + data) across any of the supported databases and generates executable SQL synchronization scripts.

---

## 2. Goals, Non-Goals, and Anti-Goals

### Goals
* **Multi-Engine Database Connectivity:** Direct query execution across PostgreSQL, MSSQL, Oracle, SQLite, and H2.
  * H2 embedded databases (specifically format 3 / H2 2.x+ `.mv.db` files) supported via an embedded Java/JDBC bridge runner.
* **Project-Centric Organization:** Connections, saved queries, and execution history are scoped per project.
* **Frequent Query Tracking:** Automatically record query execution counts, execution durations, and timestamps; allow pinning and categorizing frequent diagnostic queries.
* **Interactive Datagrid (Tabulator):** Display query result sets with high responsiveness:
  * Multi-column sorting (ascending, descending, neutral).
  * Grouping by one or more columns with collapsible parent rows and row counts (native, 100% open-source via Tabulator).
  * Global search/filter across all returned records.
  * Multi-query execution: run query at cursor or selection (`Ctrl+Enter`), with tabbed result sets when multiple queries execute.
* **Universal Cross-Database Table Diff Engine:**
  * Select source connection/table and target connection/table across **any** of the 5 supported databases (Postgres, MSSQL, Oracle, SQLite, H2).
  * Compare schema structures (column names, normalized data types, nullability, primary keys) and output target-compliant DDL statements (`ALTER TABLE ADD COLUMN`, etc.).
  * Compare row data (matched via primary keys or user-selected identifier columns) and detect inserts, updates, and deletes.
  * Generate formatted, transaction-wrapped SQL migration/sync scripts (`ALTER TABLE`, `INSERT`, `UPDATE`, `DELETE`) tailored to the target database dialect.
* **Desktop Application:** Standalone desktop app running locally on user workstations.

### Non-Goals
* Full database administration suite (e.g., user role permissions management, server configuration tuning, automated backups).
* Visual query builder / drag-and-drop query generator (the primary audience are engineers and analysts writing diagnostic SQL).
* Continuous CDC / real-time streaming replication.

### Anti-Goals
* Unattended or silent database modification: The diff tool must NEVER execute sync scripts automatically on target databases without explicit user review, confirmation, and invocation.
* Memory exhaustion from unbounded queries: Queries enforce default safe limits (e.g., 5,000 rows preview with explicit override toggle).

---

## 3. Constraints & Tech Stack

* **Platform:** Runs on local desktop environments (Linux, macOS, Windows).
* **Tech Stack:** Python 3 desktop application runtime combining a Python core (PySide6 / `pywebview`) with a modern embedded web UI.
* **Driver Requirements:**
  * **Oracle:** Pure Python thin driver (`python-oracledb`) — no Oracle Instant Client required.
  * **MSSQL:** Pure DB-API driver (`pymssql`).
  * **PostgreSQL:** `psycopg` (v3).
  * **SQLite:** Standard library `sqlite3`.
  * **H2:** Embedded format 3 (`.mv.db`) supported via a lightweight JDBC bridge runner utilizing H2 2.x JAR.
* **Datagrid Framework:** Tabulator (MIT licensed, open-source) — provides out-of-the-box multi-column grouping, hierarchical collapsible rows, and virtual rendering with zero commercial license restrictions.

---

## 4. Evaluated Approaches & Selection

1. **Approach 1: Electron + React with AG Grid & Monaco Editor**
   * High UI polish, but heavy runtime footprint and AG Grid restricts multi-column grouping to its paid commercial Enterprise tier.
2. **Approach 2: Python Desktop with Embedded Web Datagrid (Tabulator) — [SELECTED]**
   * Python core manages database drivers, project SQLite state, and data diffing logic.
   * UI runs via desktop window embedding Tabulator + SQL editor for zero-license-cost multi-column grouping and query execution.
   * Leverages team familiarity with Python and rich data processing ecosystem.
3. **Approach 3: JVM Desktop (Compose Multiplatform / JavaFX)**
   * Native JDBC everywhere, but building complex multi-column grouping datagrids in Java desktop frameworks requires significantly more effort and maintenance.

---

## 5. System Architecture & Component Specification

```
+------------------------------------------------------------------------+
|                          Desktop UI Layer                              |
|  +--------------------+  +----------------------+  +----------------+  |
|  | Project & Conn Nav |  | SQL Editor & History |  | Table Diff UI  |  |
|  +--------------------+  +----------------------+  +----------------+  |
|  +------------------------------------------------------------------+  |
|  |         Interactive Datagrid (Tabulator: Multi-Group, Sort)      |  |
|  |         [Result Tab 1]  [Result Tab 2] ...                       |  |
|  +------------------------------------------------------------------+  |
+-----------------------------------^------------------------------------+
                                    | (Local API / IPC)
+-----------------------------------v------------------------------------+
|                      Python Application Core                           |
|  +------------------+  +-------------------+  +---------------------+  |
|  | Project Manager  |  | Query History &   |  | Universal Table     |  |
|  | & Connection Mgr |  | Frequent Tracker  |  | Diff & Sync Engine  |  |
|  +------------------+  +-------------------+  +---------------------+  |
|  +------------------------------------------------------------------+  |
|  |             Database Connector Abstraction Layer                 |  |
|  |  [Postgres]   [MSSQL]   [Oracle]   [SQLite]   [H2 Embedded/TCP]  |  |
|  +------------------------------------------------------------------+  |
+-----------------------------------+------------------------------------+
                                    |
                           +--------v---------+
                           |  ~/.dbviewer.db  | (Local Project & Query Store)
                           +------------------+
```

### 5.1 Local Metadata Store (`~/.dbviewer/dbviewer.db`)

* **`projects`**: `id`, `name`, `description`, `created_at`, `updated_at`
* **`connections`**: `id`, `project_id`, `name`, `engine_type` (`postgres`, `mssql`, `oracle`, `sqlite`, `h2`), `host`, `port`, `database_name`, `username`, `password_encrypted`, `file_path` (for SQLite / H2 embedded), `connection_options_json`
* **`queries`**: `id`, `project_id`, `connection_id`, `name`, `sql_text`, `is_pinned`, `execution_count`, `last_executed_at`, `created_at`
* **`query_history`**: `id`, `project_id`, `connection_id`, `sql_text`, `executed_at`, `duration_ms`, `row_count`, `status`, `error_message`

### 5.2 Database Connector Layer

Every database engine implements the `BaseDatabaseConnector` interface:
* `test_connection() -> ConnectionResult`
* `execute_query(sql: str, max_rows: int) -> List[QueryResult]` (supports single or multi-statement returning multiple result sets)
* `get_tables() -> List[str]`
* `get_table_schema(table_name: str) -> TableSchema` (columns, types, nullability, primary keys)
* `fetch_table_rows(table_name: str, key_columns: List[str]) -> TableData`

**Engine Connectors:**
* **PostgreSQL:** `psycopg` v3.
* **MSSQL:** `pymssql`.
* **Oracle:** `python-oracledb` (thin mode).
* **SQLite:** Python `sqlite3`.
* **H2:** Embedded format 3 (`.mv.db`) supported through a lightweight JDBC bridge runner executing against H2 2.x JAR, as well as optional H2 TCP mode.

### 5.3 Interactive Datagrid & Query Workspace

* **Query Editor:** Syntax-highlighted SQL editor with:
  * Execution shortcut: `Ctrl+Enter` (or `Cmd+Enter` on macOS). Executes selection, or current query at cursor.
  * Frequent queries panel: surfaces most frequently run queries per project, plus pinned queries for one-click execution.
  * Query execution history drawer: past executions with timings and status.
* **Datagrid Capabilities (Powered by Tabulator):**
  * **Multi-Column Grouping:** Drag or select multiple columns to group by (e.g. `Region` -> `Category`). Generates collapsible group headers with count summaries.
  * **Multi-Column Sorting:** Sort by one or multiple columns (Shift-click).
  * **Search & Filter:** Instant client-side text filtering across columns.
  * **Multi-Result Tabs:** If a script executes multiple `SELECT` queries, each result set renders in its own labeled tab.
  * **Export:** One-click export to CSV, JSON, or SQL INSERTs.

### 5.4 Universal Table Diff & Sync Generation Engine

The diff engine supports cross-database comparisons between any of the 5 supported engines:

1. **Schema Normalization & Comparison:**
   * Reads column metadata for Source Table and Target Table.
   * Maps engine-specific types to a normalized representation (e.g. `VARCHAR`, `INTEGER`, `NUMERIC`, `TIMESTAMP`, `BOOLEAN`).
   * Detects:
     * Missing columns in target: generates target-dialect DDL (`ALTER TABLE ... ADD COLUMN ...`).
     * Type discrepancies: generates warnings or type conversion statements where supported.
2. **Key Matching:**
   * Automatically resolves Primary Keys for both tables.
   * If PK is missing or mismatched, allows the user to select one or more matching key columns.
3. **Data Diffing Algorithm:**
   * Fetches records from source and target indexed by the key.
   * Detects:
     * **Inserts:** Rows in Source missing in Target -> generates target-dialect `INSERT` statements.
     * **Updates:** Rows in both with differing values -> generates targeted `UPDATE ... SET ... WHERE ...` (only modifying changed columns).
     * **Deletes:** Rows in Target missing in Source -> optional/configurable `DELETE FROM ... WHERE ...`.
4. **Dialect-Specific SQL Generator:**
   * Emits syntax appropriate for the target database:
     * Quote identifiers: `"` for Postgres/Oracle/H2, `[]` for MSSQL, `` ` `` or `"` for SQLite.
     * Boolean and Timestamp literals formatted for target engine.
     * Wrapped in a transaction block (`BEGIN TRANSACTION ... COMMIT`).
   * Displays the generated SQL in a review dialog with diff statistics (e.g. `+12 Inserts, ~4 Updates, -1 Delete, +1 Schema change`).
   * Offers "Copy SQL", "Save SQL file", and "Execute on Target Database" (with explicit safety confirmation).

---

## 6. What's Left to the Builder

* Selection of PySide6 `QWebEngineView` or `pywebview` based on local environment packaging.
* Dark / Light mode styling theme.
* Batch size tuning for large table diffs (streaming diff in chunks of 5,000 rows).
