"""H2 connector using the H2 JDBC Shell (H2 2.x / MVStore format 3).

Requires Java and an H2 jar. Configure ``jar_path`` or DBVIEWER_H2_JAR.
The connector uses the H2 Shell command line, keeping JDBC integration free
of a mandatory Python bridge dependency.
"""
import os
import shutil
import subprocess
import time
from datetime import date, datetime, time as datetime_time
from decimal import Decimal
from src.dbviewer.connectors._dbapi import DBAPIConnector
from src.dbviewer.connectors.base import ColumnInfo, QueryResult, TableSchema


class H2Connector(DBAPIConnector):
    dialect="h2"
    def __init__(self,config):
        super().__init__(config)
        self._tcp=bool(config.get("host"))

    def build_jdbc_url(self):
        if self._tcp:
            return f"jdbc:h2:tcp://{self.config['host']}:{self.config.get('port',9092)}/{self.config.get('database',self.config.get('database_name',''))}"
        path=self.config.get("file_path")
        if not path: raise ValueError("H2 connection requires file_path or host")
        if path.endswith(".mv.db"): path=path[:-6]
        return "jdbc:h2:file:"+os.path.abspath(path)

    def _command(self,sql):
        jar=self.config.get("jar_path") or os.environ.get("DBVIEWER_H2_JAR")
        if not jar or not os.path.isfile(jar): raise RuntimeError("H2 requires an H2 2.x jar; set jar_path or DBVIEWER_H2_JAR")
        java=shutil.which("java")
        if not java: raise RuntimeError("Java runtime not found")
        command=[java,"-cp",jar,"org.h2.tools.Shell","-url",self.build_jdbc_url(),"-user",self.config.get("user",self.config.get("username","sa")),"-password",self.config.get("password","") ,"-sql",sql]
        result=subprocess.run(command,capture_output=True,text=True,timeout=self.config.get("timeout",30),check=False)
        if result.returncode: raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        return result.stdout

    @staticmethod
    def _table_rows(output):
        """Parse the Shell's pipe-delimited result table, excluding headings."""
        rows=[]
        for line in output.splitlines():
            line=line.strip()
            if not line or line.startswith("(") or set(line) <= set("-+ "): continue
            if "|" in line: values=[part.strip() for part in line.strip("|").split("|")]
            else: values=[line]
            rows.append(values)
        if len(rows)>1: return rows[1:]
        return []

    def _get_connection(self):
        raise RuntimeError("H2 shell connector does not expose DB-API connections")
    def test_connection(self):
        try: self._command("SELECT 1"); return {"success":True}
        except Exception as exc: return {"success":False,"error":str(exc)}
    def execute_query(self,sql,max_rows=5000):
        from src.dbviewer.connectors.sqlite_connector import _split_statements
        results=[]
        for statement in _split_statements(sql):
            started=time.perf_counter()
            try:
                raw=self._command(statement+f" FETCH FIRST {int(max_rows)} ROWS ONLY" if statement.lstrip().upper().startswith("SELECT") else statement)
                rows=self._table_rows(raw)
                first=next((line for line in raw.splitlines() if line.strip() and not line.lstrip().startswith("(") and not set(line.strip()) <= set("-+ ")),"")
                columns=[v.strip() for v in first.strip().strip("|").split("|")] if "|" in first else []
                if rows and not columns: columns=["result"]
                results.append(QueryResult(columns,rows[:max_rows],(time.perf_counter()-started)*1000,min(len(rows),max_rows)))
            except Exception as exc:
                results.append(QueryResult([],[],(time.perf_counter()-started)*1000,0,str(exc)))
        return results
    def get_tables(self):
        output=self._command("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA='PUBLIC' AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME")
        return [row[0] for row in self._table_rows(output) if row]
    def get_table_schema(self,table_name):
        # Query catalog via Shell; DDL metadata parsing can vary by console settings.
        output=self._command(f"SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA='PUBLIC' AND TABLE_NAME='{table_name.upper().replace(chr(39),chr(39)*2)}' ORDER BY ORDINAL_POSITION")
        rows=self._table_rows(output)
        cols=[]
        for row in rows:
            row=[x.strip() for x in row]
            if len(row)>=3 and row[0].upper()!="COLUMN_NAME" and row[0] and not set(row[0])<=set("-+"):
                cols.append(ColumnInfo(row[0],row[1],row[2].upper()=="YES"))
        return TableSchema(table_name,cols,[])

    def fetch_table_rows(self,table_name,key_columns,max_rows=100_000):
        safe_table=table_name.replace("'", "''")
        type_output=self._command(
            "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
            f"WHERE TABLE_SCHEMA='PUBLIC' AND TABLE_NAME='{safe_table.upper()}' ORDER BY ORDINAL_POSITION"
        )
        type_rows=self._table_rows(type_output)
        types={row[0].upper():row[1].upper() for row in type_rows if len(row)>=2 and row[0].upper()!="COLUMN_NAME"}
        ordering=" ORDER BY "+", ".join(self._identifier(c) for c in key_columns) if key_columns else ""
        output=self._command(f"SELECT * FROM {self._identifier(table_name)}{ordering} FETCH FIRST {int(max_rows)} ROWS ONLY")
        lines=[line.strip() for line in output.splitlines() if line.strip() and not line.strip().startswith("(") and not set(line.strip()) <= set("-+ ")]
        if not lines:return []
        header=[part.strip() for part in lines[0].strip("|").split("|")]
        def convert(column, value):
            value=value.strip()
            if not value or value.upper()=="NULL": return None
            kind=types.get(column.upper(), "")
            try:
                if kind in {"BOOLEAN", "BOOL"}: return value.upper() in {"TRUE", "1"}
                if kind in {"TINYINT", "SMALLINT", "INTEGER", "INT", "BIGINT"}: return int(value)
                if any(x in kind for x in ("NUMERIC", "DECIMAL")): return Decimal(value)
                if kind in {"REAL", "FLOAT", "DOUBLE"}: return float(value)
                if kind == "DATE": return date.fromisoformat(value)
                if kind.startswith("TIMESTAMP"): return datetime.fromisoformat(value)
                if kind.startswith("TIME"): return datetime_time.fromisoformat(value)
            except ValueError:
                return value
            return value
        return [dict(zip(header,[convert(name, part) for name,part in zip(header,line.strip("|").split("|"))])) for line in lines[1:]][:max_rows]
