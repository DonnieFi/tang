from __future__ import annotations

import json
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

import pytest

from tang.adapters import (
    BatchStatus,
    OpaqueSourceLocator,
    SessionIdentity,
    SourceFingerprint,
    SourceRecord,
    TurnBatch,
    TurnRole,
    VisibleTurn,
)
from tang.context import Citation, ContextExcerpt
from tang.multicontext import MultiSourceAllocator, ValidatedSourceRead


NOW = datetime(2026, 7, 15, 0, 0, tzinfo=timezone.utc)


def _validated_with_first_user(index: int, first_user: str) -> ValidatedSourceRead:
    identity = SessionIdentity("codex", "fixture", f"source-{index}")
    source = SourceRecord(
        identity=identity,
        locator=OpaqueSourceLocator(f"private/source-{index}.jsonl"),
        fingerprint=SourceFingerprint("sha256", f"digest-{index}"),
        project_hint="/synthetic/project",
        started_at=NOW,
        updated_at=NOW + timedelta(minutes=index),
    )
    turns = (
        VisibleTurn(
            0,
            TurnRole.USER,
            first_user,
            "jsonl:1",
            NOW,
        ),
        VisibleTurn(
            1,
            TurnRole.AGENT,
            "ack",
            "jsonl:2",
            NOW,
        ),
    )
    return ValidatedSourceRead(
        source,
        TurnBatch(identity, BatchStatus.COMPLETE, turns),
        "project-a",
    )


def test_conflicting_first_user_goals_emit_constraint_signals() -> None:
    pack = MultiSourceAllocator().allocate(
        (
            _validated_with_first_user(0, "Use Redis for the cache boundary"),
            _validated_with_first_user(1, "Use SQLite for the cache boundary"),
        ),
        "project-a",
    )
    document = json.loads(pack.to_json())
    assert document["constraint_signals"][0]["kind"] == "first_user_goal_mismatch"
    assert len(document["untrusted_data_envelope"]["sources"]) == 2
    assert all(section["excerpts"] for section in document["untrusted_data_envelope"]["sources"])
    assert any("disagree" in warning for warning in document["warnings"])


def test_conflict_only_warning_keeps_pack_status_complete() -> None:
    pack = MultiSourceAllocator().allocate(
        (
            _validated_with_first_user(0, "Use Redis for the cache boundary"),
            _validated_with_first_user(1, "Use SQLite for the cache boundary"),
        ),
        "project-a",
    )
    assert pack.constraint_signals
    assert pack.status == "complete"


def test_normalize_goal_strips_host_envelope_before_compare() -> None:
    from tang.multicontext import _normalize_goal

    a = _normalize_goal(
        "<timestamp>Mon</timestamp>\n<user_query>\nFix the bug\n</user_query>"
    )
    b = _normalize_goal("Fix the bug")
    assert a == b


def validated(index: int, project_key: str = "project-a") -> ValidatedSourceRead:
    identity = SessionIdentity("codex", "fixture", f"source-{index}")
    source = SourceRecord(
        identity=identity,
        locator=OpaqueSourceLocator(f"private/source-{index}.jsonl"),
        fingerprint=SourceFingerprint("sha256", f"digest-{index}"),
        project_hint="/synthetic/project",
        started_at=NOW,
        updated_at=NOW + timedelta(minutes=index),
    )
    turns = tuple(
        VisibleTurn(
            ordinal=ordinal,
            role=TurnRole.USER if ordinal % 2 == 0 else TurnRole.AGENT,
            text=(
                "Implement the shared cache boundary"
                if ordinal == 0
                else f"source-{index}-turn-{ordinal} " + "x" * 500
            ),
            citation_locator=f"jsonl:{ordinal + 1}",
            timestamp=NOW + timedelta(minutes=index, seconds=ordinal),
        )
        for ordinal in range(12)
    )
    return ValidatedSourceRead(
        source,
        TurnBatch(identity, BatchStatus.COMPLETE, turns),
        project_key,
    )


def test_allocation_is_fair_chronological_cited_and_under_both_budgets() -> None:
    inputs = (validated(2), validated(0), validated(1))
    allocator = MultiSourceAllocator(token_budget=2_000)

    first = allocator.allocate(inputs, "project-a")
    second = allocator.allocate(inputs, "project-a")

    assert first == second
    assert first.markdown_estimated_tokens == (len(first.to_markdown()) + 3) // 4
    assert first.json_estimated_tokens == (len(first.to_json()) + 3) // 4
    assert first.estimated_tokens <= 2_000
    assert [section.source_id for section in first.sections] == sorted(
        section.source_id for section in first.sections
    )
    assert all(section.excerpts for section in first.sections)
    assert all(section.omitted_turns > 0 for section in first.sections)
    for section in first.sections:
        ordinals = [excerpt.ordinal for excerpt in section.excerpts]
        assert ordinals == sorted(ordinals)
        assert ordinals[-1] == 11
        assert all(excerpt.citation.turn_locator for excerpt in section.excerpts)
    document = json.loads(first.to_json())
    assert document["schema_version"] == 1
    assert len(document["untrusted_data_envelope"]["sources"]) == 3


def test_tight_budget_truncates_reserves_but_keeps_every_source() -> None:
    pack = MultiSourceAllocator(token_budget=600).allocate(
        (validated(0), validated(1)), "project-a"
    )

    assert pack.estimated_tokens <= 600
    assert all(len(section.excerpts) >= 1 for section in pack.sections)
    assert all(section.excerpts[-1].ordinal == 11 for section in pack.sections)
    assert all(section.excerpts[-1].truncated for section in pack.sections)


def test_allocator_rejects_unvalidated_project_mix_and_duplicates() -> None:
    first = validated(0)
    foreign = validated(1, "project-b")

    with pytest.raises(ValueError, match="active project"):
        MultiSourceAllocator().allocate((first, foreign), "project-a")
    with pytest.raises(ValueError, match="duplicate"):
        MultiSourceAllocator().allocate((first, first), "project-a")


def test_oversize_excerpt_does_not_hide_older_smaller_turn() -> None:
    item = validated(0)
    excerpts = tuple(
        ContextExcerpt(
            ordinal=ordinal,
            role="user",
            citation=Citation("codex", "source-0", f"jsonl:{ordinal + 1}", NOW),
            text=text,
            truncated=False,
        )
        for ordinal, text in (
            (0, "older useful turn"),
            (1, "x" * 1_200),
            (2, "newest reserve"),
        )
    )
    item = ValidatedSourceRead(
        item.source,
        TurnBatch(item.source.identity, BatchStatus.COMPLETE, item.read.turns[:3]),
        item.project_key,
    )
    allocator = MultiSourceAllocator(token_budget=512)
    allocator._single = SimpleNamespace(
        build=lambda source, read: SimpleNamespace(
            excerpts=excerpts,
            source_title=None,
            warnings=(),
            redaction_count=0,
        )
    )

    pack = allocator.allocate((item,), "project-a")

    assert [excerpt.ordinal for excerpt in pack.sections[0].excerpts] == [0, 2]
