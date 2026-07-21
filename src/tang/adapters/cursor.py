"""Read-only adapter for Cursor agent transcript JSONL files."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tang.cursor_sidecar import epoch_millis, read_store_session_meta
from tang.adapters.incremental_checkpoint import decode_fingerprint_checkpoint

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

_TASK_TOOL_NAMES = frozenset({"Task"})


@dataclass(frozen=True, slots=True)
class _SidecarMetadata:
    title: str | None = None
    started_at: datetime | None = None
    updated_at: datetime | None = None
    header: SessionHeader = SessionHeader()


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
        self._chats_root = self._cursor_home / "chats"
        self._workspace_chat_hash = self.workspace_chat_hash(self._project_dir)
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

    @staticmethod
    def workspace_chat_hash(project_dir: Path) -> str:
        """MD5 of the resolved absolute project path (Cursor chats layout)."""

        return hashlib.md5(str(project_dir.resolve()).encode()).hexdigest()

    def has_project_transcripts(self) -> bool:
        """True when this project has a Cursor agent-transcripts directory."""

        return self._transcript_root() is not None

    def _transcript_root(self) -> Path | None:
        if not self._projects_root.is_dir():
            return None
        slug = self._project_slug(self._project_dir)
        candidate = self._projects_root / slug / "agent-transcripts"
        return candidate if candidate.is_dir() else None

    def _chat_session_dir(self, native_id: str) -> Path | None:
        if not self._chats_root.is_dir():
            return None
        workspace = self._workspace_chat_hash
        candidate = self._chats_root / workspace / native_id
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
        previous, _validated = self._decode_checkpoint(checkpoint, warnings)
        current = dict(previous)
        records: list[SourceRecord] = []
        present: set[str] = set()

        try:
            session_dirs = sorted(root.iterdir())
        except OSError:
            return ScanBatch(
                status=BatchStatus.UNAVAILABLE,
                warnings=(
                    AdapterWarning(
                        "unreadable-store",
                        "The Cursor agent-transcripts directory could not be listed.",
                    ),
                ),
            )

        for session_dir in session_dirs:
            identity: SessionIdentity | None = None
            try:
                if not session_dir.is_dir():
                    continue
                jsonl = session_dir / f"{session_dir.name}.jsonl"
                if not jsonl.is_file():
                    continue
                native_id = session_dir.name
                identity = SessionIdentity(
                    self.adapter_key, self.source_namespace, native_id
                )
                canonical = identity.canonical
                chat_dir = self._chat_session_dir(native_id)
                # Mark present before fingerprint so a read failure keeps the
                # last-known-good checkpoint entry instead of treating the
                # session as removed from disk.
                present.add(canonical)
                fingerprint = _fingerprint_session(jsonl, chat_dir)
                if current.get(canonical) == fingerprint.value:
                    continue
                sidecar = _load_sidecar(
                    chat_dir,
                    identity,
                    warnings,
                )
                fallback = datetime.fromtimestamp(
                    jsonl.stat().st_mtime, tz=timezone.utc
                )
                records.append(
                    SourceRecord(
                        identity=identity,
                        locator=OpaqueSourceLocator(str(jsonl)),
                        fingerprint=fingerprint,
                        project_hint=str(self._project_dir),
                        started_at=sidecar.started_at or fallback,
                        updated_at=sidecar.updated_at or fallback,
                        title=sidecar.title,
                        health=SessionHealth.UNKNOWN,
                        header=sidecar.header,
                    )
                )
                current[canonical] = fingerprint.value
            except OSError:
                if identity is None:
                    warnings.append(
                        AdapterWarning(
                            "cursor-session-enumerate-skipped",
                            "A Cursor transcript directory entry could not be inspected and was skipped.",
                        )
                    )
                else:
                    warnings.append(
                        AdapterWarning(
                            "session-checkpoint-retained",
                            "A Cursor transcript session could not be read; the prior checkpoint fingerprint was kept.",
                            identity,
                        )
                    )
                continue

        removed: list[SessionIdentity] = []
        for key in previous:
            if key not in present:
                removed.append(SessionIdentity.from_canonical(key))
                current.pop(key, None)

        next_checkpoint = None
        if records or removed or current != previous:
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
                        "The Cursor transcript file is unavailable.",
                        source.identity,
                    ),
                ),
            )
        turns: list[VisibleTurn] = []
        warnings: list[AdapterWarning] = []
        index = 0
        observed_header = SessionHeader()
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
                                "A Cursor transcript line could not be parsed.",
                                source.identity,
                            )
                        )
                        continue
                    observed_header = _merge_task_model_header(
                        payload, observed_header
                    )
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
                            citation_locator=f"line:{line_no}",
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
                        "The Cursor transcript file could not be read.",
                        source.identity,
                    ),
                ),
            )
        header = source.header.merged_with(observed_header)
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
            header=header,
            warnings=tuple(warnings),
        )

    @staticmethod
    def _fingerprint(path: Path) -> SourceFingerprint:
        return _fingerprint_session(path, None)

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
            # Cursor stores fingerprints only; treat schema 1 as pre-validated.
            legacy_rescan_versions=frozenset({1}),
            warnings=warnings,
        )

def _fingerprint_session(jsonl: Path, chat_dir: Path | None) -> SourceFingerprint:
    digest = hashlib.sha256()
    for path in _fingerprint_sources(jsonl, chat_dir):
        digest.update(path.name.encode("utf-8"))
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    return SourceFingerprint("sha256", digest.hexdigest())


def _fingerprint_sources(jsonl: Path, chat_dir: Path | None) -> tuple[Path, ...]:
    parts = [jsonl]
    if chat_dir is not None and chat_dir.is_dir():
        for name in ("meta.json", "store.db"):
            candidate = chat_dir / name
            if candidate.is_file():
                parts.append(candidate)
    return tuple(parts)


def _load_sidecar(
    chat_dir: Path | None,
    identity: SessionIdentity,
    warnings: list[AdapterWarning],
) -> _SidecarMetadata:
    if chat_dir is None:
        return _SidecarMetadata()
    title: str | None = None
    started_at: datetime | None = None
    updated_at: datetime | None = None
    header = SessionHeader()

    meta_path = chat_dir / "meta.json"
    if meta_path.is_file():
        try:
            document = json.loads(meta_path.read_text(encoding="utf-8"))
            if not isinstance(document, dict):
                raise ValueError("meta is not an object")
            raw_title = document.get("title")
            if isinstance(raw_title, str) and raw_title.strip():
                title = raw_title.strip()
            started_at = epoch_millis(document.get("createdAtMs"))
            updated_at = epoch_millis(document.get("updatedAtMs"))
        except (json.JSONDecodeError, UnicodeError, ValueError):
            warnings.append(
                AdapterWarning(
                    "cursor-meta-drift",
                    "Cursor meta.json had an unsupported shape.",
                    identity,
                )
            )

    store_meta = read_store_session_meta(chat_dir) if chat_dir else None
    if store_meta is not None:
        store_title = store_meta.get("name")
        if isinstance(store_title, str) and store_title.strip():
            title = title or store_title.strip()
        store_started = epoch_millis(store_meta.get("createdAt"))
        store_updated = epoch_millis(store_meta.get("updatedAt"))
        started_at = started_at or store_started
        updated_at = updated_at or store_updated
        model_id = store_meta.get("lastUsedModel")
        mode = store_meta.get("mode")
        header = SessionHeader(
            model_id=model_id if isinstance(model_id, str) else header.model_id,
            effort=mode if isinstance(mode, str) else header.effort,
        )
    elif chat_dir is not None and (chat_dir / "store.db").is_file():
        warnings.append(
            AdapterWarning(
                "cursor-store-drift",
                "Cursor store.db meta could not be read.",
                identity,
            )
        )

    return _SidecarMetadata(
        title=title,
        started_at=started_at,
        updated_at=updated_at,
        header=header,
    )


def _merge_task_model_header(
    payload: object, header: SessionHeader
) -> SessionHeader:
    if not isinstance(payload, dict) or payload.get("role") != "assistant":
        return header
    message = payload.get("message")
    if not isinstance(message, dict):
        return header
    content = message.get("content")
    if not isinstance(content, list):
        return header
    model_id = header.model_id
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        if block.get("name") not in _TASK_TOOL_NAMES:
            continue
        tool_input = block.get("input")
        if isinstance(tool_input, dict) and isinstance(tool_input.get("model"), str):
            model_id = tool_input["model"]
    if model_id == header.model_id:
        return header
    return SessionHeader(
        model_provider=header.model_provider,
        model_id=model_id,
        effort=header.effort,
    )


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
