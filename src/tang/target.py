"""Conservative current-target resolution for supported host harnesses."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
import re
from pathlib import Path
from typing import Literal

from tang.adapters import (
    SessionHealth,
    SessionIdentity,
    SourceFingerprint,
    SourceRecord,
)
from tang.project import ProjectIdentity, ProjectResolutionError, resolve_project
from tang.repository import StoredSession


class TargetResolutionKind(StrEnum):
    RESOLVED = "resolved"
    CONFIRMATION_REQUIRED = "confirmation_required"
    UNAVAILABLE = "unavailable"


class TargetResolutionCode(StrEnum):
    """Stable, path-safe classifications for target-resolution outcomes."""

    UNIQUE_CANDIDATE = "unique-candidate"
    HOST_ID_MATCH = "host-id-match"
    EXPLICIT_CONFIRMATION = "explicit-confirmation"
    NO_ELIGIBLE_TARGET = "no-eligible-target"
    HOST_ID_UNKNOWN = "host-id-unknown"
    AMBIGUOUS_TARGET = "ambiguous-target"
    FOREIGN_PROJECT = "foreign-project"
    SELECTED_SOURCE = "selected-source"
    UNAVAILABLE_TARGET = "unavailable-target"
    STALE_INDEX = "stale-index"


class HostTargetContextError(ValueError):
    """A fixed-class refusal for malformed or inconsistent private context."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


_OPENCODE_SESSION_ID = re.compile(r"ses_[A-Za-z0-9_-]{1,128}\Z")


@dataclass(frozen=True, slots=True)
class OpenCodeTargetContext:
    """Verified, path-safe evidence derived from one OpenCode tool invocation."""

    project_key: str
    native_session_id: str = field(repr=False)
    observed_fingerprint: SourceFingerprint = field(repr=False)

    @classmethod
    def from_host(
        cls,
        *,
        session_id: str,
        directory: Path | str,
        worktree: Path | str,
        observed_source: SourceRecord,
    ) -> OpenCodeTargetContext:
        """Validate exact host metadata against a freshly observed source record."""

        if not isinstance(session_id, str) or not _OPENCODE_SESSION_ID.fullmatch(
            session_id
        ):
            raise HostTargetContextError(
                "malformed-host-context",
                "OpenCode host target context is incomplete or malformed.",
            )
        if (
            observed_source.identity.adapter != "opencode"
            or observed_source.identity.native_id != session_id
        ):
            raise HostTargetContextError(
                "host-source-mismatch",
                "OpenCode host identity does not match the observed session.",
            )
        try:
            directory_path = Path(directory).expanduser().resolve(strict=True)
            worktree_path = Path(worktree).expanduser().resolve(strict=True)
            directory_project = resolve_project(directory)
            worktree_project = resolve_project(worktree)
            source_project = resolve_project(observed_source.project_hint)
        except (OSError, TypeError, ValueError, ProjectResolutionError) as error:
            raise HostTargetContextError(
                "malformed-host-context",
                "OpenCode host target context is incomplete or unusable.",
            ) from error
        worktree_contains_directory = directory_path.is_relative_to(worktree_path)
        shared_git_project = worktree_project.key == directory_project.key
        if (
            source_project.key != directory_project.key
            or not (worktree_contains_directory or shared_git_project)
        ):
            raise HostTargetContextError(
                "host-project-mismatch",
                "OpenCode host and observed session projects do not match.",
            )
        return cls(
            project_key=directory_project.key,
            native_session_id=session_id,
            observed_fingerprint=observed_source.fingerprint,
        )


@dataclass(frozen=True, slots=True)
class TargetCandidate:
    """Only path-safe data needed to rank and present a possible target."""

    identity: SessionIdentity
    project_key: str
    updated_at: datetime
    health: SessionHealth
    fingerprint: SourceFingerprint = field(repr=False)
    native_available: bool = True

    @classmethod
    def from_source(cls, source: SourceRecord) -> TargetCandidate:
        project = resolve_project(source.project_hint)
        return cls(
            identity=source.identity,
            project_key=project.key,
            updated_at=source.updated_at,
            health=source.health,
            fingerprint=source.fingerprint,
        )

    @classmethod
    def from_stored(cls, session: StoredSession) -> TargetCandidate:
        return cls(
            identity=session.source.identity,
            project_key=session.project_key,
            updated_at=session.source.updated_at,
            health=session.source.health,
            fingerprint=session.source.fingerprint,
            native_available=session.native_available,
        )


@dataclass(frozen=True, slots=True)
class CandidateWarning:
    """Path-safe evidence that one native project hint was unusable."""

    code: str
    identity: SessionIdentity
    message: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class CandidateDiscovery:
    candidates: tuple[TargetCandidate, ...]
    warnings: tuple[CandidateWarning, ...]


def candidates_for_project(
    records: tuple[SourceRecord, ...], active_project: ProjectIdentity
) -> CandidateDiscovery:
    """Resolve native project hints and retain only active-project Codex records."""

    candidates: list[TargetCandidate] = []
    warnings: list[CandidateWarning] = []
    for source in sorted(records, key=lambda item: item.identity.canonical):
        if source.identity.adapter != "codex":
            continue
        try:
            candidate = TargetCandidate.from_source(source)
        except (OSError, ValueError, ProjectResolutionError):
            warnings.append(
                CandidateWarning(
                    "project-hint-unavailable",
                    source.identity,
                    "A Codex session project hint could not be resolved and was skipped.",
                )
            )
            continue
        if candidate.project_key == active_project.key:
            candidates.append(candidate)
    return CandidateDiscovery(tuple(candidates), tuple(warnings))


@dataclass(frozen=True, slots=True)
class TargetResolution:
    kind: TargetResolutionKind
    code: TargetResolutionCode
    candidates: tuple[TargetCandidate, ...]
    target: TargetCandidate | None
    reason: str

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("target resolution requires a qualified reason")
        if self.kind is TargetResolutionKind.RESOLVED:
            if self.target is None or self.target not in self.candidates:
                raise ValueError("a resolved target must be one of the candidates")
        elif self.target is not None:
            raise ValueError("unresolved target results cannot select a candidate")

    def as_document(self) -> dict[str, object]:
        """Return a deterministic JSON-ready summary without private identities."""

        return {
            "candidate_count": len(self.candidates),
            "code": self.code.value,
            "kind": self.kind.value,
            "reason": self.reason,
            "schema_version": 1,
        }


def _rank(candidate: TargetCandidate) -> tuple[float, str]:
    return (-candidate.updated_at.timestamp(), candidate.identity.canonical)


def resolve_current_target(
    candidates: tuple[TargetCandidate, ...],
    active_project: ProjectIdentity,
    *,
    current_native_id: str | None = None,
    exclude: frozenset[SessionIdentity] = frozenset(),
) -> TargetResolution:
    """Resolve only unique or native-identified targets; never infer from recency."""

    eligible = tuple(
        sorted(
            (
                candidate
                for candidate in candidates
                if candidate.identity.adapter == "codex"
                and candidate.project_key == active_project.key
                and candidate.native_available
                and candidate.identity not in exclude
            ),
            key=_rank,
        )
    )
    if not eligible:
        return TargetResolution(
            TargetResolutionKind.UNAVAILABLE,
            TargetResolutionCode.NO_ELIGIBLE_TARGET,
            (),
            None,
            "No eligible Codex session is known for the active project.",
        )

    if current_native_id is not None:
        matched = tuple(
            candidate
            for candidate in eligible
            if candidate.identity.native_id == current_native_id
        )
        if len(matched) == 1:
            return TargetResolution(
                TargetResolutionKind.RESOLVED,
                TargetResolutionCode.HOST_ID_MATCH,
                eligible,
                matched[0],
                "The host supplied a unique native Codex session ID for this project.",
            )
        return TargetResolution(
            TargetResolutionKind.CONFIRMATION_REQUIRED,
            TargetResolutionCode.HOST_ID_UNKNOWN,
            eligible,
            None,
            "The supplied native session ID did not identify one eligible target; choose explicitly.",
        )

    if len(eligible) == 1:
        return TargetResolution(
            TargetResolutionKind.RESOLVED,
            TargetResolutionCode.UNIQUE_CANDIDATE,
            eligible,
            eligible[0],
            "Exactly one eligible Codex session exists for the active project.",
        )

    return TargetResolution(
        TargetResolutionKind.CONFIRMATION_REQUIRED,
        TargetResolutionCode.AMBIGUOUS_TARGET,
        eligible,
        None,
        "Several eligible Codex sessions exist; recency alone is weak evidence, so choose explicitly.",
    )


def confirm_target(
    resolution: TargetResolution, chosen: SessionIdentity
) -> TargetResolution:
    """Apply an explicit user choice without expanding the offered candidate set."""

    if resolution.kind is not TargetResolutionKind.CONFIRMATION_REQUIRED:
        raise ValueError("only a confirmation-required result can be confirmed")
    matches = tuple(
        candidate for candidate in resolution.candidates if candidate.identity == chosen
    )
    if len(matches) != 1:
        raise ValueError("chosen target is not an offered candidate")
    return TargetResolution(
        TargetResolutionKind.RESOLVED,
        TargetResolutionCode.EXPLICIT_CONFIRMATION,
        resolution.candidates,
        matches[0],
        "The target was selected explicitly from the eligible candidates.",
    )


def _opencode_refusal(
    code: TargetResolutionCode,
    reason: str,
    candidates: tuple[TargetCandidate, ...] = (),
) -> TargetResolution:
    return TargetResolution(
        TargetResolutionKind.UNAVAILABLE,
        code,
        candidates,
        None,
        reason,
    )


def resolve_opencode_target(
    sessions: tuple[StoredSession, ...],
    active_project: ProjectIdentity,
    context: OpenCodeTargetContext,
    *,
    exclude: frozenset[SessionIdentity] = frozenset(),
) -> TargetResolution:
    """Require an exact, fresh OpenCode host match and explicit confirmation."""

    if context.project_key != active_project.key:
        return _opencode_refusal(
            TargetResolutionCode.FOREIGN_PROJECT,
            "The active OpenCode host belongs to a different project.",
        )

    matches = tuple(
        sorted(
            (
                TargetCandidate.from_stored(session)
                for session in sessions
                if session.source.identity.adapter == "opencode"
                and session.project_key == active_project.key
                and session.source.identity.native_id == context.native_session_id
            ),
            key=_rank,
        )
    )
    if not matches:
        return _opencode_refusal(
            TargetResolutionCode.NO_ELIGIBLE_TARGET,
            "The active OpenCode session is not indexed for this project.",
        )
    if len(matches) != 1:
        return _opencode_refusal(
            TargetResolutionCode.AMBIGUOUS_TARGET,
            "The OpenCode host identity matched more than one indexed session.",
            matches,
        )

    candidate = matches[0]
    if candidate.identity in exclude:
        return _opencode_refusal(
            TargetResolutionCode.SELECTED_SOURCE,
            "The active OpenCode destination cannot also be a selected source.",
            matches,
        )
    if not candidate.native_available:
        return _opencode_refusal(
            TargetResolutionCode.UNAVAILABLE_TARGET,
            "The active OpenCode session is no longer available natively.",
            matches,
        )
    if candidate.fingerprint != context.observed_fingerprint:
        return _opencode_refusal(
            TargetResolutionCode.STALE_INDEX,
            "The indexed OpenCode session is stale; refresh the project index.",
            matches,
        )
    return TargetResolution(
        TargetResolutionKind.CONFIRMATION_REQUIRED,
        TargetResolutionCode.HOST_ID_MATCH,
        matches,
        None,
        "The host identified one exact OpenCode target; confirm it explicitly.",
    )


DestinationHarness = Literal["codex", "opencode"]


def resolve_destination_target(
    harness: DestinationHarness,
    active_project: ProjectIdentity,
    *,
    sessions: tuple[StoredSession, ...],
    current_native_id: str | None = None,
    opencode_context: OpenCodeTargetContext | None = None,
    exclude: frozenset[SessionIdentity] = frozenset(),
) -> TargetResolution:
    """One entry for Codex and OpenCode current-target resolution."""

    if harness == "codex":
        candidates = tuple(
            TargetCandidate.from_stored(session)
            for session in sessions
            if session.source.identity.adapter == "codex"
            and session.project_key == active_project.key
        )
        return resolve_current_target(
            candidates,
            active_project,
            current_native_id=current_native_id,
            exclude=exclude,
        )
    if harness == "opencode":
        if opencode_context is None:
            raise ValueError("OpenCode target resolution requires host context")
        return resolve_opencode_target(
            sessions,
            active_project,
            opencode_context,
            exclude=exclude,
        )
    raise ValueError(f"unsupported destination harness: {harness!r}")
