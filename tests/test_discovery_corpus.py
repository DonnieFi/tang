from __future__ import annotations

from tang.adapters import BatchStatus, CodexAdapter, GrokAdapter, TurnSelection


def test_combined_corpus_has_search_chronology_partial_and_isolation(
    discovery_corpus,
) -> None:
    codex = CodexAdapter(
        discovery_corpus.codex_home, source_namespace="discovery-codex"
    )
    grok = GrokAdapter(
        discovery_corpus.grok_home, source_namespace="discovery-grok"
    )

    codex_scan = codex.scan(None)
    grok_scan = grok.scan(None)

    assert codex_scan.status is BatchStatus.PARTIAL
    assert len(codex_scan.records) == 4
    assert grok_scan.status is BatchStatus.COMPLETE
    assert len(grok_scan.records) == 1
    assert {
        record.project_hint for record in (*codex_scan.records, *grok_scan.records)
    } == {"/work/tang-demo", "/work/foreign-vault"}

    reads = [codex.read(record, TurnSelection()) for record in codex_scan.records]
    all_text = "\n".join(turn.text for read in reads for turn in read.turns)
    assert "nebula-lantern" in all_text
    assert "checkpoint recovery" in all_text
    assert "foreign-quasar-secret" in all_text
    assert any(len(turn.text) == 3_000 for read in reads for turn in read.turns)
    assert any(read.status is BatchStatus.PARTIAL for read in reads)
    for read in reads:
        timestamps = [turn.timestamp for turn in read.turns]
        assert timestamps == sorted(timestamps)


def test_foreign_sentinel_is_distinct_from_current_project(discovery_corpus) -> None:
    adapter = CodexAdapter(
        discovery_corpus.codex_home, source_namespace="discovery-codex"
    )
    records = adapter.scan(None).records
    foreign = [record for record in records if record.project_hint == "/work/foreign-vault"]
    current = [record for record in records if record.project_hint == "/work/tang-demo"]

    assert len(foreign) == 1
    assert len(current) == 3
    foreign_read = adapter.read(foreign[0], TurnSelection())
    current_text = "\n".join(
        turn.text
        for record in current
        for turn in adapter.read(record, TurnSelection()).turns
    )
    assert "foreign-quasar-secret" in "\n".join(
        turn.text for turn in foreign_read.turns
    )
    assert "foreign-quasar-secret" not in current_text
