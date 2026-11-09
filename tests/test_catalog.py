from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from tang.catalog import (
    CatalogError,
    forget_project,
    open_catalog,
    recall,
    sync_project,
)
from tang.cli import main
from tang.project import resolve_project
from tang.storage import open_database, project_data_path

SYNCED_AT = datetime(2026, 11, 9, 21, 30, tzinfo=timezone.utc)


def _insert_session(
    connection: sqlite3.Connection,
    *,
    project_key: str,
    source_id: str,
    adapter: str,
    native_id: str,
    handle: str,
    title: str,
    search_text: str,
    native_available: int = 1,
    updated_at: str = "2026-11-01T00:00:00Z",
) -> None:
    content = json.dumps(
        {"display_name": title, "schema_version": 1},
        sort_keys=True,
        separators=(",", ":"),
    )
    connection.execute("BEGIN IMMEDIATE")
    connection.execute(
        """
        INSERT INTO sessions(
            source_id, project_key, adapter, source_namespace, native_id,
            locator, fingerprint_algorithm, fingerprint_value, project_hint,
            started_at, updated_at, health, indexed_at, native_available,
            session_handle, title
        ) VALUES (
            ?, ?, ?, 'fixture', ?,
            ?, 'sha256', 'fixture', '/project',
            '2026-11-01T00:00:00Z', ?, 'complete',
            '2026-11-01T00:00:00Z', ?, ?, ?
        )
        """,
        (
            source_id,
            project_key,
            adapter,
            native_id,
            f"fixture:{native_id}",
            updated_at,
            native_available,
            handle,
            title,
        ),
    )
    connection.execute(
        """
        INSERT INTO capsules(
            source_id, project_key, schema_version, content_json, search_text,
            byte_count, updated_at
        ) VALUES (?, ?, 1, ?, ?, ?, ?)
        """,
        (
            source_id,
            project_key,
            content,
            search_text,
            len(content.encode("utf-8")),
            updated_at,
        ),
    )
    connection.execute("COMMIT")


def _project_db(root: Path) -> tuple[object, Path, sqlite3.Connection]:
    root.mkdir()
    project = resolve_project(root)
    database = project_data_path(project)
    return project, database, open_database(database)


def test_sync_and_recall_span_projects_without_native_logs(tmp_path: Path) -> None:
    alpha, alpha_db, alpha_conn = _project_db(tmp_path / "alpha")
    beta, beta_db, beta_conn = _project_db(tmp_path / "beta")
    catalog_path = tmp_path / "catalog.db"
    try:
        _insert_session(
            alpha_conn,
            project_key=alpha.key,
            source_id="codex:fixture:books",
            adapter="codex",
            native_id="books",
            handle="C1",
            title="Reading list",
            search_text="five books to bring",
        )
        _insert_session(
            beta_conn,
            project_key=beta.key,
            source_id="grok:fixture:crash",
            adapter="grok",
            native_id="crash",
            handle="G1",
            title="Indexer crash",
            search_text="guard the empty catalog before ranking",
            updated_at="2026-11-02T00:00:00Z",
        )
        catalog = open_catalog(catalog_path)
        try:
            assert sync_project(
                catalog,
                alpha_conn,
                project_key=alpha.key,
                project_display=alpha.display_name,
                database_path=alpha_db,
                synced_at=SYNCED_AT,
            ).upserted == 1
            assert sync_project(
                catalog,
                beta_conn,
                project_key=beta.key,
                project_display=beta.display_name,
                database_path=beta_db,
                synced_at=SYNCED_AT,
            ).upserted == 1
            hits = recall(catalog, "book")
        finally:
            catalog.close()
    finally:
        alpha_conn.close()
        beta_conn.close()

    assert [hit.source_id for hit in hits] == ["codex:fixture:books"]
    assert hits[0].catalog_handle == "C1"
    assert hits[0].project_display == "alpha"
    assert "book" in (hits[0].snippet or "")


def test_catalog_redacts_secrets_and_keeps_handles_stable(tmp_path: Path) -> None:
    project, database, connection = _project_db(tmp_path / "work")
    catalog_path = tmp_path / "catalog.db"
    try:
        _insert_session(
            connection,
            project_key=project.key,
            source_id="codex:fixture:secret",
            adapter="codex",
            native_id="secret",
            handle="C1",
            title="Token note",
            search_text="API_KEY=supersecretvalue in the note",
        )
        catalog = open_catalog(catalog_path)
        try:
            sync_project(
                catalog,
                connection,
                project_key=project.key,
                project_display=project.display_name,
                database_path=database,
                synced_at=SYNCED_AT,
            )
            stored = catalog.execute(
                "SELECT search_text, catalog_handle FROM catalog_sessions"
            ).fetchone()
            assert stored["search_text"] == "API_KEY=[REDACTED:credential] in the note"
            assert stored["catalog_handle"] == "C1"
            connection.execute("DELETE FROM capsules WHERE source_id = 'codex:fixture:secret'")
            connection.execute("DELETE FROM sessions WHERE source_id = 'codex:fixture:secret'")
            assert sync_project(
                catalog,
                connection,
                project_key=project.key,
                project_display=project.display_name,
                database_path=database,
                synced_at=SYNCED_AT,
            ).removed == 1
            _insert_session(
                connection,
                project_key=project.key,
                source_id="codex:fixture:next",
                adapter="codex",
                native_id="next",
                handle="C1",
                title="Next note",
                search_text="a later session",
            )
            sync_project(
                catalog,
                connection,
                project_key=project.key,
                project_display=project.display_name,
                database_path=database,
                synced_at=SYNCED_AT,
            )
            handle = catalog.execute(
                "SELECT catalog_handle FROM catalog_sessions WHERE source_id = ?",
                ("codex:fixture:next",),
            ).fetchone()["catalog_handle"]
            assert handle == "C2"
            assert recall(catalog, "supersecretvalue") == ()
        finally:
            catalog.close()
    finally:
        connection.close()

    if os.name == "posix":
        assert catalog_path.stat().st_mode & 0o777 == 0o600


def test_recall_hides_unavailable_sessions_unless_asked(tmp_path: Path) -> None:
    project, database, connection = _project_db(tmp_path / "work")
    try:
        _insert_session(
            connection,
            project_key=project.key,
            source_id="cursor:fixture:gone",
            adapter="cursor",
            native_id="gone",
            handle="R1",
            title="Gone session",
            search_text="recover the missing transcript",
            native_available=0,
        )
        catalog = open_catalog(tmp_path / "catalog.db")
        try:
            sync_project(
                catalog,
                connection,
                project_key=project.key,
                project_display=project.display_name,
                database_path=database,
                synced_at=SYNCED_AT,
            )
            assert recall(catalog, "transcript") == ()
            found = recall(catalog, "transcript", include_unavailable=True)
            assert [hit.catalog_handle for hit in found] == ["R1"]
            assert found[0].native_available is False
        finally:
            catalog.close()
    finally:
        connection.close()


def test_sync_refuses_a_database_from_another_project(tmp_path: Path) -> None:
    project, database, connection = _project_db(tmp_path / "work")
    try:
        _insert_session(
            connection,
            project_key="directory:sha256:other",
            source_id="codex:fixture:other",
            adapter="codex",
            native_id="other",
            handle="C1",
            title="Other",
            search_text="other project",
        )
        catalog = open_catalog(tmp_path / "catalog.db")
        try:
            try:
                sync_project(
                    catalog,
                    connection,
                    project_key=project.key,
                    project_display=project.display_name,
                    database_path=database,
                    synced_at=SYNCED_AT,
                )
            except CatalogError as error:
                assert error.code == "project-mismatch"
            else:
                raise AssertionError("expected project-mismatch")
        finally:
            catalog.close()
    finally:
        connection.close()


def test_forget_project_removes_only_that_project(tmp_path: Path) -> None:
    alpha, alpha_db, alpha_conn = _project_db(tmp_path / "alpha")
    beta, beta_db, beta_conn = _project_db(tmp_path / "beta")
    catalog_path = tmp_path / "catalog.db"
    try:
        _insert_session(
            alpha_conn,
            project_key=alpha.key,
            source_id="codex:fixture:alpha",
            adapter="codex",
            native_id="alpha",
            handle="C1",
            title="Alpha",
            search_text="alpha lighthouse",
        )
        _insert_session(
            beta_conn,
            project_key=beta.key,
            source_id="grok:fixture:beta",
            adapter="grok",
            native_id="beta",
            handle="G1",
            title="Beta",
            search_text="beta lighthouse",
        )
        catalog = open_catalog(catalog_path)
        try:
            sync_project(
                catalog,
                alpha_conn,
                project_key=alpha.key,
                project_display=alpha.display_name,
                database_path=alpha_db,
                synced_at=SYNCED_AT,
            )
            sync_project(
                catalog,
                beta_conn,
                project_key=beta.key,
                project_display=beta.display_name,
                database_path=beta_db,
                synced_at=SYNCED_AT,
            )
        finally:
            catalog.close()
        assert forget_project(catalog_path, alpha.key) == 1
        assert forget_project(tmp_path / "missing.db", beta.key) == 0
        catalog = open_catalog(catalog_path)
        try:
            hits = recall(catalog, "lighthouse")
        finally:
            catalog.close()
    finally:
        alpha_conn.close()
        beta_conn.close()
    assert [hit.project_display for hit in hits] == ["beta"]


def test_cli_recall_is_global_and_does_not_create_a_missing_catalog(
    tmp_path: Path, capsys
) -> None:
    missing = tmp_path / "absent.db"
    assert main(["recall", "book", "--catalog", str(missing)]) == 2
    captured = capsys.readouterr()
    assert "catalog-missing" in captured.err
    assert not missing.exists()

    alpha = tmp_path / "alpha"
    beta = tmp_path / "beta"
    alpha.mkdir()
    beta.mkdir()
    alpha_project = resolve_project(alpha)
    beta_project = resolve_project(beta)
    alpha_db = open_database(project_data_path(alpha_project))
    beta_db = open_database(project_data_path(beta_project))
    try:
        _insert_session(
            alpha_db,
            project_key=alpha_project.key,
            source_id="codex:fixture:alpha",
            adapter="codex",
            native_id="alpha",
            handle="C1",
            title="Alpha notes",
            search_text="alpha only phrase",
        )
        _insert_session(
            beta_db,
            project_key=beta_project.key,
            source_id="grok:fixture:beta",
            adapter="grok",
            native_id="beta",
            handle="G1",
            title="Beta notes",
            search_text="beta zebra phrase",
        )
    finally:
        alpha_db.close()
        beta_db.close()

    catalog = tmp_path / "catalog.db"
    assert main(["catalog", "sync", "--cwd", str(alpha), "--catalog", str(catalog), "--json"]) == 0
    assert main(["catalog", "sync", "--cwd", str(beta), "--catalog", str(catalog), "--json"]) == 0
    capsys.readouterr()
    assert main(["recall", "zebra", "--catalog", str(catalog), "--json"]) == 0
    document = json.loads(capsys.readouterr().out)
    assert document["schema_version"] == 1
    assert document["result_count"] == 1
    assert document["results"][0]["catalog_handle"] == "G1"
    assert document["results"][0]["project_display"] == "beta"
    assert document["results"][0]["harness"] == "grok"
    assert "database_path" not in document["results"][0]
