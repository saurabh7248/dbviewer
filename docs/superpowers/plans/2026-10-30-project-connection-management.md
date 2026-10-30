# Project and Connection Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add delete, edit, and named-copy actions for projects and connections, with case-insensitive unique names enforced in storage and API.

**Architecture:** Keep Flask routes, SQLite `MetadataStore`, and the existing vanilla JavaScript dialogs/sidebar. Storage owns validation, migration, and transactional copies; the API exposes safe records and errors; the UI adds action controls and modal copy/edit forms.

**Tech Stack:** Python, SQLite, Flask, pytest, HTML, CSS, vanilla JavaScript.

**Spec:** `docs/superpowers/specs/2026-10-30-project-connection-management-design.md`

## Global Constraints

- Project names are unique across all projects; connection names are unique within their project. Uniqueness is case-insensitive and ignores surrounding whitespace.
- Project copy creates a new project with the supplied name and source description, then copies its connections under the new project while retaining each connection's settings and stored credential. It does not copy query records or execution history.
- Connection copy creates a connection in the same project, retaining its settings and credential and using the name supplied in the dialog.
- Editing a connection loads its non-secret settings into the existing connection form. Password input stays blank; leaving it blank preserves the saved credential. The API must never return stored credentials.
- Project deletion asks for confirmation because it cascades to connections, saved queries, and history. Connection deletion also asks for confirmation and relies on the existing foreign-key behavior to detach query/history references.
- The existing uncommitted async form-reset fix in `app.js` is unrelated and must be preserved.

## Review Focus

- Existing duplicate names in a pre-migration metadata database could prevent creation of the unique indexes: test migration behavior or explicitly normalize/reject duplicates safely in the migration task.
- Whitespace-only names and names differing only by case must be rejected consistently: pin in storage validation tests.
- A failed project copy must not leave a partial project or connections: pin transaction rollback in storage tests.
- Editing a connection with a blank password must retain its credential: pin in storage/API tests.
- Sidebar action clicks must not also select the project/connection: verify in UI behavior or focused JS test if the harness can exercise it.

---

### Task 1: Storage uniqueness, edit, and copy behavior

**Files:**
- Modify: `src/dbviewer/storage/metadata_store.py`
- Test: `tests/test_metadata_store.py`

**Interfaces:**
- Produces `copy_project(project_id: int, name: str) -> dict`.
- Produces `copy_connection(project_id: int, connection_id: int, name: str) -> dict`.
- Existing `create_project`, `save_connection`, and delete methods retain their signatures.

- [x] **Step 1: Write failing tests** for globally unique case-insensitive trimmed project names; per-project unique case-insensitive trimmed connection names; blank names; project copy preserving description and connection settings/credential but excluding queries/history; connection copy preserving settings/credential; invalid source ownership; transactional rollback on duplicate destination name; and updates excluding the record itself from uniqueness checks.
- [x] **Step 2: Run** `pytest tests/test_metadata_store.py -q` and confirm the new assertions fail for missing behavior.
- [x] **Step 3: Implement** normalized name validation, unique indexes on `projects(lower(trim(name)))` and `connections(project_id, lower(trim(name)))`, and transactional copy methods. Before creating indexes on an existing DB, detect existing normalized duplicates and raise a clear migration error naming the collision instead of silently changing user data.
- [x] **Step 4: Run** `pytest tests/test_metadata_store.py -q`; all storage tests pass.
- [ ] **Step 5: Commit** as `feat: enforce unique project and connection names` (blocked: `.git` is read-only in the workspace sandbox).

### Task 2: Management API routes and safe edit records

**Files:**
- Modify: `src/dbviewer/api/app.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes Task 1 `copy_project(project_id, name)` and `copy_connection(project_id, connection_id, name)`.
- Adds `POST /api/projects/<id>/copy` with JSON `{name}`.
- Adds `GET /api/projects/<id>/connections/<connection_id>` and `PUT /api/projects/<id>/connections/<connection_id>`; responses contain non-secret connection fields, never password values.
- Adds `DELETE /api/projects/<id>/connections/<connection_id>` and `POST /api/projects/<id>/connections/<connection_id>/copy` with JSON `{name}`.

- [x] **Step 1: Write failing API tests** for project copy, connection copy, connection safe read/update, delete and not-found/ownership responses, name collision errors, and absence of stored password in every response. Tests were present on resume; the original RED output was not recorded.
- [x] **Step 2: Run** `pytest tests/test_api.py -q`. (Focused green run on resume: 17 passed; expected RED output was not recorded before interruption.)
- [x] **Step 3: Implement** the routes with project ownership checks, safe serialization, and HTTP 400 validation responses.
- [x] **Step 4: Run** `pytest tests/test_api.py -q`; all API tests pass.
- [ ] **Step 5: Commit** as `feat: expose project and connection management APIs` (blocked: `.git` is read-only in this workspace).

### Task 3: Sidebar actions and named copy/edit dialogs

**Files:**
- Modify: `src/dbviewer/ui/index.html`
- Modify: `src/dbviewer/ui/static/css/styles.css`
- Modify: `src/dbviewer/ui/static/js/app.js`
- Test: `tests/test_ui_assets.py` and add a focused JavaScript test only if the repository already supports it without adding a runtime dependency.

**Interfaces:**
- Consumes Task 2 routes.
- Uses the existing project form for new-project creation and the existing connection form for add/edit; add a reusable copy-name dialog for both project and connection copies.

- [x] **Step 1: Add/extend UI assertions** for management controls, dialogs, accessible names, and action hooks; verify async submit handlers capture forms before awaits.
- [x] **Step 2: Run** `pytest tests/test_ui_assets.py -q` and confirm the new assertions fail. (Observed expected missing-dialog failure on first run.)
- [x] **Step 3: Implement** project copy/delete controls and connection edit/copy/delete controls. Stop action propagation. Confirm destructive deletes. On edit, load safe connection data, keep password blank, send update by PUT, and preserve blank password semantics. Copy dialogs require a user-entered name and display API uniqueness errors. Refresh lists and clear stale current-connection state after deletion.
- [x] **Step 4: Run** `pytest tests/test_ui_assets.py -q` and any focused JS check available.
- [ ] **Step 5: Commit** as `feat: add project and connection management controls` (blocked: `.git` is read-only in this workspace).

### Task 4: Whole-change verification and review

**Files:** all files changed in Tasks 1–3.

- [x] Run `pytest -q`, `node --check src/dbviewer/ui/static/js/app.js`, and `git diff --check`.
- [ ] Review the whole diff against the design, especially migration behavior, transaction boundaries, secret handling, and stale UI selection after deletion.
- [ ] Commit any required fixes and record final verification evidence (commit unavailable because `.git` is read-only).
