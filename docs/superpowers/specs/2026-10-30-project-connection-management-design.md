# Project and Connection Management Design

## Intent

Add visible project and connection management actions so users can delete projects and connections, edit connection settings, and make named copies. Prevent confusing duplicates by enforcing case-insensitive unique names.

## Goals

- Projects can be deleted and copied from the project list.
- Connections can be edited, deleted, and copied from the connection list.
- Every copy opens an in-app dialog with an editable name before it is created.
- Project names are unique across all projects; connection names are unique within their project. Uniqueness is case-insensitive and ignores surrounding whitespace.
- API and storage validation enforce the same naming rules so clients cannot bypass them.
- Existing database files continue to work through a schema migration.

## Non-goals

- Rename or edit project details (only connection editing is requested).
- Copy query history or saved/frequent queries into a copied project.
- Move connections between projects.
- Add automatic name suffixing.

## Approaches considered

1. **Copy dialogs with editable names and enforced uniqueness (selected).** Names are checked in the database and exposed as clear API validation errors. This makes create, edit, and copy consistent, though a name collision requires the user to choose another name.
2. **Copy dialogs with automatic numbered suffixes.** Convenient for copies but allows duplicates created through normal entry paths and makes naming less predictable. Not selected.

## Behavior and implementation decisions

- Project copy creates a new project with the supplied name and source description, then copies its connections under the new project while retaining each connection's settings and stored credential. It does not copy query records or execution history.
- Connection copy creates a connection in the same project, retaining its settings and credential and using the name supplied in the dialog.
- Editing a connection loads its non-secret settings into the existing connection form. Password input stays blank; leaving it blank preserves the saved credential. The API must never return stored credentials.
- Project deletion asks for confirmation because it cascades to connections, saved queries, and history. Connection deletion also asks for confirmation and relies on the existing foreign-key behavior to detach query/history references.
- The sidebar shows compact actions for each project and connection: edit where applicable, copy, and delete. Actions must not also trigger selecting the row.
- Name validation trims surrounding whitespace, rejects blank values, and applies case-insensitive uniqueness. A database unique index provides race-safe enforcement; storage converts collisions to a clear `ValueError`, which the API returns as HTTP 400.
- The existing uncommitted async form-reset fix in `app.js` is unrelated and must be preserved.

## Constraints

- Keep the existing Flask, SQLite metadata-store, and vanilla JavaScript architecture.
- Do not expose saved passwords in project/connection listing or editing responses.
- Preserve current connection update behavior where an omitted password keeps the existing one.
- Add storage and API tests for uniqueness, edit, delete, and copy semantics, plus UI asset/handler coverage where the current test setup supports it.

## Acceptance criteria

- Creating or renaming a project to another project's name (case-insensitive, after trimming) returns a clear validation error.
- Creating, editing, or copying a connection to a name already used in the same project returns a clear validation error; the same connection name remains allowed in a different project.
- Project copy dialog and connection copy dialog allow choosing the name before submission.
- A copied project contains copied connections and retains their settings, while its query/history collections start empty.
- Connection edit persists changed fields and preserves the existing credential when the password field is blank.
- Project and connection delete controls invoke their APIs and refresh selection and lists correctly.
- No management response includes stored credentials.
