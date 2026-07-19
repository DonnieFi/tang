"""Bounded, redacted Discovery Capsule construction."""

from __future__ import annotations

import json

from tang.adapters import SourceRecord, TurnBatch, TurnRole, VisibleTurn
from tang.redaction import (
    DEFAULT_REDACTOR,
    ContentKind,
    RedactionSeam,
    Redactor,
    TITLE_CHARACTER_LIMIT,
    conceal_native_session_ids,
    required_redaction,
)
from tang.repository import StoredCapsule
from tang.timeutil import optional_rfc3339


CAPSULE_BYTE_LIMIT = 8_192
_MAX_DISPLAY_NAME_CHARACTERS = 96
_MAX_EXCERPT_CHARACTERS = 2_048
_MAX_RECENT_EXCERPTS = 4
_TRUNCATED = "…[Truncated]"
_DISPLAY_NAME_VERSION = 2
_SESSION_HEADER_VERSION = 1

# These are host-provided envelopes that Codex records as visible ``user``
# messages before a developer's actual request. They are useful to the host,
# but are neither a session title nor recoverable user intent. Keep this list
# deliberately narrow: ordinary Markdown, XML, and instruction text remain
# evidence unless they use one of the exact host wrapper prefixes.
_HOST_ENVELOPE_PREFIXES = (
    "# agents.md instructions for ",
    "<environment_context>",
    "<permissions instructions>",
    "<skills_instructions>",
    "<apps_instructions>",
    "<plugins_instructions>",
    "<recommended_plugins>",
)


def _canonical(content: dict[str, object]) -> bytes:
    return json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _bounded(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    keep = max(1, limit - len(_TRUNCATED))
    return text[:keep].rstrip() + _TRUNCATED, True


def _is_host_envelope(text: str) -> bool:
    """Recognize only documented host wrappers, never arbitrary user prose."""

    return text.lstrip().casefold().startswith(_HOST_ENVELOPE_PREFIXES)


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
            title_result.text, TITLE_CHARACTER_LIMIT
        )
        session_header, header_redaction_count = self._session_header(source, read)

        selected_ordinals = self._selected_ordinals(read.turns)
        excerpts: list[dict[str, object]] = []
        redaction_count = title_result.redaction_count + header_redaction_count
        for turn in read.turns:
            if turn.ordinal not in selected_ordinals:
                continue
            excerpt, count = self._excerpt(turn)
            excerpts.append(excerpt)
            redaction_count += count

        display_name, display_name_truncated, title_origin = self._display_name(
            source, title, excerpts
        )

        content: dict[str, object] = {
            "capabilities": ["native-reread", "visible-user-agent-turns"],
            "display_name": display_name,
            "display_name_truncated": display_name_truncated,
            "display_name_version": _DISPLAY_NAME_VERSION,
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
            "session_header": {
                **session_header,
                "title_origin": title_origin,
                "version": _SESSION_HEADER_VERSION,
                "visible_text_bytes": sum(
                    len(turn.text.encode("utf-8")) for turn in read.turns
                ),
                "visible_turn_count": len(read.turns),
            },
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
    def needs_label_refresh(capsule: StoredCapsule | None) -> bool:
        """Return whether a prior Capsule predates current derived metadata."""

        return (
            capsule is None
            or capsule.content.get("display_name_version")
            != _DISPLAY_NAME_VERSION
            or not isinstance(capsule.content.get("session_header"), dict)
            or capsule.content["session_header"].get("version")
            != _SESSION_HEADER_VERSION
        )

    def _session_header(
        self, source: SourceRecord, read: TurnBatch
    ) -> tuple[dict[str, str | None], int]:
        values: dict[str, str | None] = {}
        redaction_count = 0
        for key, value in (
            ("model_provider", source.header.model_provider),
            ("model_id", source.header.model_id),
            ("effort", source.header.effort),
        ):
            if value is None:
                values[key] = None
                continue
            result = required_redaction(
                self._redactor,
                RedactionSeam.CAPSULE_PERSISTENCE,
                ContentKind.DISPLAY_METADATA,
                value,
            )
            values[key] = result.text or None
            redaction_count += result.redaction_count
        return values, redaction_count

    @staticmethod
    def _display_name(
        source: SourceRecord, title: str, excerpts: list[dict[str, object]]
    ) -> tuple[str, bool, str]:
        """Build a compact recognizable label from already permitted evidence."""

        candidate = title
        title_origin = "native" if candidate else "derived_goal"
        if not candidate:
            candidate = next(
                (
                    str(excerpt["text"])
                    for excerpt in excerpts
                    if (
                        excerpt["role"] == TurnRole.USER.value
                        and not _is_host_envelope(str(excerpt["text"]))
                    )
                ),
                "",
            )
        if candidate:
            normalized = " ".join(candidate.split())
            if normalized:
                return _bounded(
                    conceal_native_session_ids(normalized),
                    _MAX_DISPLAY_NAME_CHARACTERS,
                ) + (title_origin,)
        return (
            f"{source.identity.adapter.title()} session · no user task captured",
            False,
            "no_user_task",
        )

    @staticmethod
    def _selected_ordinals(turns: tuple[VisibleTurn, ...]) -> frozenset[int]:
        first_user = next(
            (
                turn.ordinal
                for turn in turns
                if turn.role is TurnRole.USER and not _is_host_envelope(turn.text)
            ),
            None,
        )
        recent = [
            turn.ordinal
            for turn in turns[-_MAX_RECENT_EXCERPTS:]
            if not _is_host_envelope(turn.text)
        ]
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
