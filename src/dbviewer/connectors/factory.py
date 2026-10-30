"""Construct a connector from a stored connection configuration."""
from src.dbviewer.connectors.sqlite_connector import SQLiteConnector


def get_connector(connection_config: dict):
    engine = str(connection_config.get("engine_type", "")).strip().lower()
    if engine == "sqlite":
        return SQLiteConnector(connection_config)
    if engine in {"postgres", "postgresql"}:
        from src.dbviewer.connectors.postgres_connector import PostgresConnector
        return PostgresConnector(connection_config)
    if engine in {"mssql", "sqlserver", "sql_server"}:
        from src.dbviewer.connectors.mssql_connector import MSSQLConnector
        return MSSQLConnector(connection_config)
    if engine == "oracle":
        from src.dbviewer.connectors.oracle_connector import OracleConnector
        return OracleConnector(connection_config)
    if engine == "h2":
        from src.dbviewer.connectors.h2_connector import H2Connector
        return H2Connector(connection_config)
    raise ValueError(f"Unsupported engine type: {engine or '<missing>'}")
