"""Current-project indexing coordinator over adapters and repositories."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone

from tang.adapters import (
    AdapterWarning,
    BatchStatus,
    SessionAdapter,
    SourceRecord,
    TurnSelection,
)
from tang.capsule import DiscoveryCapsuleBuilder
from tang.index_catalog import IndexCatalog, IndexWriteBatch
from tang.project import ProjectIdentity, ProjectResolutionError, resolve_project
from tang.repository import StoredCapsule, TangRepository
from tang.target import TargetCandidate


@dataclass(frozen=True, slots=True)
class IndexWarning:
    code: str
    message: str = field(repr=False)
    source_id: str | None = None


@dataclass(frozen=True, slots=True)
class IndexDiagnostic:
    """A visible store-wide issue proven not to affect this project."""

    code: str
    message: str = field(repr=False)
    scope: str

    def __post_init__(self) -> None:
        if self.scope != "foreign":
            raise ValueError("only foreign diagnostics are non-impacting")


@dataclass(frozen=True, slots=True)
class IndexResult:
    indexed: int
    deleted: int
    unchanged: int
    excluded: int
    warnings: tuple[IndexWarning, ...]
    diagnostics: tuple[IndexDiagnostic, ...] = ()
    refreshed: int = 0

    @property
    def status(self) -> str:
        return "partial" if self.warnings else "complete"


class ProjectIndexer:
    def __init__(
        self,
        repository: TangRepository,
        *,
        capsule_builder: DiscoveryCapsuleBuilder | None = None,
    ) -> None:
        self._repository = repository
        self._capsules = capsule_builder or DiscoveryCapsuleBuilder()
        self._catalog = IndexCatalog(repository)

    @staticmethod
    def _is_proven_foreign_warning(
        warning: AdapterWarning,
        record_scopes: dict[str, str],
        active_project: ProjectIdentity,
    ) -> bool:
        """Downgrade only warnings tied to one resolvable foreign source."""

        if warning.code == "duplicate-session-id":
            # A duplicate identity can represent a second, differently scoped
            # native file, so a single record's project hint is insufficient.
            return False
        if warning.identity is not None:
            scope = record_scopes.get(warning.identity.canonical)
            if scope is not None:
                return scope == "foreign"
        if warning.project_hint is None:
            return False
        try:
            return resolve_project(warning.project_hint).key != active_project.key
        except (OSError, ValueError, ProjectResolutionError):
            return False

    def index(
        self,
        adapters: tuple[SessionAdapter, ...],
        active_project: ProjectIdentity,
        *,
        now: datetime | None = None,
    ) -> IndexResult:
        indexed = deleted = unchanged = excluded = refreshed_count = 0
        warnings: list[IndexWarning] = []
        diagnostics: list[IndexDiagnostic] = []
        timestamp = now or datetime.now(timezone.utc)

        # Existing Capsule labels are already redacted, bounded, and persisted.
        # Refresh their current algorithm before deriving session titles from
        # them, so one transaction has one authoritative label source.
        with self._repository.transaction():
            for session in self._repository.sessions_for_project(active_project.key):
                capsule = self._repository.get_capsule(session.source.identity.canonical)
                if capsule is None:
                    continue
                if not self._capsules.needs_label_refresh(capsule):
                    continue
                refreshed_capsule = self._capsules.refresh_display_label(capsule)
                if refreshed_capsule is None:
                    continue
                self._repository.put_capsule(refreshed_capsule)
                if not isinstance(capsule.content.get("source_title"), str):
                    self._repository.set_derived_title(
                        refreshed_capsule.source_id,
                        str(refreshed_capsule.content["display_name"]),
                    )
                refreshed_count += 1
            self._repository.backfill_untitled_sessions(active_project.key)

        for adapter in adapters:
            prior_checkpoint = self._repository.get_checkpoint(
                adapter.adapter_key, adapter.source_namespace, active_project.key
            )
            scan = adapter.scan(prior_checkpoint)
            pending: list[tuple[SourceRecord, StoredCapsule]] = []
            checkpoint_safe = True
            record_scopes: dict[str, str] = {}
            eligible_sources: list[SourceRecord] = []
            for source in scan.records:
                try:
                    candidate = TargetCandidate.from_source(source)
                except (OSError, ValueError, ProjectResolutionError):
                    warnings.append(
                        IndexWarning(
                            "project-hint-unavailable",
                            "A changed session project hint could not be resolved and was skipped.",
                            source.identity.canonical,
                        )
                    )
                    checkpoint_safe = False
                    continue
                if candidate.project_key != active_project.key:
                    record_scopes[source.identity.canonical] = "foreign"
                    excluded += 1
                    continue
                record_scopes[source.identity.canonical] = "current"
                eligible_sources.append(source)

            for warning in scan.warnings:
                source_id = warning.identity.canonical if warning.identity else None
                if self._is_proven_foreign_warning(
                    warning, record_scopes, active_project
                ):
                    diagnostics.append(
                        IndexDiagnostic(warning.code, warning.message, "foreign")
                    )
                    continue
                warnings.append(IndexWarning(warning.code, warning.message, source_id))

            for source in eligible_sources:
                stored_fingerprint = self._repository.fingerprint_for(
                    source.identity.canonical
                )
                existing_capsule = self._repository.get_capsule(
                    source.identity.canonical
                )
                if (
                    stored_fingerprint == source.fingerprint
                    and not self._capsules.needs_label_refresh(existing_capsule)
                ):
                    unchanged += 1
                    continue
                read = adapter.read(source, TurnSelection())
                warnings.extend(
                    IndexWarning(
                        warning.code, warning.message, source.identity.canonical
                    )
                    for warning in read.warnings
                )
                if read.status is BatchStatus.UNAVAILABLE or not read.turns:
                    warnings.append(
                        IndexWarning(
                            "session-not-indexed",
                            "A changed session had no readable visible turns and was skipped.",
                            source.identity.canonical,
                        )
                    )
                    # This source was positively resolved to the active project.
                    # Advancing the fingerprint cursor prevents one poison record
                    # from forcing full rescans forever; any native content change
                    # changes the fingerprint and makes it eligible for retry.
                    continue
                source = replace(source, header=source.header.merged_with(read.header))
                try:
                    capsule = self._capsules.build(source, read, active_project.key)
                except ValueError:
                    warnings.append(
                        IndexWarning(
                            "capsule-not-built",
                            "A changed session could not produce a bounded capsule and was skipped.",
                            source.identity.canonical,
                        )
                    )
                    # As above, retain the warning for this attempt but allow the
                    # adapter cursor to advance until the native source changes.
                    continue
                derived_title = capsule.content.get("display_name")
                pending.append(
                    (
                        replace(source, title=derived_title)
                        if (
                            (not source.title or not source.title.strip())
                            and isinstance(derived_title, str)
                            and derived_title.strip()
                        )
                        else source,
                        capsule,
                    )
                )

            checkpoint_changed = (
                scan.next_checkpoint is not None
                and scan.next_checkpoint != prior_checkpoint
                and checkpoint_safe
            )
            removable = tuple(
                identity
                for identity in scan.removed
                if (
                    (stored := self._repository.get_session(identity.canonical))
                    is not None
                    and stored.project_key == active_project.key
                )
            )
            if pending or removable or checkpoint_changed:
                self._catalog.commit(
                    IndexWriteBatch(
                        tuple(pending),
                        removable,
                        scan.next_checkpoint,
                        checkpoint_changed,
                        active_project.key,
                        timestamp,
                    )
                )
                indexed += len(pending)
                deleted += len(removable)

        return IndexResult(
            indexed,
            deleted,
            unchanged,
            excluded,
            tuple(warnings),
            tuple(diagnostics),
            refreshed_count,
        )
