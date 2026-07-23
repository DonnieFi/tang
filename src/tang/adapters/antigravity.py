"""Read-only adapter for Antigravity CLI history and brain transcripts."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from tang.adapters.base import (
    AdapterCheckpoint,
    AdapterWarning,
    BatchStatus,
    OpaqueSourceLocator,
    ScanBatch,
    SessionHeader,
    SessionHealth,
    SessionIdentity,
    SourceFingerprint,
    SourceRecord,
    TurnBatch,
    TurnRole,
    TurnSelection,
    VisibleTurn,
)
from tang.adapters.incremental_checkpoint import decode_fingerprint_checkpoint

_USER_REQUEST = re.compile(
    r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", re.DOTALL
)
_TOOL_OUTPUT_PREFIX = "Created At:"


@dataclass(frozen=True, slots=True)
class _HistoryEntry:
    display: str | None
    started_at: datetime
    updated_at: datetime


class AntigravityAdapter:
    """Discover and reread Antigravity CLI sessions for one resolved project."""

    adapter_key = "antigravity"

    def __init__(
        self,
        project_dir: Path | str,
        *,
        antigravity_home: Path | None = None,
        source_namespace: str | None = None,
    ) -> None:
        self._project_dir = Path(project_dir).expanduser().resolve()
        configured = antigravity_home or _default_home()
        self._antigravity_home = configured.expanduser().resolve()
        self._history_path = self._antigravity_home / "history.jsonl"
        self._brain_root = self._antigravity_home / "brain"
        self.source_namespace = source_namespace or self._namespace_for(
            self._antigravity_home
        )
        SessionIdentity(self.adapter_key, self.source_namespace, "validation")

    @staticmethod
    def _namespace_for(antigravity_home: Path) -> str:
        digest = hashlib.sha256(os.fsencode(antigravity_home)).hexdigest()
        return f"store-{digest}"

    def has_project_sessions(self) -> bool:
        return bool(self._project_history())

    def _project_history(self) -> dict[str, _HistoryEntry]:
        if not self._history_path.is_file():
            return {}
        workspace = str(self._project_dir)
        entries: dict[str, _HistoryEntry] = {}
        try:
            lines = self._history_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return {}
        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            conversation_id = payload.get("conversationId")
            if not isinstance(conversation_id, str) or not conversation_id.strip():
                continue
            if payload.get("workspace") != workspace:
                continue
            timestamp = _epoch_millis(payload.get("timestamp"))
            if timestamp is None:
                continue
            display = payload.get("display")
            title = display.strip() if isinstance(display, str) and display.strip() else None
            previous = entries.get(conversation_id)
            if previous is None:
                entries[conversation_id] = _HistoryEntry(
                    title, timestamp, timestamp
                )
            else:
                entries[conversation_id] = _HistoryEntry(
                    title or previous.display,
                    min(previous.started_at, timestamp),
                    max(previous.updated_at, timestamp),
                )
        return entries

    def _transcript_path(self, conversation_id: str) -> Path:
        return (
            self._brain_root
            / conversation_id
            / ".system_generated"
            / "logs"
            / "transcript.jsonl"
        )

    def scan(self, checkpoint: AdapterCheckpoint | None) -> ScanBatch:
        history = self._project_history()
        if not history:
            return ScanBatch(
                status=BatchStatus.UNAVAILABLE,
                warnings=(
                    AdapterWarning(
                        "missing-store",
                        "No Antigravity sessions were found for this project.",
                    ),
                ),
            )

        warnings: list[AdapterWarning] = []
        previous, _validated = self._decode_checkpoint(checkpoint, warnings)
        current = dict(previous)
        records: list[SourceRecord] = []
        present: set[str] = set()

        for conversation_id in sorted(history):
            identity = SessionIdentity(
                self.adapter_key, self.source_namespace, conversation_id
            )
            canonical = identity.canonical
            present.add(canonical)
            transcript = self._transcript_path(conversation_id)
            if not transcript.is_file():
                warnings.append(
                    AdapterWarning(
                        "missing-transcript",
                        "An Antigravity history entry has no readable transcript and was skipped.",
                        identity,
                    )
                )
                continue
            try:
                fingerprint = _fingerprint_file(transcript)
                if current.get(canonical) == fingerprint.value:
                    continue
                entry = history[conversation_id]
                records.append(
                    SourceRecord(
                        identity=identity,
                        locator=OpaqueSourceLocator(str(transcript)),
                        fingerprint=fingerprint,
                        project_hint=str(self._project_dir),
                        started_at=entry.started_at,
                        updated_at=entry.updated_at,
                        title=entry.display,
                        health=SessionHealth.UNKNOWN,
                        header=SessionHeader(model_provider="google"),
                    )
                )
                current[canonical] = fingerprint.value
            except OSError:
                warnings.append(
                    AdapterWarning(
                        "session-checkpoint-retained",
                        "An Antigravity transcript could not be read; the prior checkpoint fingerprint was kept.",
                        identity,
                    )
                )
                continue

        removed = [
            SessionIdentity.from_canonical(key)
            for key in previous
            if key not in present
        ]
        for identity in removed:
            current.pop(identity.canonical, None)

        next_checkpoint = None
        if records or removed or current != previous:
            next_checkpoint = AdapterCheckpoint(
                self.adapter_key,
                self.source_namespace,
                json.dumps(
                    {"schema_version": 1, "fingerprints": current},
                    sort_keys=True,
                ),
            )

        status = BatchStatus.COMPLETE
        if warnings:
            status = BatchStatus.PARTIAL
        if not records and warnings:
            status = BatchStatus.UNAVAILABLE
        return ScanBatch(
            status=status,
            records=tuple(records),
            removed=tuple(removed),
            warnings=tuple(warnings),
            next_checkpoint=next_checkpoint,
        )

    def read(self, source: SourceRecord, selection: TurnSelection) -> TurnBatch:
        path = Path(source.locator.value)
        if not path.is_file():
            return TurnBatch(
                source.identity,
                BatchStatus.UNAVAILABLE,
                (),
                header=SessionHeader(),
                warnings=(
                    AdapterWarning(
                        "missing-transcript",
                        "The Antigravity transcript is unavailable.",
                        source.identity,
                    ),
                ),
            )

        turns: list[VisibleTurn] = []
        warnings: list[AdapterWarning] = []
        index = 0
        try:
            with path.open(encoding="utf-8") as handle:
                for line_no, raw_line in enumerate(handle, start=1):
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        warnings.append(
                            AdapterWarning(
                                "malformed-turn",
                                "An Antigravity transcript line could not be parsed.",
                                source.identity,
                            )
                        )
                        continue
                    role = _visible_role(payload)
                    if role is None:
                        continue
                    text = _visible_text(payload, role)
                    if not text.strip():
                        continue
                    index += 1
                    if not selection.includes(index):
                        continue
                    turns.append(
                        VisibleTurn(
                            ordinal=index,
                            role=role,
                            text=text,
                            citation_locator=f"line:{line_no}",
                            timestamp=_parse_timestamp(payload.get("created_at")),
                        )
                    )
        except OSError:
            return TurnBatch(
                source.identity,
                BatchStatus.UNAVAILABLE,
                (),
                header=SessionHeader(),
                warnings=(
                    AdapterWarning(
                        "unreadable-transcript",
                        "The Antigravity transcript could not be read.",
                        source.identity,
                    ),
                ),
            )

        if not turns:
            warnings.append(
                AdapterWarning(
                    "no-visible-turns",
                    "The Antigravity transcript had no readable user or agent text.",
                    source.identity,
                )
            )
        return TurnBatch(
            source.identity,
            BatchStatus.COMPLETE if turns else BatchStatus.UNAVAILABLE,
            tuple(turns),
            header=source.header,
            warnings=tuple(warnings),
        )

    def _decode_checkpoint(
        self,
        checkpoint: AdapterCheckpoint | None,
        warnings: list[AdapterWarning],
    ) -> tuple[dict[str, str], frozenset[str]]:
        return decode_fingerprint_checkpoint(
            checkpoint,
            adapter_key=self.adapter_key,
            source_namespace=self.source_namespace,
            allowed_schema_versions=frozenset({1}),
            legacy_rescan_versions=frozenset({1}),
            warnings=warnings,
        )


def _default_home() -> Path:
    configured = os.environ.get("ANTIGRAVITY_HOME")
    if configured:
        return Path(configured)
    cli_home = Path.home() / ".gemini" / "antigravity-cli"
    if cli_home.is_dir():
        return cli_home
    return Path.home() / ".gemini" / "antigravity"


def _fingerprint_file(path: Path) -> SourceFingerprint:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return SourceFingerprint("sha256", digest.hexdigest())


def _epoch_millis(value: object) -> datetime | None:
    if not isinstance(value, int):
        return None
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc)


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _visible_role(payload: dict[str, object]) -> TurnRole | None:
    source = payload.get("source")
    event_type = payload.get("type")
    if source == "USER_EXPLICIT" and event_type == "USER_INPUT":
        return TurnRole.USER
    if source == "MODEL" and event_type == "PLANNER_RESPONSE":
        return TurnRole.AGENT
    return None


def _visible_text(payload: dict[str, object], role: TurnRole) -> str:
    if role is TurnRole.USER:
        content = payload.get("content")
        if not isinstance(content, str):
            return ""
        match = _USER_REQUEST.search(content)
        if match is not None:
            return match.group(1).strip()
        return content.strip()
    content = payload.get("content")
    if isinstance(content, str) and content.strip():
        if content.lstrip().startswith(_TOOL_OUTPUT_PREFIX):
            return ""
        return content.strip()
    thinking = payload.get("thinking")
    if isinstance(thinking, str) and thinking.strip():
        return thinking.strip()
    return ""
