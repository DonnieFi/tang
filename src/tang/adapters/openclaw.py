"""Read-only adapter for OpenClaw agent SQLite session stores."""

from __future__ import annotations

import base64
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
    SourceRecord,
    TurnBatch,
    TurnRole,
    TurnSelection,
    VisibleTurn,
)
from tang.adapters.incremental_checkpoint import decode_fingerprint_checkpoint
from tang.openclaw_store import (
    fingerprint_session,
    has_sessions,
    load_sessions,
    read_message_events,
)

_LOCATOR_PREFIX = "openclaw:"


class OpenClawAdapter:
    """Discover and reread OpenClaw sessions from one agent SQLite database."""

    adapter_key = "openclaw"

    def __init__(
        self,
        project_dir: Path | str,
        *,
        openclaw_home: Path | None = None,
        agent_id: str = "main",
        source_namespace: str | None = None,
    ) -> None:
        self._project_dir = Path(project_dir).expanduser().resolve()
        configured = openclaw_home or Path(
            os.environ.get("OPENCLAW_HOME", Path.home() / ".openclaw")
        )
        self._openclaw_home = configured.expanduser().resolve()
        self._agent_id = agent_id
        self._agent_db = (
            self._openclaw_home / "agents" / agent_id / "agent" / "openclaw-agent.sqlite"
        )
        self.source_namespace = source_namespace or self._namespace_for(
            self._openclaw_home, agent_id
        )
        SessionIdentity(self.adapter_key, self.source_namespace, "validation")

    @staticmethod
    def _namespace_for(openclaw_home: Path, agent_id: str) -> str:
        digest = hashlib.sha256(
            os.fsencode(f"{openclaw_home}:{agent_id}")
        ).hexdigest()
        return f"store-{digest}"

    @staticmethod
    def encode_native_id(session_key: str) -> str:
        """Encode a colon-bearing OpenClaw session key for SessionIdentity."""

        return base64.urlsafe_b64encode(session_key.encode("utf-8")).decode(
            "ascii"
        ).rstrip("=")

    @staticmethod
    def decode_native_id(native_id: str) -> str:
        padding = "=" * (-len(native_id) % 4)
        return base64.urlsafe_b64decode(native_id + padding).decode("utf-8")

    def has_project_sessions(self) -> bool:
        return self._prefer_sqlite() and has_sessions(self._agent_db)

    def _prefer_sqlite(self) -> bool:
        return self._agent_db.is_file()

    def scan(self, checkpoint: AdapterCheckpoint | None) -> ScanBatch:
        if not self._prefer_sqlite():
            return ScanBatch(
                status=BatchStatus.UNAVAILABLE,
                warnings=(
                    AdapterWarning(
                        "missing-store",
                        "No OpenClaw agent database was found.",
                    ),
                ),
            )

        warnings: list[AdapterWarning] = []
        previous, _validated = self._decode_checkpoint(checkpoint, warnings)
        current = dict(previous)
        records: list[SourceRecord] = []
        present: set[str] = set()

        try:
            sessions = load_sessions(self._agent_db)
        except OSError:
            return ScanBatch(
                status=BatchStatus.UNAVAILABLE,
                warnings=(
                    AdapterWarning(
                        "unreadable-store",
                        "The OpenClaw agent database could not be read.",
                    ),
                ),
            )

        for session in sessions:
            identity = SessionIdentity(
                self.adapter_key,
                self.source_namespace,
                self.encode_native_id(session.session_key),
            )
            canonical = identity.canonical
            present.add(canonical)
            try:
                fingerprint = fingerprint_session(self._agent_db, session.session_id)
                if current.get(canonical) == fingerprint.value:
                    continue
                records.append(
                    SourceRecord(
                        identity=identity,
                        locator=OpaqueSourceLocator(
                            _encode_locator(
                                self._agent_db,
                                session.session_key,
                                session.session_id,
                            )
                        ),
                        fingerprint=fingerprint,
                        project_hint=str(self._project_dir),
                        started_at=session.started_at,
                        updated_at=session.updated_at,
                        title=session.title,
                        health=SessionHealth.UNKNOWN,
                        header=session.header,
                    )
                )
                current[canonical] = fingerprint.value
            except OSError:
                warnings.append(
                    AdapterWarning(
                        "session-checkpoint-retained",
                        "An OpenClaw session could not be fingerprinted; the prior checkpoint fingerprint was kept.",
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
        locator = _decode_locator(source.locator.value)
        if locator is None:
            return TurnBatch(
                source.identity,
                BatchStatus.UNAVAILABLE,
                (),
                header=SessionHeader(),
                warnings=(
                    AdapterWarning(
                        "invalid-locator",
                        "The OpenClaw source locator is invalid.",
                        source.identity,
                    ),
                ),
            )

        db_path, session_key, session_id = locator
        if self.decode_native_id(source.identity.native_id) != session_key:
            return TurnBatch(
                source.identity,
                BatchStatus.UNAVAILABLE,
                (),
                header=SessionHeader(),
                warnings=(
                    AdapterWarning(
                        "identity-mismatch",
                        "The OpenClaw session identity does not match its locator.",
                        source.identity,
                    ),
                ),
            )

        if not db_path.is_file():
            return TurnBatch(
                source.identity,
                BatchStatus.UNAVAILABLE,
                (),
                header=SessionHeader(),
                warnings=(
                    AdapterWarning(
                        "missing-transcript",
                        "The OpenClaw agent database is unavailable.",
                        source.identity,
                    ),
                ),
            )

        turns: list[VisibleTurn] = []
        warnings: list[AdapterWarning] = []
        observed_header = SessionHeader()
        index = 0
        try:
            events = read_message_events(db_path, session_id)
        except OSError:
            return TurnBatch(
                source.identity,
                BatchStatus.UNAVAILABLE,
                (),
                header=SessionHeader(),
                warnings=(
                    AdapterWarning(
                        "unreadable-transcript",
                        "The OpenClaw transcript could not be read.",
                        source.identity,
                    ),
                ),
            )

        for seq, payload in events:
            if payload.get("type") != "message":
                continue
            message = payload.get("message")
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            if role not in {"user", "assistant"}:
                continue
            text = _visible_text(message.get("content"))
            if not text.strip():
                continue
            observed_header = _merge_header(message, observed_header)
            index += 1
            if not selection.includes(index):
                continue
            timestamp = _parse_timestamp(payload.get("timestamp")) or _epoch_millis(
                message.get("timestamp")
            )
            turns.append(
                VisibleTurn(
                    ordinal=index,
                    role=TurnRole.USER if role == "user" else TurnRole.AGENT,
                    text=text,
                    citation_locator=f"seq:{seq}",
                    timestamp=timestamp,
                )
            )

        header = source.header.merged_with(observed_header)
        if not turns:
            warnings.append(
                AdapterWarning(
                    "no-visible-turns",
                    "The OpenClaw session had no readable user or assistant text.",
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


def _encode_locator(db_path: Path, session_key: str, session_id: str) -> str:
    payload = {
        "db": str(db_path),
        "session_key": session_key,
        "session_id": session_id,
    }
    return _LOCATOR_PREFIX + json.dumps(payload, sort_keys=True)


def _decode_locator(value: str) -> tuple[Path, str, str] | None:
    if not value.startswith(_LOCATOR_PREFIX):
        return None
    try:
        payload = json.loads(value[len(_LOCATOR_PREFIX) :])
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    db = payload.get("db")
    session_key = payload.get("session_key")
    session_id = payload.get("session_id")
    if not all(isinstance(item, str) and item for item in (db, session_key, session_id)):
        return None
    return Path(db), session_key, session_id


def _visible_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
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
    return ""


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


def _epoch_millis(value: object) -> datetime | None:
    if value is None or not isinstance(value, int):
        return None
    seconds = value / 1000 if value > 10**12 else value
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None


def _merge_header(message: dict[str, object], header: SessionHeader) -> SessionHeader:
    provider = message.get("provider")
    model = message.get("model")
    return SessionHeader(
        model_provider=provider if isinstance(provider, str) else header.model_provider,
        model_id=model if isinstance(model, str) else header.model_id,
        effort=header.effort,
        git_branch=header.git_branch,
        agent_role=header.agent_role,
        compacted=header.compacted,
    )
