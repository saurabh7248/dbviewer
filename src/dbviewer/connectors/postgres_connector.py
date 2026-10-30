"""PostgreSQL connector backed by psycopg 3."""
import psycopg
from src.dbviewer.connectors._dbapi import DBAPIConnector
from src.dbviewer.connectors.base import ColumnInfo, TableSchema


class PostgresConnector(DBAPIConnector):
    dialect = "postgres"

    def _get_connection(self):
        c = self.config
        return psycopg.connect(host=c.get("host"), port=c.get("port", 5432), dbname=c.get("database", c.get("database_name")), user=c.get("user", c.get("username")), password=c.get("password"), **c.get("connection_options", {}))

    def get_tables(self):
        conn = self._get_connection()
        try:
            cur = conn.cursor(); cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema() AND table_type='BASE TABLE' ORDER BY table_name")
            return [r[0] for r in cur.fetchall()]
        finally: conn.close()

    def get_table_schema(self, table_name):
        conn = self._get_connection()
        try:
            cur=conn.cursor(); cur.execute("SELECT c.column_name,c.data_type,c.is_nullable,c.column_default, CASE WHEN k.column_name IS NULL THEN 0 ELSE 1 END FROM information_schema.columns c LEFT JOIN (SELECT kcu.column_name FROM information_schema.table_constraints tc JOIN information_schema.key_column_usage kcu USING (constraint_name,table_schema,table_name) WHERE tc.constraint_type='PRIMARY KEY' AND tc.table_schema=current_schema() AND tc.table_name=%s) k USING(column_name) WHERE c.table_schema=current_schema() AND c.table_name=%s ORDER BY c.ordinal_position", (table_name,table_name))
            rows=cur.fetchall(); cols=[ColumnInfo(r[0],r[1],r[2]=="YES",bool(r[4]),r[3]) for r in rows]
            return TableSchema(table_name,cols,[x.name for x in cols if x.is_primary_key])
        finally: conn.close()
