"""Read-only adapter for Cursor agent transcript JSONL files."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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


class CursorAdapter:
    """Discover and reread Cursor agent transcripts for one resolved project."""

    adapter_key = "cursor"

    def __init__(
        self,
        project_dir: Path | str,
        *,
        cursor_home: Path | None = None,
        source_namespace: str | None = None,
    ) -> None:
        self._project_dir = Path(project_dir).expanduser().resolve()
        configured = cursor_home or Path(
            os.environ.get("CURSOR_HOME", Path.home() / ".cursor")
        )
        self._cursor_home = configured.expanduser().resolve()
        self._projects_root = self._cursor_home / "projects"
        self.source_namespace = source_namespace or self._namespace_for(
            self._cursor_home
        )
        SessionIdentity(self.adapter_key, self.source_namespace, "validation")

    @staticmethod
    def _namespace_for(cursor_home: Path) -> str:
        digest = hashlib.sha256(os.fsencode(cursor_home)).hexdigest()
        return f"store-{digest}"

    @staticmethod
    def _project_slug(project_dir: Path) -> str:
        text = str(project_dir).strip("/")
        return text.replace("/", "-") or "root"

    def _transcript_root(self) -> Path | None:
        if not self._projects_root.is_dir():
            return None
        slug = self._project_slug(self._project_dir)
        candidate = self._projects_root / slug / "agent-transcripts"
        return candidate if candidate.is_dir() else None

    def scan(self, checkpoint: AdapterCheckpoint | None) -> ScanBatch:
        root = self._transcript_root()
        if root is None:
            return ScanBatch(
                status=BatchStatus.UNAVAILABLE,
                warnings=(
                    AdapterWarning(
                        "missing-store",
                        "No Cursor agent transcripts were found for this project.",
                    ),
                ),
            )

        warnings: list[AdapterWarning] = []
        previous, validated = self._decode_checkpoint(checkpoint, warnings)
        current = dict(previous)
        records: list[SourceRecord] = []
        removed: list[SessionIdentity] = []

        for session_dir in sorted(root.iterdir()):
            if not session_dir.is_dir():
                continue
            jsonl = session_dir / f"{session_dir.name}.jsonl"
            if not jsonl.is_file():
                continue
            native_id = session_dir.name
            identity = SessionIdentity(
                self.adapter_key, self.source_namespace, native_id
            )
            fingerprint = self._fingerprint(jsonl)
            canonical = identity.canonical
            if current.get(canonical) == fingerprint.value:
                continue
            mtime = datetime.fromtimestamp(jsonl.stat().st_mtime, tz=timezone.utc)
            records.append(
                SourceRecord(
                    identity=identity,
                    locator=OpaqueSourceLocator(str(jsonl)),
                    fingerprint=fingerprint,
                    project_hint=str(self._project_dir),
                    started_at=mtime,
                    updated_at=mtime,
                    health=SessionHealth.UNKNOWN,
                )
            )
            current[canonical] = fingerprint.value

        seen = {record.identity.canonical for record in records}
        for key in previous:
            if key not in seen and key not in current:
                removed.append(SessionIdentity.from_canonical(key))

        next_checkpoint = None
        if records or current != previous:
            next_checkpoint = AdapterCheckpoint(
                self.adapter_key,
                self.source_namespace,
                json.dumps(
                    {
                        "schema_version": 1,
                        "fingerprints": current,
                    },
                    sort_keys=True,
                ),
            )

        return ScanBatch(
            status=BatchStatus.COMPLETE,
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
                        "The Cursor transcript file is unavailable.",
                        source.identity,
                    ),
                ),
            )
        turns: list[VisibleTurn] = []
        warnings: list[AdapterWarning] = []
        index = 0
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    warnings.append(
                        AdapterWarning(
                            "malformed-turn",
                            "A Cursor transcript line could not be parsed.",
                            source.identity,
                        )
                    )
                    continue
                role = payload.get("role")
                if role not in {"user", "assistant"}:
                    continue
                text = _visible_text(payload)
                if not text.strip():
                    continue
                index += 1
                turns.append(
                    VisibleTurn(
                        ordinal=index,
                        role=TurnRole.USER if role == "user" else TurnRole.AGENT,
                        text=text,
                        citation_locator=f"line:{index}",
                    )
                )
        if not turns:
            warnings.append(
                AdapterWarning(
                    "no-visible-turns",
                    "The Cursor transcript had no readable user or assistant text.",
                    source.identity,
                )
            )
        return TurnBatch(
            source.identity,
            BatchStatus.COMPLETE if turns else BatchStatus.UNAVAILABLE,
            tuple(turns),
            header=SessionHeader(),
            warnings=tuple(warnings),
        )

    @staticmethod
    def _fingerprint(path: Path) -> SourceFingerprint:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return SourceFingerprint("sha256", digest.hexdigest())

    def _decode_checkpoint(
        self,
        checkpoint: AdapterCheckpoint | None,
        warnings: list[AdapterWarning],
    ) -> tuple[dict[str, str], frozenset[str]]:
        if checkpoint is None:
            return {}, frozenset()
        if (
            checkpoint.adapter != self.adapter_key
            or checkpoint.source_namespace != self.source_namespace
        ):
            warnings.append(
                AdapterWarning(
                    "checkpoint-scope",
                    "The checkpoint belongs to another adapter namespace; a full scan ran.",
                )
            )
            return {}, frozenset()
        try:
            payload = json.loads(checkpoint.cursor)
            fingerprints = payload["fingerprints"]
            if not isinstance(fingerprints, dict):
                raise ValueError
            return {
                str(key): str(value)
                for key, value in fingerprints.items()
                if isinstance(key, str) and isinstance(value, str)
            }, frozenset()
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            warnings.append(
                AdapterWarning(
                    "checkpoint-invalid",
                    "The Cursor checkpoint was invalid; a full scan ran.",
                )
            )
            return {}, frozenset()


def _visible_text(payload: dict[str, Any]) -> str:
    message = payload.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "text":
            continue
        text = block.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text)
    return "\n".join(parts)
