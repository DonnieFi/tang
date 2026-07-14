"""Conservative, reusable current-Codex-target resolution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from tang.adapters import SessionHealth, SessionIdentity, SourceRecord
from tang.project import ProjectIdentity


class TargetResolutionKind(StrEnum):
    RESOLVED = "resolved"
    CONFIRMATION_REQUIRED = "confirmation_required"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class TargetCandidate:
    """Only path-safe data needed to rank and present a possible target."""

    identity: SessionIdentity
    project_key: str
    updated_at: datetime
    health: SessionHealth

    @classmethod
    def from_source(
        cls, source: SourceRecord, project: ProjectIdentity
    ) -> TargetCandidate:
        return cls(
            identity=source.identity,
            project_key=project.key,
            updated_at=source.updated_at,
            health=source.health,
        )


@dataclass(frozen=True, slots=True)
class TargetResolution:
    kind: TargetResolutionKind
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
                and candidate.identity not in exclude
            ),
            key=_rank,
        )
    )
    if not eligible:
        return TargetResolution(
            TargetResolutionKind.UNAVAILABLE,
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
                eligible,
                matched[0],
                "The host supplied a unique native Codex session ID for this project.",
            )
        return TargetResolution(
            TargetResolutionKind.CONFIRMATION_REQUIRED,
            eligible,
            None,
            "The supplied native session ID did not identify one eligible target; choose explicitly.",
        )

    if len(eligible) == 1:
        return TargetResolution(
            TargetResolutionKind.RESOLVED,
            eligible,
            eligible[0],
            "Exactly one eligible Codex session exists for the active project.",
        )

    return TargetResolution(
        TargetResolutionKind.CONFIRMATION_REQUIRED,
        eligible,
        None,
        "Several eligible Codex sessions exist; recency alone is weak evidence, so choose explicitly.",
    )


def confirm_target(
    resolution: TargetResolution, chosen: SessionIdentity
) -> TargetResolution:
    """Apply an explicit user choice without expanding the offered candidate set."""

    matches = tuple(
        candidate for candidate in resolution.candidates if candidate.identity == chosen
    )
    if len(matches) != 1:
        raise ValueError("chosen target is not an offered candidate")
    return TargetResolution(
        TargetResolutionKind.RESOLVED,
        resolution.candidates,
        matches[0],
        "The target was selected explicitly from the eligible candidates.",
    )
