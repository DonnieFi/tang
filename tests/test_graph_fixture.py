from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from tang.adapters import (
    OpaqueSourceLocator,
    SessionHealth,
    SessionIdentity,
    SourceFingerprint,
    SourceRecord,
)
from tang.continuation import ContinuationError, ContinuationService
from tang.repository import TangRepository
from tang.storage import open_database


FIXTURE = Path(__file__).parent / "fixtures" / "graph" / "multiverse.json"


def load() -> dict[str, object]:
    return json.loads(FIXTURE.read_text())


def test_canonical_fixture_is_stable_explicit_many_to_many() -> None:
    document = load()
    assert document["schema_version"] == 1
    assert document["active_source_id"] == "codex:multiverse:g"
    assert [node["native_id"] for node in document["nodes"]] == list("abcdefgh")
    assert [
        (edge["source_id"].rsplit(":", 1)[-1], edge["target_id"].rsplit(":", 1)[-1])
        for edge in document["edges"]
    ] == [("a", "c"), ("b", "c"), ("c", "d"), ("c", "e"), ("e", "g"), ("f", "g")]
    assert {edge["confirmation_mode"] for edge in document["edges"]} == {"explicit"}
    assert all(str(edge["confirmed_at"]).endswith("Z") for edge in document["edges"])
    unavailable = [node for node in document["nodes"] if not node["native_available"]]
    assert [node["native_id"] for node in unavailable] == ["f"]


def test_fixture_drives_dag_service_and_invalid_candidates(tmp_path: Path) -> None:
    document = load()
    connection = open_database(tmp_path / "tang.db")
    repository = TangRepository(connection)
    service = ContinuationService(repository)
    try:
        with repository.transaction():
            for node in document["nodes"]:
                identity = SessionIdentity(*node["source_id"].split(":", 2))
                timestamp = datetime.fromisoformat(node["timestamp"].replace("Z", "+00:00"))
                repository.upsert_session(
                    SourceRecord(
                        identity,
                        OpaqueSourceLocator(f"fixture:{node['native_id']}"),
                        SourceFingerprint("sha256", f"fixture-{node['native_id']}"),
                        "/fixture/tang",
                        timestamp,
                        timestamp,
                        SessionHealth(node["health"]),
                    ),
                    document["project_key"],
                    timestamp,
                )
        for edge in document["edges"]:
            service.link(
                (edge["source_id"],),
                edge["target_id"],
                document["project_key"],
                edge["confirmation_mode"],
                datetime.fromisoformat(edge["confirmed_at"].replace("Z", "+00:00")),
            )
        assert len(repository.continuations_for_project(document["project_key"])) == 6

        for candidate in document["invalid_candidates"]:
            with pytest.raises(ContinuationError) as failure:
                service.link(
                    (candidate["source_id"],),
                    candidate["target_id"],
                    document["project_key"],
                    "explicit",
                    datetime.fromisoformat("2026-07-14T20:40:00+00:00"),
                )
            assert failure.value.code == candidate["reason"]
    finally:
        connection.close()
