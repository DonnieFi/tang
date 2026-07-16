"""Read-only adapter for local Codex JSONL session logs."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
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


class _UnsafeCodexSource(OSError):
    """A native log weakened or escaped the configured containment seam."""


class CodexAdapter:
    """Discover and reread Codex logs without modifying native history."""

    adapter_key = "codex"

    def __init__(
        self,
        codex_home: Path | None = None,
        *,
        source_namespace: str | None = None,
    ) -> None:
        configured_home = codex_home or Path(
            os.environ.get("CODEX_HOME", Path.home() / ".codex")
        )
        self._codex_home = configured_home.expanduser().resolve()
        self._sessions_root = self._codex_home / "sessions"
        self.source_namespace = source_namespace or self._namespace_for(
            self._codex_home
        )
        SessionIdentity(self.adapter_key, self.source_namespace, "validation")

    @staticmethod
    def _namespace_for(codex_home: Path) -> str:
        digest = hashlib.sha256(os.fsencode(codex_home)).hexdigest()
        return f"store-{digest}"

    def scan(self, checkpoint: AdapterCheckpoint | None) -> ScanBatch:
        if not self._sessions_root.is_dir():
            return ScanBatch(
                status=BatchStatus.UNAVAILABLE,
                warnings=(
                    AdapterWarning(
                        "missing-store",
                        "The configured Codex sessions directory is unavailable.",
                    ),
                ),
            )

        warnings: list[AdapterWarning] = []
        previous, validated = self._decode_checkpoint(checkpoint, warnings)
        # Carry unseen entries forward. Epic 3 owns explicit deletion handling;
        # a partial scan must not erase the last known-good indexed record.
        current = dict(previous)
        current_validated = set(validated)
        records: list[SourceRecord] = []
        seen: set[SessionIdentity] = set()
        try:
            logs, discovery_warnings = self._session_logs()
        except OSError:
            return ScanBatch(
                status=BatchStatus.UNAVAILABLE,
                warnings=(
                    AdapterWarning(
                        "unreadable-store",
                        "The configured Codex sessions directory cannot be read.",
                    ),
                ),
            )
        warnings.extend(discovery_warnings)

        for log_path in logs:
            native_id = self._filename_session_id(log_path)
            if native_id is None:
                warnings.append(
                    AdapterWarning(
                        "unrecognized-session-name",
                        "A Codex JSONL log without a terminal UUID was skipped.",
                    )
                )
                continue
            identity = SessionIdentity(
                self.adapter_key, self.source_namespace, native_id
            )
            if identity in seen:
                warnings.append(
                    AdapterWarning(
                        "duplicate-session-id",
                        "A duplicate Codex session identity was skipped.",
                        identity,
                    )
                )
                continue
            seen.add(identity)
            try:
                fingerprint = self._fingerprint(log_path)
                if (
                    previous.get(identity.canonical) == fingerprint.value
                    and identity.canonical in validated
                ):
                    # The SHA-256 digest still covers the complete native log;
                    # skip only the redundant JSON/schema pass for known bytes.
                    continue
                record, record_warnings, source_valid = self._source_record(
                    log_path, identity, fingerprint
                )
            except _UnsafeCodexSource:
                warnings.append(
                    AdapterWarning(
                        "unsafe-session-source",
                        "A symlinked or escaped Codex session log was skipped.",
                        identity,
                    )
                )
                continue
            except (OSError, UnicodeError):
                warnings.append(
                    AdapterWarning(
                        "unreadable-session",
                        "A Codex session log could not be read and was skipped.",
                        identity,
                    )
                )
                continue

            warnings.extend(
                AdapterWarning(
                    warning.code,
                    warning.message,
                    warning.identity,
                    record.project_hint,
                )
                for warning in record_warnings
            )
            if not source_valid and identity.canonical in previous:
                warnings.append(
                    AdapterWarning(
                        "last-known-good-retained",
                        "Invalid current Codex data was ignored so the prior record remains authoritative.",
                        identity,
                        record.project_hint,
                    )
                )
                continue
            current[identity.canonical] = record.fingerprint.value
            if source_valid:
                current_validated.add(identity.canonical)
            else:
                current_validated.discard(identity.canonical)
            if previous.get(identity.canonical) != record.fingerprint.value:
                records.append(record)

        removed: tuple[SessionIdentity, ...] = ()
        if not warnings:
            removed = tuple(
                SessionIdentity.from_canonical(canonical)
                for canonical in previous.keys() - {
                    identity.canonical for identity in seen
                }
            )
            for identity in removed:
                current.pop(identity.canonical, None)
                current_validated.discard(identity.canonical)

        next_checkpoint = AdapterCheckpoint(
            self.adapter_key,
            self.source_namespace,
            json.dumps(
                {
                    "schema_version": 2,
                    "fingerprints": current,
                    "validated": sorted(current_validated),
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
        return ScanBatch(
            status=BatchStatus.PARTIAL if warnings else BatchStatus.COMPLETE,
            records=tuple(records),
            removed=removed,
            next_checkpoint=next_checkpoint,
            warnings=tuple(warnings),
        )

    def read(
        self, session_ref: SourceRecord, selection: TurnSelection
    ) -> TurnBatch:
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
        try:
            log_path = self._validated_log(Path(session_ref.locator.value))
        except (OSError, ValueError):
            return self._unavailable(
                identity,
                "missing-source",
                "The selected Codex session log is unavailable.",
            )
        if self._filename_session_id(log_path) != identity.native_id:
            return self._unavailable(
                identity,
                "identity-mismatch",
                "The selected Codex log does not match its source identity.",
            )

        warnings: list[AdapterWarning] = []
        turns: list[VisibleTurn] = []
        visible_ordinal = 0
        try:
            source = log_path.open("r", encoding="utf-8")
        except (OSError, UnicodeError):
            return self._unavailable(
                identity, "unreadable-source", "The selected Codex log cannot be read."
            )
        with source:
            try:
                for line_number, line in enumerate(source, start=1):
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        warnings.append(
                            AdapterWarning(
                                "malformed-jsonl",
                                f"Skipped malformed Codex JSONL at line {line_number}.",
                                identity,
                            )
                        )
                        continue
                    visible = self._visible_message(
                        row, identity, line_number, warnings
                    )
                    if visible is None:
                        continue
                    role, text, timestamp = visible
                    if selection.includes(visible_ordinal):
                        turns.append(
                            VisibleTurn(
                                ordinal=visible_ordinal,
                                role=role,
                                text=text,
                                citation_locator=f"jsonl:{line_number}",
                                timestamp=timestamp,
                            )
                        )
                    visible_ordinal += 1
            except UnicodeError:
                warnings.append(
                    AdapterWarning(
                        "invalid-encoding",
                        "The Codex log contained invalid UTF-8 after readable data.",
                        identity,
                    )
                )

        try:
            after = self._fingerprint(log_path)
        except OSError:
            warnings.append(
                AdapterWarning(
                    "source-changed-during-read",
                    "The Codex log could not be re-fingerprinted after reading.",
                    identity,
                )
            )
        else:
            if after.value != session_ref.fingerprint.value:
                warnings.append(
                    AdapterWarning(
                        "source-changed-during-read",
                        "The Codex log changed while visible turns were being read.",
                        identity,
                    )
                )

        return TurnBatch(
            identity=identity,
            status=BatchStatus.PARTIAL if warnings else BatchStatus.COMPLETE,
            turns=tuple(turns),
            warnings=tuple(warnings),
        )

    def _session_logs(
        self,
    ) -> tuple[tuple[Path, ...], tuple[AdapterWarning, ...]]:
        root = self._sessions_root.resolve(strict=True)
        logs: list[Path] = []
        warnings: list[AdapterWarning] = []

        def visit(directory: Path) -> None:
            try:
                children = tuple(sorted(directory.iterdir(), key=lambda path: path.name))
            except OSError:
                warnings.append(
                    AdapterWarning(
                        "unreadable-session-group",
                        "One Codex session directory could not be read and was skipped.",
                    )
                )
                return
            for child in children:
                try:
                    if child.is_symlink():
                        warnings.append(
                            AdapterWarning(
                                "unsafe-session-source",
                                "A symlinked Codex session path was skipped.",
                            )
                        )
                        continue
                    resolved = child.resolve(strict=True)
                    resolved.relative_to(root)
                    if resolved.is_dir():
                        visit(resolved)
                    elif resolved.is_file() and resolved.suffix == ".jsonl":
                        logs.append(resolved)
                except (OSError, ValueError):
                    warnings.append(
                        AdapterWarning(
                            "unsafe-session-source",
                            "An unreadable or escaped Codex session path was skipped.",
                        )
                    )

        visit(root)
        return tuple(logs), tuple(warnings)

    def _source_record(
        self,
        log_path: Path,
        identity: SessionIdentity,
        fingerprint: SourceFingerprint,
    ) -> tuple[SourceRecord, tuple[AdapterWarning, ...], bool]:
        log_path = self._validated_log(log_path)
        warnings: list[AdapterWarning] = []
        metadata: dict[str, Any] | None = None
        latest: datetime | None = None
        last_lifecycle: str | None = None
        source_valid = True
        with log_path.open("r", encoding="utf-8") as source:
            for line_number, line in enumerate(source, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    source_valid = False
                    warnings.append(
                        AdapterWarning(
                            "malformed-jsonl",
                            f"Codex JSONL is malformed at line {line_number}.",
                            identity,
                        )
                    )
                    continue
                if not isinstance(row, dict):
                    source_valid = False
                    warnings.append(
                        AdapterWarning(
                            "row-schema-drift",
                            f"Codex JSONL has a non-object row at line {line_number}.",
                            identity,
                        )
                    )
                    continue
                timestamp = self._timestamp(row.get("timestamp"))
                if timestamp is None:
                    source_valid = False
                    warnings.append(
                        AdapterWarning(
                            "row-timestamp-drift",
                            f"Codex JSONL has an invalid timestamp at line {line_number}.",
                            identity,
                        )
                    )
                latest = timestamp if latest is None else max(latest, timestamp or latest)
                if metadata is None and row.get("type") == "session_meta":
                    payload = row.get("payload")
                    if isinstance(payload, dict):
                        metadata = payload
                if row.get("type") == "event_msg" and isinstance(
                    row.get("payload"), dict
                ):
                    event_type = row["payload"].get("type")
                    if event_type in {"task_started", "task_complete"}:
                        last_lifecycle = event_type
                warning_count = len(warnings)
                self._visible_message(row, identity, line_number, warnings)
                if len(warnings) != warning_count:
                    source_valid = False

        if metadata is None:
            source_valid = False
            warnings.append(
                AdapterWarning(
                    "missing-session-metadata",
                    "The Codex log has no usable session metadata.",
                    identity,
                )
            )
            metadata = {}
        metadata_id = metadata.get("id")
        if metadata_id != identity.native_id:
            source_valid = False
            warnings.append(
                AdapterWarning(
                    "session-id-mismatch",
                    "Codex metadata ID does not match the log filename identity.",
                    identity,
                )
            )
        cwd = metadata.get("cwd")
        if not isinstance(cwd, str) or not cwd:
            source_valid = False
            cwd = "unknown-project"
            warnings.append(
                AdapterWarning(
                    "missing-project-metadata",
                    "Codex metadata has no usable project directory.",
                    identity,
                )
            )
        started = self._timestamp(metadata.get("timestamp"))
        if started is None:
            source_valid = False
            started = datetime.fromtimestamp(log_path.stat().st_mtime, timezone.utc)
            warnings.append(
                AdapterWarning(
                    "missing-start-time",
                    "Codex metadata has no valid start time; filesystem time was used.",
                    identity,
                )
            )
        updated = latest or started
        if updated < started:
            source_valid = False
            updated = started
            warnings.append(
                AdapterWarning(
                    "timestamp-order",
                    "Codex row timestamps preceded the session start and were clamped.",
                    identity,
                )
            )
        return (
            SourceRecord(
                identity=identity,
                locator=OpaqueSourceLocator(str(log_path)),
                fingerprint=fingerprint,
                project_hint=cwd,
                started_at=started,
                updated_at=updated,
                health=(
                    SessionHealth.COMPLETE
                    if last_lifecycle == "task_complete"
                    else SessionHealth.UNKNOWN
                ),
            ),
            tuple(warnings),
            source_valid,
        )

    def _validated_log(self, log_path: Path) -> Path:
        if log_path.is_symlink():
            raise _UnsafeCodexSource("symlinked log")
        root = self._sessions_root.resolve(strict=True)
        resolved = log_path.resolve(strict=True)
        try:
            resolved.relative_to(root)
        except ValueError as error:
            raise _UnsafeCodexSource("log escaped configured store") from error
        if not resolved.is_file():
            raise _UnsafeCodexSource("log is not a regular file")
        return resolved

    @staticmethod
    def _filename_session_id(log_path: Path) -> str | None:
        candidate = log_path.stem.rsplit("-", 5)
        if len(candidate) < 6:
            return None
        native_id = "-".join(candidate[-5:])
        try:
            UUID(native_id)
        except ValueError:
            return None
        return native_id

    def _fingerprint(self, log_path: Path) -> SourceFingerprint:
        log_path = self._validated_log(log_path)
        digest = hashlib.sha256()
        with log_path.open("rb") as source:
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
            schema_version = payload.get("schema_version")
            if schema_version not in {1, 2} or not isinstance(fingerprints, dict):
                raise ValueError
            if not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in fingerprints.items()
            ):
                raise ValueError
            if schema_version == 1:
                # Revalidate legacy checkpoint entries once before treating them
                # as safe to skip; v1 did not record structural validity.
                return fingerprints, frozenset()
            validated = payload["validated"]
            if (
                not isinstance(validated, list)
                or not all(isinstance(value, str) for value in validated)
                or not set(validated).issubset(fingerprints)
            ):
                raise ValueError
            return fingerprints, frozenset(validated)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            warnings.append(
                AdapterWarning(
                    "checkpoint-invalid",
                    "The checkpoint was invalid; a full scan ran.",
                )
            )
            return {}, frozenset()

    @classmethod
    def _visible_message(
        cls,
        row: object,
        identity: SessionIdentity,
        line_number: int,
        warnings: list[AdapterWarning],
    ) -> tuple[TurnRole, str, datetime | None] | None:
        if not isinstance(row, dict):
            warnings.append(
                AdapterWarning(
                    "row-schema-drift",
                    f"Skipped non-object Codex row at line {line_number}.",
                    identity,
                )
            )
            return None
        if row.get("type") != "response_item":
            return None
        payload = row.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != "message":
            return None
        role = {"user": TurnRole.USER, "assistant": TurnRole.AGENT}.get(
            payload.get("role")
        )
        if role is None:
            return None
        content = payload.get("content")
        if not isinstance(content, list):
            warnings.append(
                AdapterWarning(
                    "visible-turn-schema-drift",
                    f"Skipped visible Codex message with invalid content at line {line_number}.",
                    identity,
                )
            )
            return None
        expected_type = "input_text" if role is TurnRole.USER else "output_text"
        text_parts = [
            item.get("text")
            for item in content
            if isinstance(item, dict)
            and item.get("type") == expected_type
            and isinstance(item.get("text"), str)
            and item["text"]
        ]
        if not text_parts:
            warnings.append(
                AdapterWarning(
                    "visible-turn-schema-drift",
                    f"Skipped visible Codex message without supported text at line {line_number}.",
                    identity,
                )
            )
            return None
        return role, "\n".join(text_parts), cls._timestamp(row.get("timestamp"))

    @staticmethod
    def _timestamp(value: object) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _unavailable(
        identity: SessionIdentity, code: str, message: str
    ) -> TurnBatch:
        return TurnBatch(
            identity=identity,
            status=BatchStatus.UNAVAILABLE,
            warnings=(AdapterWarning(code, message, identity),),
        )
