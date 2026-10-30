"""Flask API for projects, diagnostic queries, and reviewed table syncs."""
import dataclasses
import json
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

from src.dbviewer.config import DEFAULT_MAX_ROWS
from src.dbviewer.connectors.factory import get_connector
from src.dbviewer.diff.comparator import TableComparator
from src.dbviewer.diff.sql_generator import SQLSyncGenerator
from src.dbviewer.storage.metadata_store import MetadataStore


def _public_connection(value):
    value = dict(value)
    value.pop("password_encrypted", None)
    value.pop("password", None)
    value.pop("connection_options_json", None)
    return value


def _connector_config(value):
    config = dict(value)
    config["database"] = config.get("database_name")
    config["user"] = config.get("username")
    config["password"] = config.get("password_encrypted")
    config["connection_options"] = json.loads(config.get("connection_options_json") or "{}")
    return config


def _jsonable(value):
    if dataclasses.is_dataclass(value): return {k: _jsonable(v) for k,v in dataclasses.asdict(value).items()}
    if isinstance(value, dict): return {str(k): _jsonable(v) for k,v in value.items()}
    if isinstance(value, (list, tuple)): return [_jsonable(v) for v in value]
    return value


def create_app(store=None):
    app = Flask(__name__, static_folder=None)
    store = store or MetadataStore()
    comparator, generator, diffs = TableComparator(), SQLSyncGenerator(), {}
    ui_root = Path(__file__).resolve().parents[1] / "ui"

    @app.errorhandler(ValueError)
    def bad_request(exc): return jsonify({"error": str(exc)}), 400

    @app.errorhandler(Exception)
    def internal_error(exc):
        if isinstance(exc, HTTPException): return jsonify({"error":exc.description}),exc.code
        app.logger.exception("API request failed")
        return jsonify({"error": str(exc)}), 500

    @app.get("/")
    def index(): return send_from_directory(ui_root, "index.html")

    @app.get("/static/<path:filename>")
    def static_files(filename): return send_from_directory(ui_root / "static", filename)

    @app.get("/api/projects")
    def list_projects(): return jsonify(store.list_projects())

    @app.post("/api/projects")
    def create_project():
        data=request.get_json(silent=True) or {}
        if not data.get("name"): return jsonify({"error":"Project name is required"}),400
        return jsonify(store.create_project(data["name"],data.get("description", ""))),201

    @app.delete("/api/projects/<int:project_id>")
    def delete_project(project_id): return ("",204) if store.delete_project(project_id) else (jsonify({"error":"Project not found"}),404)

    @app.post("/api/projects/<int:project_id>/copy")
    def copy_project(project_id):
        if not store.get_project(project_id): return jsonify({"error":"Project not found"}),404
        data=request.get_json(silent=True) or {}
        if not data.get("name"): return jsonify({"error":"Project name is required"}),400
        return jsonify(store.copy_project(project_id, data["name"])),201

    @app.get("/api/projects/<int:project_id>/connections")
    def list_connections(project_id):
        if not store.get_project(project_id): return jsonify({"error":"Project not found"}),404
        return jsonify([_public_connection(c) for c in store.list_connections(project_id)])

    @app.post("/api/projects/<int:project_id>/connections")
    def save_connection(project_id):
        if not store.get_project(project_id): return jsonify({"error":"Project not found"}),404
        data=request.get_json(silent=True) or {}
        if not data.get("name") or not data.get("engine_type"): return jsonify({"error":"Connection name and engine_type are required"}),400
        saved=store.save_connection(project_id,data)
        return jsonify(_public_connection(saved)),201

    def get_project_connection(project_id, connection_id):
        if not store.get_project(project_id):
            return None, (jsonify({"error":"Project not found"}),404)
        record=store.get_connection(connection_id)
        if record is None or record["project_id"] != project_id:
            return None, (jsonify({"error":"Connection not found in project"}),404)
        return record, None

    @app.get("/api/projects/<int:project_id>/connections/<int:connection_id>")
    def get_project_connection_record(project_id, connection_id):
        record,error=get_project_connection(project_id,connection_id)
        if error: return error
        return jsonify(_public_connection(record))

    @app.put("/api/projects/<int:project_id>/connections/<int:connection_id>")
    def update_project_connection(project_id, connection_id):
        record,error=get_project_connection(project_id,connection_id)
        if error: return error
        data=dict(request.get_json(silent=True) or {})
        data["id"]=record["id"]
        if data.get("password") == "": data.pop("password")
        saved=store.save_connection(project_id,data)
        return jsonify(_public_connection(saved))

    @app.delete("/api/projects/<int:project_id>/connections/<int:connection_id>")
    def delete_project_connection(project_id, connection_id):
        _,error=get_project_connection(project_id,connection_id)
        if error: return error
        store.delete_connection(connection_id)
        return "",204

    @app.post("/api/projects/<int:project_id>/connections/<int:connection_id>/copy")
    def copy_project_connection(project_id, connection_id):
        _,error=get_project_connection(project_id,connection_id)
        if error: return error
        data=request.get_json(silent=True) or {}
        if not data.get("name"): return jsonify({"error":"Connection name is required"}),400
        return jsonify(_public_connection(store.copy_connection(project_id,connection_id,data["name"]))),201

    @app.post("/api/connections/test")
    def test_connection():
        data=request.get_json(silent=True) or {}
        try: result=get_connector(data).test_connection()
        except Exception as exc: result={"success":False,"error":str(exc)}
        return jsonify(result),200 if result.get("success") else 400

    def get_connection_or_404(connection_id):
        record=store.get_connection(connection_id)
        if record is None: return None,None
        return record,get_connector(_connector_config(record))

    @app.get("/api/connections/<int:connection_id>/tables")
    def get_tables(connection_id):
        record,connector=get_connection_or_404(connection_id)
        if record is None: return jsonify({"error":"Connection not found"}),404
        return jsonify(connector.get_tables())

    @app.post("/api/query/run")
    def run_query():
        data=request.get_json(silent=True) or {}
        project_id,connection_id,sql=data.get("project_id"),data.get("connection_id"),data.get("sql","")
        if not project_id or not connection_id or not sql.strip(): return jsonify({"error":"project_id, connection_id and sql are required"}),400
        record=store.get_connection(connection_id)
        if record is None or record["project_id"] != project_id: return jsonify({"error":"Connection not found in project"}),404
        max_rows=max(1,min(int(data.get("max_rows",DEFAULT_MAX_ROWS)),100000))
        started=time.perf_counter()
        results=get_connector(_connector_config(record)).execute_query(sql,max_rows=max_rows)
        duration=(time.perf_counter()-started)*1000
        has_error=any(r.error for r in results)
        row_count=sum(r.row_count for r in results)
        store.record_query_execution(project_id,connection_id,sql,duration,row_count,"ERROR" if has_error else "SUCCESS", "; ".join(r.error for r in results if r.error))
        return jsonify({"results":[_jsonable(r) for r in results],"duration_ms":duration,"row_count":row_count}),200

    @app.get("/api/projects/<int:project_id>/queries/frequent")
    def frequent_queries(project_id):
        if not store.get_project(project_id): return jsonify({"error":"Project not found"}),404
        return jsonify(store.list_frequent_queries(project_id,int(request.args.get("limit",10))))

    @app.get("/api/projects/<int:project_id>/queries/history")
    def query_history(project_id):
        if not store.get_project(project_id): return jsonify({"error":"Project not found"}),404
        return jsonify(store.list_query_history(project_id,int(request.args.get("limit",50))))

    @app.post("/api/queries/<int:query_id>/pin")
    def pin_query(query_id):
        data=request.get_json(silent=True) or {}
        is_pinned=data.get("is_pinned",True)
        if not isinstance(is_pinned,bool): return jsonify({"error":"is_pinned must be a boolean"}),400
        if not store.pin_query(query_id,is_pinned): return jsonify({"error":"Query not found"}),404
        return jsonify({"success":True})

    @app.post("/api/diff/compare")
    def compare_tables():
        data=request.get_json(silent=True) or {}
        source_record,source=get_connection_or_404(int(data.get("source_connection_id",0)))
        target_record,target=get_connection_or_404(int(data.get("target_connection_id",0)))
        if source_record is None or target_record is None: return jsonify({"error":"Source or target connection not found"}),404
        result=comparator.compare_tables(source,data["source_table"],target,data["target_table"],data.get("key_columns"))
        token=str(__import__("uuid").uuid4()); diffs[token]=(result,target_record)
        return jsonify({"diff_id":token,"diff":_jsonable(result)})

    @app.post("/api/diff/generate-sql")
    def generate_sql():
        data=request.get_json(silent=True) or {}
        item=diffs.get(data.get("diff_id"))
        if item is None: return jsonify({"error":"Diff not found; compare the tables again"}),404
        result,target_record=item
        sql=generator.generate_sync_script(result,data.get("target_engine") or target_record["engine_type"],bool(data.get("include_deletes",True)))
        return jsonify({"sql":sql})

    @app.post("/api/diff/execute-sync")
    def execute_sync():
        data=request.get_json(silent=True) or {}
        if data.get("confirmed") is not True: return jsonify({"error":"Explicit confirmation is required"}),400
        record,connector=get_connection_or_404(int(data.get("target_connection_id",0)))
        if record is None: return jsonify({"error":"Target connection not found"}),404
        sql=data.get("sql","")
        if not sql.strip(): return jsonify({"error":"SQL script is required"}),400
        results=connector.execute_query(sql,max_rows=DEFAULT_MAX_ROWS)
        errors=[r.error for r in results if r.error]
        return jsonify({"success":not errors,"results":[_jsonable(r) for r in results],"errors":errors}),200 if not errors else 400

    app.metadata_store=store
    return app
