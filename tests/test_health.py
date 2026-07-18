from __future__ import annotations

import json
from pathlib import Path

from tang.adapters import CodexAdapter, SessionHealth
from tang.health import describe_health, health_label, health_style


def only_log(home: Path) -> Path:
    return next((home / "sessions").rglob("*.jsonl"))


def test_ambiguous_active_task_defaults_to_unknown(codex_fixture_home: Path) -> None:
    record = CodexAdapter(
        codex_fixture_home, source_namespace="health-fixture"
    ).scan(None).records[0]

    assert record.health is SessionHealth.UNKNOWN
    assert describe_health(record.health) == (
        "Unverified; native evidence is insufficient"
    )


def test_last_observed_task_complete_supports_qualified_complete(
    copied_codex_home: Path,
) -> None:
    log = only_log(copied_codex_home)
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    complete_index = next(
        index
        for index, row in enumerate(rows)
        if row["type"] == "event_msg"
        and row["payload"].get("type") == "task_complete"
    )
    log.write_text(
        "\n".join(json.dumps(row) for row in rows[: complete_index + 1]) + "\n"
    )

    record = CodexAdapter(
        copied_codex_home, source_namespace="health-fixture"
    ).scan(None).records[0]

    assert record.health is SessionHealth.COMPLETE
    assert describe_health(record.health) == "Last observed native task completed"


def test_missing_lifecycle_evidence_remains_unknown(copied_codex_home: Path) -> None:
    log = only_log(copied_codex_home)
    rows = [
        row
        for row in (json.loads(line) for line in log.read_text().splitlines())
        if row["type"] != "event_msg"
        or row["payload"].get("type") not in {"task_started", "task_complete"}
    ]
    log.write_text("\n".join(json.dumps(row) for row in rows) + "\n")

    record = CodexAdapter(
        copied_codex_home, source_namespace="health-fixture"
    ).scan(None).records[0]

    assert record.health is SessionHealth.UNKNOWN


def test_every_health_label_is_qualified_and_non_automatic() -> None:
    labels = {health: describe_health(health) for health in SessionHealth}

    assert set(labels) == set(SessionHealth)
    assert "Possibly" in labels[SessionHealth.POSSIBLY_INTERRUPTED]
    assert "unverified" in labels[SessionHealth.UNKNOWN].lower()
    assert all("continue" not in label.lower() for label in labels.values())


def test_health_styles_are_semantic_without_replacing_labels() -> None:
    assert health_style(SessionHealth.COMPLETE) == "bold #2aa198"
    assert health_style(SessionHealth.POSSIBLY_INTERRUPTED) == "bold red"
    assert health_style(SessionHealth.UNKNOWN) == "bold #ff9d3d"


def test_health_labels_clarify_uncertainty_without_changing_native_enums() -> None:
    assert health_label(SessionHealth.COMPLETE) == "complete"
    assert health_label(SessionHealth.POSSIBLY_INTERRUPTED) == "possibly interrupted"
    assert health_label(SessionHealth.UNKNOWN) == "unverified"
    assert SessionHealth.UNKNOWN.value == "unknown"
