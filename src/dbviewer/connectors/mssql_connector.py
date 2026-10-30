"""Microsoft SQL Server connector backed by pymssql."""
import pymssql
from src.dbviewer.connectors._dbapi import DBAPIConnector
from src.dbviewer.connectors.base import ColumnInfo, TableSchema


class MSSQLConnector(DBAPIConnector):
    dialect="mssql"
    def _get_connection(self):
        c=self.config
        return pymssql.connect(server=c.get("host"),port=str(c.get("port",1433)),database=c.get("database",c.get("database_name")),user=c.get("user",c.get("username")),password=c.get("password"),**c.get("connection_options",{}))
    def get_tables(self):
        conn=self._get_connection()
        try:
            cur=conn.cursor(); cur.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME"); return [r[0] for r in cur.fetchall()]
        finally: conn.close()
    def get_table_schema(self,table_name):
        schema, separator, table = table_name.rpartition(".")
        if not separator:
            table, schema = table_name, None
        conn=self._get_connection()
        try:
            cur=conn.cursor(); cur.execute("SELECT c.COLUMN_NAME,c.DATA_TYPE,c.IS_NULLABLE,c.COLUMN_DEFAULT,CASE WHEN k.COLUMN_NAME IS NULL THEN 0 ELSE 1 END FROM INFORMATION_SCHEMA.COLUMNS c LEFT JOIN (SELECT ku.COLUMN_NAME FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE ku ON ku.CONSTRAINT_NAME=tc.CONSTRAINT_NAME AND ku.TABLE_SCHEMA=tc.TABLE_SCHEMA AND ku.TABLE_NAME=tc.TABLE_NAME WHERE tc.CONSTRAINT_TYPE='PRIMARY KEY' AND tc.TABLE_NAME=%s AND (%s IS NULL OR tc.TABLE_SCHEMA=%s)) k ON k.COLUMN_NAME=c.COLUMN_NAME WHERE c.TABLE_NAME=%s AND (%s IS NULL OR c.TABLE_SCHEMA=%s) ORDER BY c.ORDINAL_POSITION",(table,schema,schema,table,schema,schema))
            rows=cur.fetchall(); cols=[ColumnInfo(r[0],r[1],r[2]=="YES",bool(r[4]),r[3]) for r in rows]; return TableSchema(table_name,cols,[x.name for x in cols if x.is_primary_key])
        finally: conn.close()
