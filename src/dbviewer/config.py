"""Configuration and defaults for DBViewer."""

from pathlib import Path
from typing import Optional, Union

APP_NAME = "DBViewer"
DEFAULT_DB_DIR = Path.home() / ".dbviewer"
DEFAULT_DB_PATH = DEFAULT_DB_DIR / "dbviewer.db"
DEFAULT_MAX_ROWS = 5000
DEFAULT_API_HOST = "127.0.0.1"
DEFAULT_API_PORT = 5000

SUPPORTED_ENGINES = ("sqlite", "postgres", "mssql", "oracle", "h2")


def get_default_db_path() -> Path:
    """Return the default SQLite database path, ensuring the directory exists."""
    DEFAULT_DB_DIR.mkdir(parents=True, exist_ok=True)
    return DEFAULT_DB_PATH


def resolve_db_path(db_path: Optional[Union[str, Path]] = None) -> str:
    """Resolve database path string, using default if None."""
    if db_path is None:
        return str(get_default_db_path())
    path_str = str(db_path)
    if path_str != ":memory:":
        Path(path_str).parent.mkdir(parents=True, exist_ok=True)
    return path_str
