"""Read-only adapter for Claude Code project-scoped JSONL session logs."""

from __future__ import annotations

import hashlib
import json
import os
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

class ClaudeAdapter:
    """Discover and reread Claude Code sessions for one resolved project."""

    adapter_key = "claude"

    def __init__(
        self,
        project_dir: Path | str,
        *,
        claude_home: Path | None = None,
        source_namespace: str | None = None,
    ) -> None:
        self._project_dir = Path(project_dir).expanduser().resolve()
        configured = claude_home or Path(
            os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")
        )
        self._claude_home = configured.expanduser().resolve()
        self._projects_root = self._claude_home / "projects"
        self.source_namespace = source_namespace or self._namespace_for(
            self._claude_home
        )
        SessionIdentity(self.adapter_key, self.source_namespace, "validation")

    @staticmethod
    def _namespace_for(claude_home: Path) -> str:
        digest = hashlib.sha256(os.fsencode(claude_home)).hexdigest()
        return f"store-{digest}"

    @staticmethod
    def project_slug(project_dir: Path) -> str:
        text = str(project_dir.resolve()).lstrip("/")
        return f"-{text.replace('/', '-')}" if text else "-root"

    def has_project_sessions(self) -> bool:
        root = self._project_root()
        return root is not None and any(root.glob("*.jsonl"))

    def _project_root(self) -> Path | None:
        if not self._projects_root.is_dir():
            return None
        candidate = self._projects_root / self.project_slug(self._project_dir)
        return candidate if candidate.is_dir() else None

    def scan(self, checkpoint: AdapterCheckpoint | None) -> ScanBatch:
        root = self._project_root()
        if root is None or not any(root.glob("*.jsonl")):
            return ScanBatch(
                status=BatchStatus.UNAVAILABLE,
                warnings=(
                    AdapterWarning(
                        "missing-store",
                        "No Claude Code session logs were found for this project.",
                    ),
                ),
            )

        warnings: list[AdapterWarning] = []
        previous, _validated = self._decode_checkpoint(checkpoint, warnings)
        current = dict(previous)
        records: list[SourceRecord] = []
        present: set[str] = set()

        try:
            session_files = sorted(path for path in root.glob("*.jsonl") if path.is_file())
        except OSError:
            return ScanBatch(
                status=BatchStatus.UNAVAILABLE,
                warnings=(
                    AdapterWarning(
                        "unreadable-store",
                        "The Claude Code project directory could not be listed.",
                    ),
                ),
            )

        for session_file in session_files:
            native_id = session_file.stem
            identity = SessionIdentity(
                self.adapter_key, self.source_namespace, native_id
            )
            canonical = identity.canonical
            present.add(canonical)
            try:
                fingerprint = _fingerprint_file(session_file)
                if current.get(canonical) == fingerprint.value:
                    continue
                metadata = _scan_metadata(session_file, identity, warnings)
                fallback = datetime.fromtimestamp(
                    session_file.stat().st_mtime, tz=timezone.utc
                )
                records.append(
                    SourceRecord(
                        identity=identity,
                        locator=OpaqueSourceLocator(str(session_file)),
                        fingerprint=fingerprint,
                        project_hint=str(self._project_dir),
                        started_at=metadata.started_at or fallback,
                        updated_at=metadata.updated_at or fallback,
                        title=metadata.title,
                        health=SessionHealth.UNKNOWN,
                        header=metadata.header,
                    )
                )
                current[canonical] = fingerprint.value
            except OSError:
                warnings.append(
                    AdapterWarning(
                        "session-checkpoint-retained",
                        "A Claude session could not be read; the prior checkpoint fingerprint was kept.",
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

        return ScanBatch(
            status=BatchStatus.PARTIAL if warnings else BatchStatus.COMPLETE,
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
                        "The Claude session log is unavailable.",
                        source.identity,
                    ),
                ),
            )

        turns: list[VisibleTurn] = []
        warnings: list[AdapterWarning] = []
        observed_header = SessionHeader()
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
                                "A Claude session line could not be parsed.",
                                source.identity,
                            )
                        )
                        continue
                    observed_header = _merge_header(payload, observed_header)
                    role = payload.get("type")
                    if role not in {"user", "assistant"}:
                        continue
                    text = _visible_text(payload)
                    if not text.strip():
                        continue
                    index += 1
                    if not selection.includes(index):
                        continue
                    timestamp = _parse_timestamp(payload.get("timestamp"))
                    turns.append(
                        VisibleTurn(
                            ordinal=index,
                            role=TurnRole.USER if role == "user" else TurnRole.AGENT,
                            text=text,
                            citation_locator=f"line:{line_no}",
                            timestamp=timestamp,
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
                        "The Claude session log could not be read.",
                        source.identity,
                    ),
                ),
            )

        header = source.header.merged_with(observed_header)
        if not turns:
            warnings.append(
                AdapterWarning(
                    "no-visible-turns",
                    "The Claude session had no readable user or assistant text.",
                    source.identity,
                )
            )
        return TurnBatch(
            source.identity,
            BatchStatus.COMPLETE if turns else BatchStatus.UNAVAILABLE,
            tuple(turns),
            header=header,
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


def _fingerprint_file(path: Path) -> SourceFingerprint:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return SourceFingerprint("sha256", digest.hexdigest())


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


def _scan_metadata(
    path: Path,
    identity: SessionIdentity,
    warnings: list[AdapterWarning],
) -> _ScanMetadata:
    title: str | None = None
    started_at: datetime | None = None
    updated_at: datetime | None = None
    header = SessionHeader()
    try:
        with path.open(encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if payload.get("type") == "ai-title":
                    raw_title = payload.get("aiTitle")
                    if isinstance(raw_title, str) and raw_title.strip():
                        title = raw_title.strip()
                timestamp = _parse_timestamp(payload.get("timestamp"))
                if timestamp is not None:
                    started_at = timestamp if started_at is None else min(started_at, timestamp)
                    updated_at = timestamp if updated_at is None else max(updated_at, timestamp)
                header = _merge_header(payload, header)
    except OSError:
        warnings.append(
            AdapterWarning(
                "claude-metadata-drift",
                "Claude session metadata could not be scanned.",
                identity,
            )
        )
    return _ScanMetadata(title, started_at, updated_at, header)


class _ScanMetadata:
    __slots__ = ("title", "started_at", "updated_at", "header")

    def __init__(
        self,
        title: str | None,
        started_at: datetime | None,
        updated_at: datetime | None,
        header: SessionHeader,
    ) -> None:
        self.title = title
        self.started_at = started_at
        self.updated_at = updated_at
        self.header = header


def _merge_header(payload: dict[str, object], header: SessionHeader) -> SessionHeader:
    message = payload.get("message")
    model_id = header.model_id
    if isinstance(message, dict):
        model = message.get("model")
        if isinstance(model, str):
            model_id = model
    return SessionHeader(
        model_provider=header.model_provider or "anthropic",
        model_id=model_id,
        effort=header.effort,
    )


def _visible_text(payload: dict[str, object]) -> str:
    message = payload.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text)
    return "\n".join(parts)
