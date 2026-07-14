from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tang.adapters import (
    AdapterCheckpoint,
    AdapterWarning,
    BatchStatus,
    OpaqueSourceLocator,
    ScanBatch,
    SessionAdapter,
    SessionIdentity,
    SourceFingerprint,
    SourceRecord,
    TurnBatch,
    TurnRole,
    TurnSelection,
    VisibleTurn,
)


NOW = datetime(2026, 7, 14, 20, 0, tzinfo=timezone.utc)


def source(native_id: str, *, namespace: str = "profile-a") -> SourceRecord:
    return SourceRecord(
        identity=SessionIdentity("grok", namespace, native_id),
        locator=OpaqueSourceLocator(f"sensitive/{native_id}"),
        fingerprint=SourceFingerprint("sha256", f"digest-{native_id}"),
        project_hint="/private/project",
        started_at=NOW,
        updated_at=NOW + timedelta(minutes=1),
        title="private title",
    )


def warning(code: str, identity: SessionIdentity | None = None) -> AdapterWarning:
    return AdapterWarning(code, f"private details for {code}", identity)


def turn(ordinal: int, role: TurnRole = TurnRole.USER) -> VisibleTurn:
    return VisibleTurn(
        ordinal=ordinal,
        role=role,
        text=f"private turn {ordinal}",
        citation_locator=f"update:{ordinal}",
        timestamp=NOW + timedelta(seconds=ordinal),
    )


def test_identity_is_canonical_and_namespace_prevents_collision() -> None:
    first = SessionIdentity("grok", "profile-a", "native-1")
    second = SessionIdentity("grok", "profile-b", "native-1")

    assert first.canonical == "grok:profile-a:native-1"
    assert first != second
    assert len({first, second}) == 2


@pytest.mark.parametrize(
    "value",
    ["", " leading", "trailing ", "has:colon", "line\nbreak", "tab\tvalue"],
)
def test_identity_rejects_ambiguous_segments(value: str) -> None:
    with pytest.raises(ValueError):
        SessionIdentity("grok", "profile", value)


def test_scan_batch_orders_records_and_warnings_deterministically() -> None:
    later = source("z-session")
    earlier = source("a-session")

    batch = ScanBatch(
        status=BatchStatus.PARTIAL,
        records=(later, earlier),
        next_checkpoint=AdapterCheckpoint("grok", "profile-a", "opaque cursor"),
        warnings=(warning("z-code"), warning("a-code", later.identity)),
    )

    assert [record.identity.native_id for record in batch.records] == [
        "a-session",
        "z-session",
    ]
    assert [item.code for item in batch.warnings] == ["a-code", "z-code"]


def test_partial_and_unavailable_results_are_typed_and_explained() -> None:
    identity = SessionIdentity("grok", "profile-a", "native-1")
    partial = TurnBatch(
        identity=identity,
        status=BatchStatus.PARTIAL,
        turns=(turn(0),),
        warnings=(warning("truncated", identity),),
    )
    unavailable = TurnBatch(
        identity=identity,
        status=BatchStatus.UNAVAILABLE,
        warnings=(warning("missing-source", identity),),
    )

    assert partial.status is BatchStatus.PARTIAL
    assert len(partial.turns) == 1
    assert unavailable.status is BatchStatus.UNAVAILABLE
    assert unavailable.turns == ()


def test_degraded_results_require_warnings() -> None:
    identity = SessionIdentity("grok", "profile-a", "native-1")

    with pytest.raises(ValueError, match="require at least one warning"):
        TurnBatch(identity=identity, status=BatchStatus.PARTIAL)


def test_result_status_requires_the_typed_enum() -> None:
    identity = SessionIdentity("grok", "profile-a", "native-1")

    with pytest.raises(TypeError, match="BatchStatus"):
        TurnBatch(identity=identity, status="complete")  # type: ignore[arg-type]


def test_unavailable_results_reject_usable_items() -> None:
    identity = SessionIdentity("grok", "profile-a", "native-1")

    with pytest.raises(ValueError, match="cannot contain usable items"):
        TurnBatch(
            identity=identity,
            status=BatchStatus.UNAVAILABLE,
            turns=(turn(0),),
            warnings=(warning("missing-source", identity),),
        )


def test_turn_batch_preserves_chronology_by_native_ordinal() -> None:
    identity = SessionIdentity("grok", "profile-a", "native-1")
    batch = TurnBatch(
        identity=identity,
        status=BatchStatus.COMPLETE,
        turns=(turn(2, TurnRole.AGENT), turn(0), turn(1, TurnRole.AGENT)),
    )

    assert [item.ordinal for item in batch.turns] == [0, 1, 2]


def test_turn_selection_is_half_open() -> None:
    selection = TurnSelection(start_at=2, stop_before=5)

    assert not selection.includes(1)
    assert selection.includes(2)
    assert selection.includes(4)
    assert not selection.includes(5)


def test_sensitive_values_are_not_exposed_by_repr() -> None:
    record = source("native-1")
    visible_turn = turn(0)

    assert "sensitive/native-1" not in repr(record)
    assert "/private/project" not in repr(record)
    assert "private title" not in repr(record)
    assert "private turn 0" not in repr(visible_turn)


def test_timestamps_are_normalized_to_utc_and_naive_values_fail() -> None:
    offset = timezone(timedelta(hours=-4))
    record = SourceRecord(
        identity=SessionIdentity("grok", "profile-a", "native-1"),
        locator=OpaqueSourceLocator("opaque"),
        fingerprint=SourceFingerprint("sha256", "digest"),
        project_hint="project",
        started_at=datetime(2026, 7, 14, 16, 0, tzinfo=offset),
        updated_at=datetime(2026, 7, 14, 16, 1, tzinfo=offset),
    )

    assert record.started_at == NOW
    assert record.started_at.tzinfo is timezone.utc
    with pytest.raises(ValueError, match="timezone-aware"):
        turn(0).__class__(
            ordinal=1,
            role=TurnRole.USER,
            text="text",
            citation_locator="update:1",
            timestamp=datetime(2026, 7, 14, 20, 0),
        )


def test_adapter_protocol_has_only_scan_and_read_behavior() -> None:
    class FakeAdapter:
        adapter_key = "fake"
        source_namespace = "fixture"

        def scan(self, checkpoint: AdapterCheckpoint | None) -> ScanBatch:
            return ScanBatch(status=BatchStatus.COMPLETE)

        def read(
            self, session_ref: SourceRecord, selection: TurnSelection
        ) -> TurnBatch:
            return TurnBatch(
                identity=session_ref.identity,
                status=BatchStatus.COMPLETE,
            )

    assert isinstance(FakeAdapter(), SessionAdapter)
