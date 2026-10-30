"""Oracle connector using python-oracledb thin mode."""
import oracledb
from src.dbviewer.connectors._dbapi import DBAPIConnector
from src.dbviewer.connectors.base import ColumnInfo, TableSchema


class OracleConnector(DBAPIConnector):
    dialect="oracle"
    def _get_connection(self):
        c=self.config
        dsn=c.get("dsn") or oracledb.makedsn(c.get("host"),c.get("port",1521),service_name=c.get("service_name",c.get("database",c.get("database_name"))))
        return oracledb.connect(user=c.get("user",c.get("username")),password=c.get("password"),dsn=dsn,**c.get("connection_options",{}))
    def get_tables(self):
        conn=self._get_connection()
        try:
            cur=conn.cursor(); cur.execute("SELECT table_name FROM user_tables ORDER BY table_name"); return [r[0] for r in cur.fetchall()]
        finally: conn.close()
    def get_table_schema(self,table_name):
        conn=self._get_connection()
        try:
            cur=conn.cursor(); cur.execute("SELECT c.column_name,c.data_type,c.nullable,c.data_default,CASE WHEN k.column_name IS NULL THEN 0 ELSE 1 END FROM user_tab_columns c LEFT JOIN (SELECT cc.column_name FROM user_constraints co JOIN user_cons_columns cc ON cc.constraint_name=co.constraint_name WHERE co.constraint_type='P' AND co.table_name=:table_name) k ON k.column_name=c.column_name WHERE c.table_name=:table_name ORDER BY c.column_id",table_name=table_name.upper())
            rows=cur.fetchall(); cols=[ColumnInfo(r[0],r[1],r[2]=="Y",bool(r[4]),r[3]) for r in rows]; return TableSchema(table_name,cols,[x.name for x in cols if x.is_primary_key])
        finally: conn.close()
