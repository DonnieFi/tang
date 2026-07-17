"""Read-only adapter for OpenCode's supported server and export contracts."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import (
    HTTPRedirectHandler,
    ProxyHandler,
    Request,
    build_opener,
)

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


MINIMUM_OPENCODE_VERSION = (1, 17, 18)
MAXIMUM_OPENCODE_MAJOR = 2
CATALOG_LIMIT = 500
CATALOG_RESPONSE_LIMIT = 8 * 1024 * 1024
EXPORT_RESPONSE_LIMIT = 8 * 1024 * 1024
_SESSION_ID = re.compile(r"ses_[A-Za-z0-9_-]{1,128}\Z")
_VERSION_PART = r"(?:0|[1-9][0-9]*)"
_VERSION = re.compile(
    rf"({_VERSION_PART})\.({_VERSION_PART})\.({_VERSION_PART})\Z"
)
_LOCATOR_PREFIX = "opencode-session-v1:"


def _supported_version(value: str) -> bool:
    match = _VERSION.fullmatch(value)
    if match is None:
        return False
    version = tuple(int(part) for part in match.groups())
    return MINIMUM_OPENCODE_VERSION <= version and version[0] < MAXIMUM_OPENCODE_MAJOR


class _OpenCodeFailure(RuntimeError):
    """One fixed-class native operation failed without exposing raw output."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class _NoRedirect(HTTPRedirectHandler):
    """Keep private localhost catalog queries on the intended origin."""

    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


class OpenCodeAdapter:
    """Discover and reread OpenCode sessions without private-store access."""

    adapter_key = "opencode"

    def __init__(
        self,
        project_dir: Path | str,
        executable: Path | str = "opencode",
        *,
        source_namespace: str | None = None,
        command_timeout: float = 30.0,
        catalog_limit: int = CATALOG_LIMIT,
    ) -> None:
        self._project_dir = Path(project_dir).expanduser().resolve(strict=True)
        if not self._project_dir.is_dir():
            raise ValueError("OpenCode project path must identify a directory")
        if command_timeout <= 0 or catalog_limit <= 0:
            raise ValueError("OpenCode limits and timeouts must be positive")
        self._executable = os.fspath(executable)
        self._command_timeout = command_timeout
        self._catalog_limit = catalog_limit
        self.source_namespace = source_namespace or self._namespace_for(
            self._executable
        )
        self._checkpoint_scope = hashlib.sha256(
            os.fsencode(self._project_dir)
        ).hexdigest()
        SessionIdentity(self.adapter_key, self.source_namespace, "validation")

    @staticmethod
    def _namespace_for(executable: str) -> str:
        resolved = shutil.which(executable) or os.path.abspath(executable)
        data_home = os.environ.get(
            "XDG_DATA_HOME", os.fspath(Path.home() / ".local" / "share")
        )
        digest = hashlib.sha256(
            os.fsencode(f"{resolved}\0{os.path.abspath(data_home)}")
        ).hexdigest()
        return f"store-{digest}"

    @staticmethod
    def _environment(**overrides: str) -> dict[str, str]:
        return {
            **os.environ,
            "OPENCODE_DISABLE_AUTOUPDATE": "1",
            "OPENCODE_DISABLE_DEFAULT_PLUGINS": "1",
            "OPENCODE_DISABLE_MODELS_FETCH": "1",
            **overrides,
        }

    def scan(self, checkpoint: AdapterCheckpoint | None) -> ScanBatch:
        warnings: list[AdapterWarning] = []
        scopes = self._decode_checkpoint(checkpoint, warnings)
        previous = scopes.get(self._checkpoint_scope, {})
        try:
            version = self._run_cli(("--version",), "version").strip()
        except _OpenCodeFailure as error:
            return self._scan_unavailable(error)
        if not _supported_version(version):
            return self._scan_unavailable(
                _OpenCodeFailure(
                    "unsupported-version",
                    "Install a stable OpenCode version >=1.17.18 and <2.0.0.",
                )
            )
        try:
            catalog = self._catalog()
        except _OpenCodeFailure as error:
            return self._scan_unavailable(error)

        current = dict(previous)
        records: list[SourceRecord] = []
        seen: set[SessionIdentity] = set()
        ordered = sorted(catalog, key=self._catalog_sort_key)
        if len(ordered) > self._catalog_limit:
            warnings.append(
                AdapterWarning(
                    "catalog-limit",
                    "The bounded OpenCode session catalog is incomplete; older sessions were not scanned.",
                    project_hint=str(self._project_dir),
                )
            )
            ordered = ordered[: self._catalog_limit]

        for item in ordered:
            record = self._catalog_record(item, warnings, seen)
            if record is None:
                continue
            current[record.identity.canonical] = record.fingerprint.value
            if previous.get(record.identity.canonical) != record.fingerprint.value:
                records.append(record)

        removed: tuple[SessionIdentity, ...] = ()
        if not warnings:
            absent_from_scope = previous.keys() - {
                identity.canonical for identity in seen
            }
            retained_elsewhere = {
                canonical
                for scope, fingerprints in scopes.items()
                if scope != self._checkpoint_scope
                for canonical in fingerprints
            }
            removed = tuple(
                SessionIdentity.from_canonical(canonical)
                for canonical in absent_from_scope - retained_elsewhere
            )
            for canonical in absent_from_scope:
                current.pop(canonical, None)

        next_scopes = {**scopes, self._checkpoint_scope: current}
        next_checkpoint = AdapterCheckpoint(
            self.adapter_key,
            self.source_namespace,
            json.dumps(
                {"schema_version": 2, "scopes": next_scopes},
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
        if session_ref.fingerprint.algorithm != "opencode-updated-ms-v1":
            return self._unavailable(
                identity,
                "wrong-source",
                "The source record has an unsupported OpenCode fingerprint.",
            )
        if self._locator_id(session_ref.locator) != identity.native_id:
            return self._unavailable(
                identity,
                "identity-mismatch",
                "The selected OpenCode locator does not match its source identity.",
            )
        if not self._same_project(session_ref.project_hint):
            return self._unavailable(
                identity,
                "project-mismatch",
                "The selected OpenCode session does not belong to this project.",
            )
        try:
            raw = self._run_cli(
                ("--pure", "export", identity.native_id), "session-export"
            )
            document = json.loads(raw)
        except _OpenCodeFailure as error:
            return self._unavailable(identity, error.code, str(error))
        except (json.JSONDecodeError, UnicodeError):
            return self._unavailable(
                identity,
                "session-export-invalid-json",
                "The selected OpenCode export was not valid JSON.",
            )
        if not isinstance(document, dict):
            return self._unavailable(
                identity,
                "session-export-schema-drift",
                "The selected OpenCode export has an unsupported shape.",
            )

        info = document.get("info")
        messages = document.get("messages")
        if not isinstance(info, dict) or not isinstance(messages, list):
            return self._unavailable(
                identity,
                "session-export-schema-drift",
                "The selected OpenCode export has an unsupported shape.",
            )
        if info.get("id") != identity.native_id:
            return self._unavailable(
                identity,
                "identity-mismatch",
                "The selected OpenCode export does not match its source identity.",
            )
        if not self._same_project(info.get("directory")):
            return self._unavailable(
                identity,
                "project-mismatch",
                "The selected OpenCode export belongs to another project.",
            )

        warnings: list[AdapterWarning] = []
        turns = self._visible_turns(messages, identity, selection, warnings)
        time_value = info.get("time")
        updated = time_value.get("updated") if isinstance(time_value, dict) else None
        if not self._nonnegative_integer(updated):
            warnings.append(
                AdapterWarning(
                    "source-change-evidence-missing",
                    "The OpenCode export has no valid updated timestamp.",
                    identity,
                )
            )
        elif str(updated) != session_ref.fingerprint.value:
            warnings.append(
                AdapterWarning(
                    "source-changed-during-read",
                    "The OpenCode session changed after it was scanned.",
                    identity,
                )
            )
        return TurnBatch(
            identity=identity,
            status=BatchStatus.PARTIAL if warnings else BatchStatus.COMPLETE,
            turns=turns,
            warnings=tuple(warnings),
        )

    def _catalog_record(
        self,
        item: object,
        warnings: list[AdapterWarning],
        seen: set[SessionIdentity],
    ) -> SourceRecord | None:
        if not isinstance(item, dict):
            warnings.append(
                AdapterWarning(
                    "catalog-schema-drift",
                    "An OpenCode catalog item had an unsupported shape and was skipped.",
                    project_hint=str(self._project_dir),
                )
            )
            return None
        native_id = item.get("id")
        if not isinstance(native_id, str) or not _SESSION_ID.fullmatch(native_id):
            warnings.append(
                AdapterWarning(
                    "catalog-identity-drift",
                    "An OpenCode catalog item had an invalid identity and was skipped.",
                    project_hint=str(self._project_dir),
                )
            )
            return None
        identity = SessionIdentity(
            self.adapter_key, self.source_namespace, native_id
        )
        if identity in seen:
            warnings.append(
                AdapterWarning(
                    "duplicate-session-id",
                    "A duplicate OpenCode session identity was skipped.",
                    identity,
                    str(self._project_dir),
                )
            )
            return None
        seen.add(identity)

        directory = item.get("directory")
        time_value = item.get("time")
        created = time_value.get("created") if isinstance(time_value, dict) else None
        updated = time_value.get("updated") if isinstance(time_value, dict) else None
        started_at = self._milliseconds(created)
        updated_at = self._milliseconds(updated)
        if (
            not self._same_project(directory)
            or started_at is None
            or updated_at is None
            or updated_at < started_at
        ):
            warnings.append(
                AdapterWarning(
                    "catalog-metadata-drift",
                    "An OpenCode catalog item had invalid project or timestamp metadata and was skipped.",
                    identity,
                    str(self._project_dir),
                )
            )
            return None
        title = item.get("title")
        if not isinstance(title, str) or not title.strip():
            title = None
            warnings.append(
                AdapterWarning(
                    "catalog-title-drift",
                    "An OpenCode session had no usable title.",
                    identity,
                    str(self._project_dir),
                )
            )
        return SourceRecord(
            identity=identity,
            locator=OpaqueSourceLocator(f"{_LOCATOR_PREFIX}{native_id}"),
            fingerprint=SourceFingerprint("opencode-updated-ms-v1", str(updated)),
            project_hint=str(self._project_dir),
            started_at=started_at,
            updated_at=updated_at,
            title=title,
            health=SessionHealth.UNKNOWN,
        )

    @staticmethod
    def _catalog_sort_key(item: object) -> tuple[int, str]:
        if not isinstance(item, dict):
            return (0, "")
        time_value = item.get("time")
        updated = time_value.get("updated") if isinstance(time_value, dict) else None
        sortable_updated = updated if OpenCodeAdapter._nonnegative_integer(updated) else 0
        native_id = item.get("id")
        return (-sortable_updated, native_id if isinstance(native_id, str) else "")

    def _visible_turns(
        self,
        messages: list[object],
        identity: SessionIdentity,
        selection: TurnSelection,
        warnings: list[AdapterWarning],
    ) -> tuple[VisibleTurn, ...]:
        visible: list[tuple[int, str, TurnRole, str]] = []
        message_ids: set[str] = set()
        for message in messages:
            if not isinstance(message, dict):
                warnings.append(
                    AdapterWarning(
                        "message-schema-drift",
                        "An OpenCode message had an unsupported shape and was skipped.",
                        identity,
                    )
                )
                continue
            info = message.get("info")
            parts = message.get("parts")
            if not isinstance(info, dict) or not isinstance(parts, list):
                warnings.append(
                    AdapterWarning(
                        "message-schema-drift",
                        "An OpenCode message had unsupported metadata and was skipped.",
                        identity,
                    )
                )
                continue
            role = {"user": TurnRole.USER, "assistant": TurnRole.AGENT}.get(
                info.get("role")
            )
            if role is None:
                continue
            message_id = info.get("id")
            session_id = info.get("sessionID")
            time_value = info.get("time")
            created = time_value.get("created") if isinstance(time_value, dict) else None
            if (
                not isinstance(message_id, str)
                or not message_id.strip()
                or message_id in message_ids
                or session_id != identity.native_id
                or not self._nonnegative_integer(created)
            ):
                warnings.append(
                    AdapterWarning(
                        "message-metadata-drift",
                        "An OpenCode visible message had invalid ordering or identity metadata and was skipped.",
                        identity,
                    )
                )
                continue
            message_ids.add(message_id)
            text_parts = [
                part["text"]
                for part in parts
                if isinstance(part, dict)
                and part.get("type") == "text"
                and not part.get("ignored", False)
                and isinstance(part.get("text"), str)
                and bool(part["text"].strip())
            ]
            if not text_parts:
                continue
            visible.append((created, message_id, role, "\n".join(text_parts)))

        turns: list[VisibleTurn] = []
        for ordinal, (created, message_id, role, text) in enumerate(
            sorted(visible, key=lambda item: (item[0], item[1]))
        ):
            if selection.includes(ordinal):
                turns.append(
                    VisibleTurn(
                        ordinal=ordinal,
                        role=role,
                        text=text,
                        citation_locator=f"message:{message_id}",
                        timestamp=self._milliseconds(created),
                    )
                )
        return tuple(turns)

    def _catalog(self) -> list[object]:
        password = secrets.token_urlsafe(32)
        username = "tang"
        port = self._available_port()
        environment = self._environment(
            OPENCODE_SERVER_PASSWORD=password,
            OPENCODE_SERVER_USERNAME=username,
        )
        try:
            process = subprocess.Popen(
                [
                    self._executable,
                    "--pure",
                    "serve",
                    "--hostname",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                cwd=self._project_dir,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError as error:
            raise _OpenCodeFailure(
                "missing-executable", "The OpenCode executable is unavailable."
            ) from error
        except OSError as error:
            raise _OpenCodeFailure(
                "catalog-unavailable",
                "The OpenCode session catalog could not be started.",
            ) from error

        deadline = time.monotonic() + self._command_timeout
        query = urlencode(
            {
                "directory": str(self._project_dir),
                "limit": self._catalog_limit + 1,
            }
        )
        credentials = base64.b64encode(
            f"{username}:{password}".encode("utf-8")
        ).decode("ascii")
        request = Request(
            f"http://127.0.0.1:{port}/session?{query}",
            headers={"Authorization": f"Basic {credentials}"},
        )
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        try:
            while True:
                if process.poll() is not None:
                    raise _OpenCodeFailure(
                        "catalog-unavailable",
                        "The OpenCode session catalog exited before it was ready.",
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise _OpenCodeFailure(
                        "catalog-timeout",
                        "The OpenCode session catalog timed out.",
                    )
                try:
                    with opener.open(
                        request, timeout=min(0.5, remaining)
                    ) as response:
                        raw = response.read(CATALOG_RESPONSE_LIMIT + 1)
                    break
                except HTTPError as error:
                    if error.code >= 500:
                        time.sleep(0.05)
                        continue
                    raise _OpenCodeFailure(
                        "catalog-unavailable",
                        "The OpenCode session catalog rejected the request.",
                    ) from error
                except (TimeoutError, URLError, OSError):
                    time.sleep(0.05)
            if len(raw) > CATALOG_RESPONSE_LIMIT:
                raise _OpenCodeFailure(
                    "catalog-too-large",
                    "The bounded OpenCode session catalog exceeded its safe response size.",
                )
            try:
                document = json.loads(raw.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as error:
                raise _OpenCodeFailure(
                    "catalog-invalid-json",
                    "The OpenCode session catalog did not return valid JSON.",
                ) from error
            if not isinstance(document, list):
                raise _OpenCodeFailure(
                    "catalog-schema-drift",
                    "The OpenCode session catalog has an unsupported shape.",
                )
            return document
        finally:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)

    def _run_cli(self, arguments: Sequence[str], operation: str) -> str:
        output = None
        try:
            try:
                if operation == "session-export":
                    output = tempfile.TemporaryFile(mode="w+b")
                result = subprocess.run(
                    [self._executable, *arguments],
                    cwd=self._project_dir,
                    env=self._environment(),
                    check=False,
                    stdout=output if output is not None else subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=output is None,
                    timeout=self._command_timeout,
                )
            except FileNotFoundError as error:
                raise _OpenCodeFailure(
                    "missing-executable", "The OpenCode executable is unavailable."
                ) from error
            except subprocess.TimeoutExpired as error:
                raise _OpenCodeFailure(
                    f"{operation}-timeout",
                    f"The OpenCode {operation} command timed out.",
                ) from error
            except (OSError, UnicodeError) as error:
                raise _OpenCodeFailure(
                    f"{operation}-unavailable",
                    f"The OpenCode {operation} command could not be read.",
                ) from error
            if result.returncode != 0:
                raise _OpenCodeFailure(
                    f"{operation}-failed", f"The OpenCode {operation} command failed."
                )
            if output is None:
                return result.stdout
            output.seek(0)
            raw = output.read(EXPORT_RESPONSE_LIMIT + 1)
            if len(raw) > EXPORT_RESPONSE_LIMIT:
                raise _OpenCodeFailure(
                    f"{operation}-too-large",
                    f"The OpenCode {operation} command exceeded the safe read limit.",
                )
            try:
                return raw.decode("utf-8")
            except UnicodeError as error:
                raise _OpenCodeFailure(
                    f"{operation}-unavailable",
                    f"The OpenCode {operation} command could not be read.",
                ) from error
        finally:
            if output is not None:
                output.close()

    def _decode_checkpoint(
        self,
        checkpoint: AdapterCheckpoint | None,
        warnings: list[AdapterWarning],
    ) -> dict[str, dict[str, str]]:
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
            if not isinstance(payload, dict):
                raise ValueError
            if payload.get("schema_version") == 1:
                self._validated_fingerprints(payload["fingerprints"])
                warnings.append(
                    AdapterWarning(
                        "checkpoint-upgraded",
                        "The legacy OpenCode checkpoint was discarded for a safe worktree-scoped full scan.",
                    )
                )
                return {}
            scopes = payload["scopes"]
            if payload.get("schema_version") != 2 or not isinstance(scopes, dict):
                raise ValueError
            decoded: dict[str, dict[str, str]] = {}
            for scope, fingerprints in scopes.items():
                if (
                    not isinstance(scope, str)
                    or not re.fullmatch(r"[0-9a-f]{64}", scope)
                ):
                    raise ValueError
                decoded[scope] = self._validated_fingerprints(fingerprints)
            return decoded
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            warnings.append(
                AdapterWarning(
                    "checkpoint-invalid",
                    "The checkpoint was invalid; a full scan ran.",
                )
            )
            return {}

    def _validated_fingerprints(self, value: object) -> dict[str, str]:
        if not isinstance(value, dict) or not all(
            isinstance(key, str) and isinstance(fingerprint, str)
            for key, fingerprint in value.items()
        ):
            raise ValueError
        identities = [SessionIdentity.from_canonical(canonical) for canonical in value]
        if any(
            identity.adapter != self.adapter_key
            or identity.source_namespace != self.source_namespace
            for identity in identities
        ):
            raise ValueError
        return value

    def _same_project(self, value: object) -> bool:
        if not isinstance(value, str) or not value:
            return False
        try:
            resolved = Path(value).expanduser().resolve(strict=True)
        except (OSError, ValueError):
            return False
        return resolved == self._project_dir and resolved.is_dir()

    @staticmethod
    def _locator_id(locator: OpaqueSourceLocator) -> str | None:
        if not locator.value.startswith(_LOCATOR_PREFIX):
            return None
        native_id = locator.value[len(_LOCATOR_PREFIX) :]
        return native_id if _SESSION_ID.fullmatch(native_id) else None

    @staticmethod
    def _nonnegative_integer(value: object) -> bool:
        return type(value) is int and value >= 0

    @classmethod
    def _milliseconds(cls, value: object) -> datetime | None:
        if not cls._nonnegative_integer(value):
            return None
        try:
            return datetime.fromtimestamp(value / 1000, timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None

    @staticmethod
    def _available_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            return int(listener.getsockname()[1])

    @staticmethod
    def _scan_unavailable(error: _OpenCodeFailure) -> ScanBatch:
        return ScanBatch(
            status=BatchStatus.UNAVAILABLE,
            warnings=(AdapterWarning(error.code, str(error)),),
        )

    @staticmethod
    def _unavailable(
        identity: SessionIdentity, code: str, message: str
    ) -> TurnBatch:
        return TurnBatch(
            identity=identity,
            status=BatchStatus.UNAVAILABLE,
            warnings=(AdapterWarning(code, message, identity),),
        )
