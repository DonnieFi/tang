"""Read-only adapter for Grok Build's documented local session store."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote
from uuid import UUID

from tang.adapters.base import (
    AdapterCheckpoint,
    AdapterWarning,
    BatchStatus,
    OpaqueSourceLocator,
    ScanBatch,
    SessionHealth,
    SessionIdentity,
    SourceFingerprint,
    SourceRecord,
    TurnBatch,
    TurnRole,
    TurnSelection,
    VisibleTurn,
)


class GrokAdapter:
    """Scan and reread Grok sessions without modifying their native store."""

    adapter_key = "grok"

    def __init__(
        self,
        grok_home: Path | None = None,
        *,
        source_namespace: str | None = None,
    ) -> None:
        configured_home = grok_home or Path(
            os.environ.get("GROK_HOME", Path.home() / ".grok")
        )
        self._grok_home = configured_home.expanduser().resolve()
        self._sessions_root = self._grok_home / "sessions"
        self.source_namespace = source_namespace or self._namespace_for(
            self._grok_home
        )
        # Validate caller-supplied namespaces through the canonical identity rules.
        SessionIdentity(self.adapter_key, self.source_namespace, "validation")

    @staticmethod
    def _namespace_for(grok_home: Path) -> str:
        digest = hashlib.sha256(os.fsencode(grok_home)).hexdigest()
        return f"store-{digest}"

    def scan(self, checkpoint: AdapterCheckpoint | None) -> ScanBatch:
        """Return sessions changed since an adapter-owned checkpoint."""
        if not self._sessions_root.is_dir():
            return ScanBatch(
                status=BatchStatus.UNAVAILABLE,
                warnings=(
                    AdapterWarning(
                        "missing-store",
                        "The configured Grok sessions directory is unavailable.",
                    ),
                ),
            )

        warnings: list[AdapterWarning] = []
        previous = self._decode_checkpoint(checkpoint, warnings)
        current: dict[str, str] = {}
        records: list[SourceRecord] = []

        try:
            session_dirs = self._session_dirs()
        except OSError:
            return ScanBatch(
                status=BatchStatus.UNAVAILABLE,
                warnings=(
                    AdapterWarning(
                        "unreadable-store",
                        "The configured Grok sessions directory cannot be read.",
                    ),
                ),
            )

        for session_dir in session_dirs:
            native_id = session_dir.name
            identity = SessionIdentity(
                self.adapter_key, self.source_namespace, native_id
            )
            try:
                record, record_warnings = self._source_record(session_dir, identity)
            except OSError:
                warnings.append(
                    AdapterWarning(
                        "unreadable-session",
                        "A Grok session could not be read and was skipped.",
                        identity,
                    )
                )
                continue

            warnings.extend(record_warnings)
            current[identity.canonical] = record.fingerprint.value
            if previous.get(identity.canonical) != record.fingerprint.value:
                records.append(record)

        next_checkpoint = AdapterCheckpoint(
            self.adapter_key,
            self.source_namespace,
            json.dumps(
                {"schema_version": 1, "fingerprints": current},
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
        return ScanBatch(
            status=BatchStatus.PARTIAL if warnings else BatchStatus.COMPLETE,
            records=tuple(records),
            next_checkpoint=next_checkpoint,
            warnings=tuple(warnings),
        )

    def read(
        self, session_ref: SourceRecord, selection: TurnSelection
    ) -> TurnBatch:
        """Reread only visible user and agent text updates from one session."""
        identity = session_ref.identity
        if (
            identity.adapter != self.adapter_key
            or identity.source_namespace != self.source_namespace
        ):
            return self._unavailable(
                identity,
                "wrong-source",
                "The source record belongs to a different adapter namespace.",
            )

        session_dir = Path(session_ref.locator.value)
        try:
            resolved_session = session_dir.resolve(strict=True)
            resolved_session.relative_to(self._sessions_root.resolve(strict=True))
        except (OSError, ValueError):
            return self._unavailable(
                identity,
                "missing-source",
                "The selected Grok session source is unavailable.",
            )
        if resolved_session.name != identity.native_id:
            return self._unavailable(
                identity,
                "wrong-source",
                "The source locator does not match the selected session identity.",
            )

        updates_path = resolved_session / "updates.jsonl"
        if not updates_path.is_file():
            return self._unavailable(
                identity,
                "missing-updates",
                "The selected Grok session has no readable update stream.",
            )

        warnings: list[AdapterWarning] = []
        try:
            fingerprint = self._fingerprint(resolved_session)
        except OSError:
            return self._unavailable(
                identity,
                "unreadable-source",
                "The selected Grok session cannot be fingerprinted.",
            )
        if fingerprint.value != session_ref.fingerprint.value:
            warnings.append(
                AdapterWarning(
                    "source-changed",
                    "The native source changed after discovery; current visible turns were read.",
                    identity,
                )
            )

        turns: list[VisibleTurn] = []
        visible_ordinal = 0
        try:
            with updates_path.open("r", encoding="utf-8") as updates:
                for line_number, line in enumerate(updates, start=1):
                    if not line.strip():
                        continue
                    try:
                        update = json.loads(line)
                    except json.JSONDecodeError:
                        code = (
                            "truncated-update"
                            if not line.endswith("\n")
                            else "malformed-update"
                        )
                        warnings.append(
                            AdapterWarning(
                                code,
                                f"Skipped invalid update at line {line_number}.",
                                identity,
                            )
                        )
                        continue

                    visible = self._visible_update(
                        update, identity, line_number, warnings
                    )
                    if visible is None:
                        continue
                    role, text, timestamp = visible
                    ordinal = visible_ordinal
                    visible_ordinal += 1
                    if selection.includes(ordinal):
                        turns.append(
                            VisibleTurn(
                                ordinal=ordinal,
                                role=role,
                                text=text,
                                citation_locator=f"updates.jsonl:{line_number}",
                                timestamp=timestamp,
                            )
                        )
        except (OSError, UnicodeError):
            warnings.append(
                AdapterWarning(
                    "unreadable-updates",
                    "The update stream ended before it could be fully read.",
                    identity,
                )
            )

        return TurnBatch(
            identity=identity,
            status=BatchStatus.PARTIAL if warnings else BatchStatus.COMPLETE,
            turns=tuple(turns),
            warnings=tuple(warnings),
        )

    def _session_dirs(self) -> tuple[Path, ...]:
        sessions: list[Path] = []
        for group in sorted(self._sessions_root.iterdir(), key=lambda path: path.name):
            if not group.is_dir():
                continue
            for candidate in sorted(group.iterdir(), key=lambda path: path.name):
                if candidate.is_dir() and self._is_uuid(candidate.name):
                    sessions.append(candidate)
        return tuple(sessions)

    @staticmethod
    def _is_uuid(value: str) -> bool:
        try:
            return str(UUID(value)) == value.lower()
        except ValueError:
            return False

    def _source_record(
        self, session_dir: Path, identity: SessionIdentity
    ) -> tuple[SourceRecord, tuple[AdapterWarning, ...]]:
        warnings: list[AdapterWarning] = []
        summary_path = session_dir / "summary.json"
        summary: dict[str, Any] = {}
        try:
            loaded = json.loads(summary_path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError("summary is not an object")
            summary = loaded
        except FileNotFoundError:
            warnings.append(
                AdapterWarning(
                    "missing-summary",
                    "A Grok session is missing summary metadata; filesystem times were used.",
                    identity,
                )
            )
        except (json.JSONDecodeError, UnicodeError, ValueError):
            warnings.append(
                AdapterWarning(
                    "malformed-summary",
                    "A Grok session has malformed summary metadata; filesystem times were used.",
                    identity,
                )
            )

        fallback = datetime.fromtimestamp(session_dir.stat().st_mtime, timezone.utc)
        started_at = self._summary_time(
            summary.get("created_at"), fallback, "created-at-drift", identity, warnings
        )
        updated_at = self._summary_time(
            summary.get("updated_at"), fallback, "updated-at-drift", identity, warnings
        )
        if updated_at < started_at:
            warnings.append(
                AdapterWarning(
                    "timestamp-order",
                    "A Grok session update time preceded its creation time; creation time was used.",
                    identity,
                )
            )
            updated_at = started_at

        project_hint = summary.get("git_root_dir")
        if not isinstance(project_hint, str) or not project_hint:
            project_hint = self._group_cwd(session_dir.parent, identity, warnings)
        title = summary.get("generated_title")
        if not isinstance(title, str) or not title:
            title = None

        return (
            SourceRecord(
                identity=identity,
                locator=OpaqueSourceLocator(str(session_dir.resolve())),
                fingerprint=self._fingerprint(session_dir),
                project_hint=project_hint,
                started_at=started_at,
                updated_at=updated_at,
                title=title,
                health=SessionHealth.UNKNOWN,
            ),
            tuple(warnings),
        )

    @staticmethod
    def _summary_time(
        value: object,
        fallback: datetime,
        warning_code: str,
        identity: SessionIdentity,
        warnings: list[AdapterWarning],
    ) -> datetime:
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is not None and parsed.utcoffset() is not None:
                    return parsed.astimezone(timezone.utc)
            except ValueError:
                pass
        warnings.append(
            AdapterWarning(
                warning_code,
                "A Grok summary timestamp was absent or unsupported; filesystem time was used.",
                identity,
            )
        )
        return fallback

    @staticmethod
    def _group_cwd(
        group_dir: Path,
        identity: SessionIdentity,
        warnings: list[AdapterWarning],
    ) -> str:
        cwd_file = group_dir / ".cwd"
        if cwd_file.is_file():
            try:
                cwd = cwd_file.read_text(encoding="utf-8").strip()
                if cwd:
                    return cwd
            except (OSError, UnicodeError):
                warnings.append(
                    AdapterWarning(
                        "unreadable-project-hint",
                        "A Grok session project hint could not be read.",
                        identity,
                    )
                )
        decoded = unquote(group_dir.name)
        return decoded or "unknown-project"

    @staticmethod
    def _fingerprint(session_dir: Path) -> SourceFingerprint:
        digest = hashlib.sha256()
        for name in ("summary.json", "updates.jsonl"):
            digest.update(name.encode("ascii"))
            path = session_dir / name
            if not path.is_file():
                digest.update(b"\0missing\0")
                continue
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
        return SourceFingerprint("sha256", digest.hexdigest())

    def _decode_checkpoint(
        self,
        checkpoint: AdapterCheckpoint | None,
        warnings: list[AdapterWarning],
    ) -> dict[str, str]:
        if checkpoint is None:
            return {}
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
            return {}
        try:
            payload = json.loads(checkpoint.cursor)
            fingerprints = payload["fingerprints"]
            if payload.get("schema_version") != 1 or not isinstance(
                fingerprints, dict
            ):
                raise ValueError
            if not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in fingerprints.items()
            ):
                raise ValueError
            return fingerprints
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            warnings.append(
                AdapterWarning(
                    "checkpoint-invalid",
                    "The checkpoint was invalid; a full scan ran.",
                )
            )
            return {}

    @staticmethod
    def _visible_update(
        update: object,
        identity: SessionIdentity,
        line_number: int,
        warnings: list[AdapterWarning],
    ) -> tuple[TurnRole, str, datetime | None] | None:
        if not isinstance(update, dict):
            warnings.append(
                AdapterWarning(
                    "update-schema-drift",
                    f"Skipped non-object update at line {line_number}.",
                    identity,
                )
            )
            return None
        if update.get("method") not in {"session/update", "_x.ai/session/update"}:
            return None
        params = update.get("params")
        if not isinstance(params, dict):
            return None
        native_id = params.get("sessionId")
        if native_id != identity.native_id:
            warnings.append(
                AdapterWarning(
                    "session-id-mismatch",
                    f"Skipped update with a mismatched session ID at line {line_number}.",
                    identity,
                )
            )
            return None
        body = params.get("update")
        if not isinstance(body, dict):
            return None
        update_kind = body.get("sessionUpdate")
        roles = {
            "user_message_chunk": TurnRole.USER,
            "agent_message_chunk": TurnRole.AGENT,
        }
        role = roles.get(update_kind)
        if role is None:
            return None
        content = body.get("content")
        if (
            not isinstance(content, dict)
            or content.get("type") != "text"
            or not isinstance(content.get("text"), str)
            or not content["text"]
        ):
            warnings.append(
                AdapterWarning(
                    "visible-turn-schema-drift",
                    f"Skipped unsupported visible turn at line {line_number}.",
                    identity,
                )
            )
            return None
        return role, content["text"], GrokAdapter._update_time(update.get("timestamp"))

    @staticmethod
    def _update_time(value: object) -> datetime | None:
        try:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return datetime.fromtimestamp(value, timezone.utc)
            if isinstance(value, str):
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is not None and parsed.utcoffset() is not None:
                    return parsed.astimezone(timezone.utc)
        except (OSError, OverflowError, ValueError):
            pass
        return None

    @staticmethod
    def _unavailable(
        identity: SessionIdentity, code: str, message: str
    ) -> TurnBatch:
        return TurnBatch(
            identity=identity,
            status=BatchStatus.UNAVAILABLE,
            warnings=(AdapterWarning(code, message, identity),),
        )
