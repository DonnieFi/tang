"""Bounded, redacted Discovery Capsule construction."""

from __future__ import annotations

import json

from tang.adapters import SourceRecord, TurnBatch, TurnRole, VisibleTurn
from tang.redaction import (
    DEFAULT_REDACTOR,
    ContentKind,
    RedactionSeam,
    Redactor,
    required_redaction,
)
from tang.repository import StoredCapsule
from tang.timeutil import optional_rfc3339


CAPSULE_BYTE_LIMIT = 8_192
_MAX_TITLE_CHARACTERS = 256
_MAX_EXCERPT_CHARACTERS = 2_048
_MAX_RECENT_EXCERPTS = 4
_TRUNCATED = "…[Truncated]"


def _canonical(content: dict[str, object]) -> bytes:
    return json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _bounded(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    keep = max(1, limit - len(_TRUNCATED))
    return text[:keep].rstrip() + _TRUNCATED, True


class DiscoveryCapsuleBuilder:
    """Select permitted visible evidence and fit canonical JSON under 8 KiB."""

    def __init__(self, *, redactor: Redactor = DEFAULT_REDACTOR) -> None:
        self._redactor = redactor

    def build(
        self, source: SourceRecord, read: TurnBatch, project_key: str
    ) -> StoredCapsule:
        if source.identity != read.identity:
            raise ValueError("source and read identities must match")
        if not read.turns:
            raise ValueError("cannot build a capsule without visible turns")

        title_result = required_redaction(
            self._redactor,
            RedactionSeam.CAPSULE_PERSISTENCE,
            ContentKind.TITLE,
            source.title or "",
        )
        title, title_truncated = _bounded(
            title_result.text, _MAX_TITLE_CHARACTERS
        )

        selected_ordinals = self._selected_ordinals(read.turns)
        excerpts: list[dict[str, object]] = []
        redaction_count = title_result.redaction_count
        for turn in read.turns:
            if turn.ordinal not in selected_ordinals:
                continue
            excerpt, count = self._excerpt(turn)
            excerpts.append(excerpt)
            redaction_count += count

        content: dict[str, object] = {
            "capabilities": ["native-reread", "visible-user-agent-turns"],
            "excerpts": excerpts,
            "harness": source.identity.adapter,
            "health": source.health.value,
            "native_session_id": source.identity.native_id,
            "omitted_visible_turns": len(read.turns) - len(excerpts),
            "project_key": project_key,
            "redaction_count": redaction_count,
            "schema_version": 1,
            "source_id": source.identity.canonical,
            "source_title": title or None,
            "source_title_truncated": title_truncated,
            "updated_at": optional_rfc3339(source.updated_at),
        }
        self._fit(content)
        encoded = _canonical(content)
        search_parts = [title] if title else []
        search_parts.extend(str(excerpt["text"]) for excerpt in content["excerpts"])
        return StoredCapsule(
            source_id=source.identity.canonical,
            project_key=project_key,
            content=content,
            search_text="\n".join(search_parts),
            byte_count=len(encoded),
            updated_at=source.updated_at,
        )

    @staticmethod
    def _selected_ordinals(turns: tuple[VisibleTurn, ...]) -> frozenset[int]:
        first_user = next(
            (turn.ordinal for turn in turns if turn.role is TurnRole.USER), None
        )
        recent = [turn.ordinal for turn in turns[-_MAX_RECENT_EXCERPTS:]]
        if first_user is not None:
            recent.append(first_user)
        return frozenset(recent)

    def _excerpt(self, turn: VisibleTurn) -> tuple[dict[str, object], int]:
        text_result = required_redaction(
            self._redactor,
            RedactionSeam.CAPSULE_PERSISTENCE,
            ContentKind.VISIBLE_TEXT,
            turn.text,
        )
        citation_result = required_redaction(
            self._redactor,
            RedactionSeam.CAPSULE_PERSISTENCE,
            ContentKind.CITATION,
            turn.citation_locator,
        )
        text, truncated = _bounded(text_result.text, _MAX_EXCERPT_CHARACTERS)
        citation, citation_truncated = _bounded(citation_result.text, 256)
        return (
            {
                "citation": {
                    "timestamp": optional_rfc3339(turn.timestamp),
                    "turn_locator": citation,
                    "turn_locator_truncated": citation_truncated,
                },
                "ordinal": turn.ordinal,
                "role": turn.role.value,
                "text": text,
                "truncated": truncated,
            },
            text_result.redaction_count + citation_result.redaction_count,
        )

    @staticmethod
    def _fit(content: dict[str, object]) -> None:
        excerpts = content["excerpts"]
        if not isinstance(excerpts, list):
            raise TypeError("capsule excerpts must be a list")
        while len(_canonical(content)) > CAPSULE_BYTE_LIMIT and len(excerpts) > 2:
            excerpts.pop(1 if excerpts[0]["role"] == TurnRole.USER.value else 0)
            content["omitted_visible_turns"] = int(
                content["omitted_visible_turns"]
            ) + 1
        while len(_canonical(content)) > CAPSULE_BYTE_LIMIT:
            target = max(excerpts, key=lambda item: len(str(item["text"])))
            text = str(target["text"])
            if len(text) <= len(_TRUNCATED) + 1:
                raise ValueError("capsule metadata exceeds the 8 KiB budget")
            keep = max(1, len(text) // 2 - len(_TRUNCATED))
            target["text"] = text[:keep].rstrip() + _TRUNCATED
            target["truncated"] = True
