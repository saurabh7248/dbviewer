"""SQLite metadata store for DBViewer projects, connections, queries, and history."""

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from src.dbviewer.config import resolve_db_path


class MetadataStore:
    """Manages application metadata stored in SQLite."""

    def __init__(self, db_path: Optional[Union[str, Any]] = None):
        self.db_path = resolve_db_path(db_path)
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = sqlite3.connect(
            self.db_path, check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.create_function(
            "dbviewer_normalized_name", 1, self._name_key, deterministic=True
        )

        with self._lock:
            with self._conn:
                self._conn.execute("PRAGMA foreign_keys = ON;")
                if self.db_path != ":memory:":
                    self._conn.execute("PRAGMA journal_mode = WAL;")
            self._init_schema()

    def _init_schema(self) -> None:
        """Initialize the database tables and indices if they do not exist."""
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS connections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    engine_type TEXT NOT NULL,
                    host TEXT,
                    port INTEGER,
                    database_name TEXT,
                    username TEXT,
                    password_encrypted TEXT,
                    file_path TEXT,
                    connection_options_json TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_connections_project ON connections(project_id);

                CREATE TABLE IF NOT EXISTS queries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    connection_id INTEGER REFERENCES connections(id) ON DELETE SET NULL,
                    name TEXT DEFAULT '',
                    sql_text TEXT NOT NULL,
                    is_pinned INTEGER DEFAULT 0,
                    execution_count INTEGER DEFAULT 0,
                    last_executed_at TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_queries_project_exec ON queries(project_id, execution_count DESC);
                CREATE INDEX IF NOT EXISTS idx_queries_project_pinned ON queries(project_id, is_pinned DESC, execution_count DESC);

                CREATE TABLE IF NOT EXISTS query_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    connection_id INTEGER REFERENCES connections(id) ON DELETE SET NULL,
                    sql_text TEXT NOT NULL,
                    executed_at TEXT NOT NULL,
                    duration_ms REAL NOT NULL,
                    row_count INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    error_message TEXT DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_query_history_project ON query_history(project_id, executed_at DESC);
                """
            )
            self._create_name_unique_indexes()

    def _create_name_unique_indexes(self) -> None:
        """Add normalized-name indexes after rejecting ambiguous legacy data."""
        project_keys = {}
        for row in self._conn.execute("SELECT name FROM projects"):
            name = row["name"]
            key = self._name_key(name)
            if not key:
                raise ValueError("Blank project name prevents metadata migration")
            if key in project_keys:
                raise ValueError(
                    f"Duplicate project name prevents metadata migration: {key!r}"
                )
            project_keys[key] = name

        connection_keys = {}
        for row in self._conn.execute("SELECT project_id, name FROM connections"):
            name = row["name"]
            key = (row["project_id"], self._name_key(name))
            if not key[1]:
                raise ValueError("Blank connection name prevents metadata migration")
            if key in connection_keys:
                raise ValueError(
                    "Duplicate connection name prevents metadata migration: "
                    f"{key[1]!r}"
                )
            connection_keys[key] = name

        # Rebuild older indexes in case a database was opened by an interrupted
        # version that used SQLite's narrower lower(trim()) normalization.
        self._conn.execute("DROP INDEX IF EXISTS idx_projects_name_normalized")
        self._conn.execute("DROP INDEX IF EXISTS idx_connections_project_name_normalized")
        self._conn.execute(
            """
            CREATE UNIQUE INDEX idx_projects_name_normalized
            ON projects(dbviewer_normalized_name(name))
            """
        )
        self._conn.execute(
            """
            CREATE UNIQUE INDEX idx_connections_project_name_normalized
            ON connections(project_id, dbviewer_normalized_name(name))
            """
        )

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _name_key(name: Any) -> str:
        if not isinstance(name, str):
            raise ValueError("Name must be a string")
        return name.strip().casefold()

    @staticmethod
    def _normalized_name(name: Any, entity: str) -> str:
        """Return a display-safe name or raise a user-facing validation error."""
        if not isinstance(name, str):
            raise ValueError(f"{entity} name must be a string")
        normalized = name.strip()
        if not normalized:
            raise ValueError(f"{entity} name must not be blank")
        return normalized

    @staticmethod
    def _is_name_collision(error: sqlite3.IntegrityError, index_name: str) -> bool:
        return index_name in str(error)

    def create_project(self, name: str, description: str = "") -> dict:
        """Create a new project and return its record."""
        name = self._normalized_name(name, "Project")
        now = self._now_iso()
        with self._lock:
            try:
                with self._conn:
                    cursor = self._conn.execute(
                        """
                        INSERT INTO projects (name, description, created_at, updated_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (name, description, now, now),
                    )
                    project_id = cursor.lastrowid
                    row = self._conn.execute(
                        "SELECT id, name, description, created_at, updated_at FROM projects WHERE id = ?",
                        (project_id,),
                    ).fetchone()
                    return dict(row)
            except sqlite3.IntegrityError as error:
                if self._is_name_collision(error, "idx_projects_name_normalized"):
                    raise ValueError(f"Project name already exists: {name}") from error
                raise

    def list_projects(self) -> List[dict]:
        """List all projects ordered by creation time."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, name, description, created_at, updated_at FROM projects ORDER BY id ASC"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_project(self, project_id: int) -> Optional[dict]:
        """Retrieve a project by ID."""
        with self._lock:
            row = self._conn.execute(
                "SELECT id, name, description, created_at, updated_at FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
            return dict(row) if row else None

    def delete_project(self, project_id: int) -> bool:
        """Delete a project and cascade deletion to connections and queries."""
        with self._lock:
            with self._conn:
                cursor = self._conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
                return cursor.rowcount > 0

    def copy_project(self, project_id: int, name: str) -> dict:
        """Copy a project and its connections without copying queries or history."""
        name = self._normalized_name(name, "Project")
        now = self._now_iso()
        with self._lock:
            try:
                with self._conn:
                    source = self._conn.execute(
                        "SELECT id, description FROM projects WHERE id = ?", (project_id,)
                    ).fetchone()
                    if not source:
                        raise ValueError(f"Project {project_id} does not exist")

                    cursor = self._conn.execute(
                        """
                        INSERT INTO projects (name, description, created_at, updated_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (name, source["description"], now, now),
                    )
                    copied_project_id = cursor.lastrowid
                    source_connections = self._conn.execute(
                        "SELECT * FROM connections WHERE project_id = ? ORDER BY id ASC",
                        (project_id,),
                    ).fetchall()
                    for connection in source_connections:
                        self._conn.execute(
                            """
                            INSERT INTO connections (
                                project_id, name, engine_type, host, port,
                                database_name, username, password_encrypted,
                                file_path, connection_options_json, created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                copied_project_id,
                                connection["name"],
                                connection["engine_type"],
                                connection["host"],
                                connection["port"],
                                connection["database_name"],
                                connection["username"],
                                connection["password_encrypted"],
                                connection["file_path"],
                                connection["connection_options_json"],
                                now,
                                now,
                            ),
                        )
                    row = self._conn.execute(
                        "SELECT id, name, description, created_at, updated_at FROM projects WHERE id = ?",
                        (copied_project_id,),
                    ).fetchone()
                    return dict(row)
            except sqlite3.IntegrityError as error:
                if self._is_name_collision(error, "idx_projects_name_normalized"):
                    raise ValueError(f"Project name already exists: {name}") from error
                raise

    def save_connection(self, project_id: int, connection_data: dict) -> dict:
        """Save a new database connection or update an existing one."""
        now = self._now_iso()
        conn_id = connection_data.get("id")

        with self._lock:
            try:
                with self._conn:
                    if conn_id is not None:
                        existing = self._conn.execute(
                            "SELECT * FROM connections WHERE id = ?", (conn_id,)
                        ).fetchone()
                        if existing:
                            if existing["project_id"] != project_id:
                                raise ValueError(
                                    f"Connection {conn_id} does not belong to project {project_id}"
                                )
                            name = connection_data["name"] if "name" in connection_data else existing["name"]
                            name = self._normalized_name(name, "Connection")
                            engine_type = connection_data["engine_type"] if "engine_type" in connection_data else existing["engine_type"]
                            host = connection_data["host"] if "host" in connection_data else existing["host"]
                            port = connection_data["port"] if "port" in connection_data else existing["port"]
                            database_name = connection_data["database_name"] if "database_name" in connection_data else existing["database_name"]
                            username = connection_data["username"] if "username" in connection_data else existing["username"]
                            if "password_encrypted" in connection_data:
                                password_encrypted = connection_data["password_encrypted"]
                            elif "password" in connection_data:
                                password_encrypted = connection_data["password"]
                            else:
                                password_encrypted = existing["password_encrypted"]
                            file_path = connection_data["file_path"] if "file_path" in connection_data else existing["file_path"]

                            if "connection_options_json" in connection_data:
                                raw = connection_data["connection_options_json"]
                                options = json.dumps(raw) if isinstance(raw, dict) else raw
                            elif "options" in connection_data or "connection_options" in connection_data:
                                raw = connection_data.get("options") or connection_data.get("connection_options")
                                options = json.dumps(raw) if raw is not None else "{}"
                            else:
                                options = existing["connection_options_json"]

                            self._conn.execute(
                                """
                                UPDATE connections
                                SET name = ?, engine_type = ?, host = ?, port = ?,
                                    database_name = ?, username = ?, password_encrypted = ?,
                                    file_path = ?, connection_options_json = ?, updated_at = ?
                                WHERE id = ?
                                """,
                                (
                                    name,
                                    engine_type,
                                    host,
                                    port,
                                    database_name,
                                    username,
                                    password_encrypted,
                                    file_path,
                                    options,
                                    now,
                                    conn_id,
                                ),
                            )
                            saved_id = conn_id
                        else:
                            name = self._normalized_name(connection_data.get("name", ""), "Connection")
                            engine_type = connection_data.get("engine_type", "")
                            host = connection_data.get("host")
                            port = connection_data.get("port")
                            database_name = connection_data.get("database_name")
                            username = connection_data.get("username")
                            password_encrypted = connection_data.get("password_encrypted") or connection_data.get("password")
                            file_path = connection_data.get("file_path")
                            options = connection_data.get("connection_options_json")
                            if options is None:
                                raw_options = connection_data.get("options") or connection_data.get("connection_options")
                                options = json.dumps(raw_options) if raw_options is not None else "{}"
                            elif isinstance(options, dict):
                                options = json.dumps(options)

                            cursor = self._conn.execute(
                                """
                                INSERT INTO connections (
                                    id, project_id, name, engine_type, host, port,
                                    database_name, username, password_encrypted,
                                    file_path, connection_options_json, created_at, updated_at
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    conn_id,
                                    project_id,
                                    name,
                                    engine_type,
                                    host,
                                    port,
                                    database_name,
                                    username,
                                    password_encrypted,
                                    file_path,
                                    options,
                                    now,
                                    now,
                                ),
                            )
                            saved_id = cursor.lastrowid
                    else:
                        name = self._normalized_name(connection_data.get("name", ""), "Connection")
                        engine_type = connection_data.get("engine_type", "")
                        host = connection_data.get("host")
                        port = connection_data.get("port")
                        database_name = connection_data.get("database_name")
                        username = connection_data.get("username")
                        password_encrypted = connection_data.get("password_encrypted") or connection_data.get("password")
                        file_path = connection_data.get("file_path")
                        options = connection_data.get("connection_options_json")
                        if options is None:
                            raw_options = connection_data.get("options") or connection_data.get("connection_options")
                            options = json.dumps(raw_options) if raw_options is not None else "{}"
                        elif isinstance(options, dict):
                            options = json.dumps(options)

                        cursor = self._conn.execute(
                            """
                            INSERT INTO connections (
                                project_id, name, engine_type, host, port,
                                database_name, username, password_encrypted,
                                file_path, connection_options_json, created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                project_id,
                                name,
                                engine_type,
                                host,
                                port,
                                database_name,
                                username,
                                password_encrypted,
                                file_path,
                                options,
                                now,
                                now,
                            ),
                        )
                        saved_id = cursor.lastrowid

                    row = self._conn.execute(
                        "SELECT * FROM connections WHERE id = ?", (saved_id,)
                    ).fetchone()
                    return dict(row)
            except sqlite3.IntegrityError as error:
                if self._is_name_collision(error, "idx_connections_project_name_normalized"):
                    raise ValueError(f"Connection name already exists in this project: {name}") from error
                raise

    def copy_connection(self, project_id: int, connection_id: int, name: str) -> dict:
        """Copy a connection into the same project with a new name."""
        name = self._normalized_name(name, "Connection")
        now = self._now_iso()
        with self._lock:
            try:
                with self._conn:
                    source = self._conn.execute(
                        "SELECT * FROM connections WHERE id = ?", (connection_id,)
                    ).fetchone()
                    if not source or source["project_id"] != project_id:
                        raise ValueError(
                            f"Connection {connection_id} does not belong to project {project_id}"
                        )
                    cursor = self._conn.execute(
                        """
                        INSERT INTO connections (
                            project_id, name, engine_type, host, port,
                            database_name, username, password_encrypted,
                            file_path, connection_options_json, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            project_id,
                            name,
                            source["engine_type"],
                            source["host"],
                            source["port"],
                            source["database_name"],
                            source["username"],
                            source["password_encrypted"],
                            source["file_path"],
                            source["connection_options_json"],
                            now,
                            now,
                        ),
                    )
                    row = self._conn.execute(
                        "SELECT * FROM connections WHERE id = ?", (cursor.lastrowid,)
                    ).fetchone()
                    return dict(row)
            except sqlite3.IntegrityError as error:
                if self._is_name_collision(error, "idx_connections_project_name_normalized"):
                    raise ValueError(f"Connection name already exists in this project: {name}") from error
                raise

    def list_connections(self, project_id: int) -> List[dict]:
        """List all connections belonging to a project."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM connections WHERE project_id = ? ORDER BY id ASC",
                (project_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_connection(self, connection_id: int) -> Optional[dict]:
        """Retrieve a connection by ID."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM connections WHERE id = ?",
                (connection_id,),
            ).fetchone()
            return dict(row) if row else None

    def delete_connection(self, connection_id: int) -> bool:
        """Delete a connection by ID."""
        with self._lock:
            with self._conn:
                cursor = self._conn.execute("DELETE FROM connections WHERE id = ?", (connection_id,))
                return cursor.rowcount > 0

    def record_query_execution(
        self,
        project_id: int,
        connection_id: int,
        sql_text: str,
        duration_ms: float,
        row_count: int,
        status: str,
        error: str = "",
    ) -> dict:
        """Record query execution into query history and update frequent queries count."""
        now = self._now_iso()
        cleaned_sql = sql_text.strip()

        with self._lock:
            with self._conn:
                # 1. Record in query_history
                hist_cursor = self._conn.execute(
                    """
                    INSERT INTO query_history (
                        project_id, connection_id, sql_text, executed_at,
                        duration_ms, row_count, status, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        connection_id,
                        cleaned_sql,
                        now,
                        duration_ms,
                        row_count,
                        status,
                        error or "",
                    ),
                )
                history_id = hist_cursor.lastrowid

                # 2. Update or insert into queries table
                existing = self._conn.execute(
                    "SELECT id, execution_count FROM queries WHERE project_id = ? AND sql_text = ?",
                    (project_id, cleaned_sql),
                ).fetchone()

                if existing:
                    self._conn.execute(
                        """
                        UPDATE queries
                        SET execution_count = execution_count + 1,
                            last_executed_at = ?,
                            connection_id = ?
                        WHERE id = ?
                        """,
                        (now, connection_id, existing["id"]),
                    )
                else:
                    self._conn.execute(
                        """
                        INSERT INTO queries (
                            project_id, connection_id, name, sql_text,
                            is_pinned, execution_count, last_executed_at, created_at
                        ) VALUES (?, ?, ?, ?, 0, 1, ?, ?)
                        """,
                        (project_id, connection_id, "", cleaned_sql, now, now),
                    )

                return {
                    "id": history_id,
                    "project_id": project_id,
                    "connection_id": connection_id,
                    "sql_text": cleaned_sql,
                    "executed_at": now,
                    "duration_ms": duration_ms,
                    "row_count": row_count,
                    "status": status,
                    "error_message": error or "",
                }

    def list_frequent_queries(self, project_id: int, limit: int = 10) -> List[dict]:
        """List queries ordered by pinned status and execution count."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, project_id, connection_id, name, sql_text,
                       is_pinned, execution_count, last_executed_at, created_at
                FROM queries
                WHERE project_id = ?
                ORDER BY is_pinned DESC, execution_count DESC, last_executed_at DESC
                LIMIT ?
                """,
                (project_id, limit),
            ).fetchall()
            result = []
            for r in rows:
                item = dict(r)
                item["is_pinned"] = bool(item["is_pinned"])
                result.append(item)
            return result

    def pin_query(self, query_id: int, is_pinned: bool) -> bool:
        """Pin or unpin a query."""
        with self._lock:
            with self._conn:
                cursor = self._conn.execute(
                    "UPDATE queries SET is_pinned = ? WHERE id = ?",
                    (1 if is_pinned else 0, query_id),
                )
                return cursor.rowcount > 0

    def get_query(self, query_id: int) -> Optional[dict]:
        """Retrieve a saved query by ID."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM queries WHERE id = ?",
                (query_id,),
            ).fetchone()
            if row:
                item = dict(row)
                item["is_pinned"] = bool(item["is_pinned"])
                return item
            return None

    def list_query_history(self, project_id: int, limit: int = 50) -> List[dict]:
        """Retrieve recent query execution history for a project."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM query_history
                WHERE project_id = ?
                ORDER BY executed_at DESC, id DESC
                LIMIT ?
                """,
                (project_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def close(self) -> None:
        """Close SQLite connection."""
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
