"""Pure deterministic allocation and rendering for multi-source Context Packs."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, replace

from tang.adapters import SourceRecord, TurnBatch, TurnRole
from tang.context import ContextExcerpt, ContextPackBuilder, UNTRUSTED_NOTICE

_GOAL_ENVELOPE = re.compile(
    r"<timestamp>.*?</timestamp>\s*|<user_query>\s*|</user_query>",
    re.DOTALL | re.IGNORECASE,
)


def _normalize_goal(text: str) -> str:
    """Strip known host envelope tags only; not semantic equivalence."""
    stripped = _GOAL_ENVELOPE.sub("", text)
    return " ".join(stripped.split()).casefold()


def constraint_signals(
    sources: tuple[ValidatedSourceRead, ...],
) -> tuple[dict[str, object], ...]:
    """Deterministic hints when first visible user goals disagree across sources."""

    goals: list[dict[str, str]] = []
    for item in sources:
        for turn in item.read.turns:
            if turn.role is not TurnRole.USER or not turn.text.strip():
                continue
            goals.append(
                {
                    "harness": item.source.identity.adapter,
                    "normalized_goal": _normalize_goal(turn.text),
                    "source_id": item.source.identity.canonical,
                    "turn_locator": turn.citation_locator,
                }
            )
            break
    if len(goals) < 2:
        return ()
    norms = {entry["normalized_goal"] for entry in goals}
    if len(norms) <= 1:
        return ()
    public = tuple(
        {
            "harness": entry["harness"],
            "source_id": entry["source_id"],
            "turn_locator": entry["turn_locator"],
        }
        for entry in sorted(goals, key=lambda row: row["source_id"])
    )
    return (
        {
            "kind": "first_user_goal_mismatch",
            "sources": public,
        },
    )


CONFLICT_WARNING = (
    "Recovered sources disagree on the first visible user goal; name the "
    "conflict in the Continuation Brief and ask which constraint to follow "
    "before acting."
)

# Pack-level warnings in this set do not downgrade status from complete reads.
NON_DEGRADING_PACK_WARNINGS = frozenset({CONFLICT_WARNING})


def _indented(text: str) -> list[str]:
    return [f"    {line}" for line in text.splitlines() or [""]]


@dataclass(frozen=True, slots=True)
class ValidatedSourceRead:
    """A source/read pair already authorized for one resolved project."""

    source: SourceRecord
    read: TurnBatch
    project_key: str

    def __post_init__(self) -> None:
        if self.source.identity != self.read.identity:
            raise ValueError("validated source and read identities must match")
        if not self.project_key:
            raise ValueError("validated source requires a project key")


@dataclass(frozen=True, slots=True)
class SourceSection:
    source_id: str
    harness: str
    native_session_id: str
    source_title: str | None
    read_status: str
    excerpts: tuple[ContextExcerpt, ...]
    warnings: tuple[str, ...]
    omitted_turns: int
    redaction_count: int

    def as_dict(self) -> dict[str, object]:
        return {
            "excerpts": [excerpt.as_dict() for excerpt in self.excerpts],
            "harness": self.harness,
            "native_session_id": self.native_session_id,
            "omitted_turns": self.omitted_turns,
            "read_status": self.read_status,
            "redaction_count": self.redaction_count,
            "source_id": self.source_id,
            "source_title": self.source_title,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class MultiSourceContextPack:
    project_key: str
    sections: tuple[SourceSection, ...]
    warnings: tuple[str, ...] = ()
    constraint_signals: tuple[dict[str, object], ...] = ()
    markdown_estimated_tokens: int = 0
    json_estimated_tokens: int = 0
    schema_version: int = 1

    @property
    def estimated_tokens(self) -> int:
        return max(self.markdown_estimated_tokens, self.json_estimated_tokens)

    @property
    def status(self) -> str:
        if any(section.read_status != "complete" for section in self.sections):
            return "partial"
        if any(
            warning not in NON_DEGRADING_PACK_WARNINGS for warning in self.warnings
        ):
            return "partial"
        return "complete"

    def as_dict(self) -> dict[str, object]:
        document: dict[str, object] = {
            "estimated_tokens": self.json_estimated_tokens,
            "project_key": self.project_key,
            "schema_version": self.schema_version,
            "status": self.status,
            "warnings": list(self.warnings),
            "untrusted_data_envelope": {
                "notice": UNTRUSTED_NOTICE,
                "sources": [section.as_dict() for section in self.sections],
            },
        }
        if self.constraint_signals:
            document["constraint_signals"] = list(self.constraint_signals)
        return document

    def to_json(self) -> str:
        return json.dumps(
            self.as_dict(), ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"

    def to_markdown(self) -> str:
        lines = [
            "# Tang Multi-Source Context Pack",
            "",
            f"- Schema version: {self.schema_version}",
            f"- Project key: `{self.project_key}`",
            (
                f"- Estimated tokens: {self.markdown_estimated_tokens} "
                "(Unicode characters / 4)"
            ),
            f"- Sources: {len(self.sections)}",
            f"- Status: {self.status}",
            "",
            "## Safety envelope",
            "",
            f"> {UNTRUSTED_NOTICE}",
            "",
            "## Untrusted historical evidence",
            "",
        ]
        if self.warnings:
            lines.append("Pack warnings (untrusted):")
            for warning in self.warnings:
                lines.extend(_indented(warning))
            lines.append("")
        if self.constraint_signals:
            lines.append("Constraint signals (deterministic, non-authoritative):")
            for signal in self.constraint_signals:
                lines.extend(_indented(json.dumps(signal, sort_keys=True)))
            lines.append("")
        for section in self.sections:
            lines.extend(
                [
                    f"### Source `{section.source_id}`",
                    "",
                    f"- Harness: {section.harness}",
                    f"- Read status: {section.read_status}",
                    f"- Omitted visible turns: {section.omitted_turns}",
                    "",
                ]
            )
            if section.source_title:
                lines.extend(
                    ["Title (untrusted):", *_indented(section.source_title), ""]
                )
            for excerpt in section.excerpts:
                citation = json.dumps(
                    excerpt.citation.as_dict(),
                    ensure_ascii=False,
                    sort_keys=True,
                )
                lines.extend(
                    [
                        f"#### Turn {excerpt.ordinal} · {excerpt.role}",
                        "",
                        "Citation (untrusted locator data):",
                        f"    {citation}",
                        "",
                        *[f"    {line}" for line in excerpt.text.splitlines()],
                        "",
                    ]
                )
            lines.append("Warnings (untrusted):")
            if section.warnings:
                for warning in section.warnings:
                    lines.extend(_indented(warning))
            else:
                lines.append("    None")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


class MultiSourceAllocator:
    def __init__(self, *, token_budget: int = 2_000) -> None:
        if token_budget < 512:
            raise ValueError("multi-source token budget must be at least 512")
        self._token_budget = token_budget
        self._single = ContextPackBuilder(
            token_budget=2_000, max_excerpt_characters=1_200
        )

    def allocate(
        self,
        sources: tuple[ValidatedSourceRead, ...],
        project_key: str,
        *,
        warnings: tuple[str, ...] = (),
    ) -> MultiSourceContextPack:
        if not sources:
            raise ValueError("multi-source allocation requires at least one source")
        ordered = tuple(sorted(sources, key=lambda item: item.source.identity.canonical))
        identities = [item.source.identity for item in ordered]
        if len(set(identities)) != len(identities):
            raise ValueError("multi-source allocation rejects duplicate sources")
        if any(item.project_key != project_key for item in ordered):
            raise ValueError("all sources must be validated for the active project")

        prepared = [self._single.build(item.source, item.read) for item in ordered]
        selected: list[list[ContextExcerpt]] = [[] for _ in ordered]
        signals = constraint_signals(ordered)
        pack_warnings = (
            warnings + (CONFLICT_WARNING,) if signals else warnings
        )

        # Reserve one newest cited excerpt per source before filling any source.
        for index, single in enumerate(prepared):
            selected[index].append(single.excerpts[-1])
        if (
            self._pack(
                ordered,
                prepared,
                selected,
                project_key,
                pack_warnings,
                signals,
            ).estimated_tokens
            > self._token_budget
            and not self._fit_reserves(
                ordered,
                prepared,
                selected,
                project_key,
                pack_warnings,
                signals,
            )
        ):
            raise ValueError("source metadata leaves no fair excerpt reserve")

        queues = [list(reversed(single.excerpts[:-1])) for single in prepared]
        while any(queues):
            for index, queue in enumerate(queues):
                if not queue:
                    continue
                excerpt = queue.pop(0)
                selected[index].append(excerpt)
                selected[index].sort(key=lambda item: item.ordinal)
                candidate = self._pack(
                    ordered,
                    prepared,
                    selected,
                    project_key,
                    pack_warnings,
                    signals,
                )
                if candidate.estimated_tokens > self._token_budget:
                    selected[index].remove(excerpt)
        return self._pack(
            ordered,
            prepared,
            selected,
            project_key,
            pack_warnings,
            signals,
        )

    def _fit_reserves(
        self,
        sources: tuple[ValidatedSourceRead, ...],
        prepared,
        selected: list[list[ContextExcerpt]],
        project_key: str,
        warnings: tuple[str, ...],
        signals: tuple[dict[str, object], ...] = (),
    ) -> bool:
        originals = [chosen[-1] for chosen in selected]
        marker = "\n\n[Excerpt truncated]"
        low, high = 1, max(len(excerpt.text) for excerpt in originals)
        fitted: list[ContextExcerpt] | None = None
        while low <= high:
            keep = (low + high) // 2
            candidates = [
                replace(
                    excerpt,
                    text=(
                        excerpt.text
                        if len(excerpt.text) <= keep
                        else excerpt.text[:keep].rstrip() + marker
                    ),
                    truncated=excerpt.truncated or len(excerpt.text) > keep,
                )
                for excerpt in originals
            ]
            for index, candidate in enumerate(candidates):
                selected[index][-1] = candidate
            pack = self._pack(
                sources, prepared, selected, project_key, warnings, signals
            )
            if pack.estimated_tokens <= self._token_budget:
                fitted = candidates
                low = keep + 1
            else:
                high = keep - 1
        if fitted is None:
            for index, excerpt in enumerate(originals):
                selected[index][-1] = excerpt
            return False
        for index, excerpt in enumerate(fitted):
            selected[index][-1] = excerpt
        return True

    def _pack(
        self,
        sources: tuple[ValidatedSourceRead, ...],
        prepared,
        selected: list[list[ContextExcerpt]],
        project_key: str,
        warnings: tuple[str, ...],
        signals: tuple[dict[str, object], ...] = (),
    ) -> MultiSourceContextPack:
        sections = tuple(
            SourceSection(
                source_id=item.source.identity.canonical,
                harness=item.source.identity.adapter,
                native_session_id=item.source.identity.native_id,
                source_title=single.source_title,
                read_status=item.read.status.value,
                excerpts=tuple(sorted(chosen, key=lambda excerpt: excerpt.ordinal)),
                warnings=single.warnings,
                omitted_turns=len(item.read.turns) - len(chosen),
                redaction_count=single.redaction_count,
            )
            for item, single, chosen in zip(sources, prepared, selected)
        )
        return self._estimated(
            MultiSourceContextPack(
                project_key, sections, warnings, signals
            )
        )

    @staticmethod
    def _estimated(pack: MultiSourceContextPack) -> MultiSourceContextPack:
        markdown = json_estimate = 0
        for _ in range(12):
            candidate = replace(
                pack,
                markdown_estimated_tokens=markdown,
                json_estimated_tokens=json_estimate,
            )
            next_markdown = math.ceil(len(candidate.to_markdown()) / 4)
            next_json = math.ceil(len(candidate.to_json()) / 4)
            if (next_markdown, next_json) == (markdown, json_estimate):
                return candidate
            markdown, json_estimate = next_markdown, next_json
        return replace(
            pack,
            markdown_estimated_tokens=markdown,
            json_estimated_tokens=json_estimate,
        )
