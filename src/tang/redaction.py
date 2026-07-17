"""Deterministic best-effort redaction shared by every sensitive seam.

Redaction reduces accidental disclosure. It is not encryption, does not erase
source data, and cannot guarantee detection of novel or intentionally obfuscated
secrets. Forbidden native content is excluded before this service sees text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, Pattern


Replacement = str | Callable[[re.Match[str]], str]
TITLE_CHARACTER_LIMIT = 256


class RedactionSeam(StrEnum):
    CAPSULE_PERSISTENCE = "capsule_persistence"
    SNIPPET_DISPLAY = "snippet_display"
    CONTEXT_REREAD = "context_reread"
    GRAPH_LABEL = "graph_label"
    SKILL_EVIDENCE = "skill_evidence"


class ContentKind(StrEnum):
    TITLE = "title"
    VISIBLE_TEXT = "visible_text"
    CITATION = "citation"
    WARNING = "warning"
    DISPLAY_METADATA = "display_metadata"
    SYSTEM_PROMPT = "system_prompt"
    HIDDEN_REASONING = "hidden_reasoning"
    TOOL_PAYLOAD = "tool_payload"
    TOOL_RESULT = "tool_result"
    FILE_BODY = "file_body"


FORBIDDEN_CONTENT_KINDS = frozenset(
    {
        ContentKind.SYSTEM_PROMPT,
        ContentKind.HIDDEN_REASONING,
        ContentKind.TOOL_PAYLOAD,
        ContentKind.TOOL_RESULT,
        ContentKind.FILE_BODY,
    }
)


@dataclass(frozen=True, slots=True)
class RedactionResult:
    text: str
    redaction_count: int
    labels: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Rule:
    label: str
    pattern: Pattern[str]
    replacement: Replacement


def _credential_assignment(match: re.Match[str]) -> str:
    return f"{match.group('name')}=[REDACTED:credential]"


def _uri_userinfo(match: re.Match[str]) -> str:
    return f"{match.group('scheme')}{match.group('user')}:[REDACTED:password]@"


DEFAULT_RULES = (
    _Rule(
        "private-key",
        re.compile(
            r"-----BEGIN [^-\r\n]*PRIVATE KEY-----.*?"
            r"-----END [^-\r\n]*PRIVATE KEY-----",
            re.DOTALL,
        ),
        "[REDACTED:private-key]",
    ),
    _Rule(
        "bearer-token",
        re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
        "Bearer [REDACTED:token]",
    ),
    _Rule(
        "known-token",
        re.compile(
            r"\b(?:AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|"
            r"github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{16,}|"
            r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\."
            r"[A-Za-z0-9_-]{8,})\b"
        ),
        "[REDACTED:token]",
    ),
    _Rule(
        "credential-assignment",
        re.compile(
            r"(?i)\b(?P<name>(?:API_KEY|ACCESS_KEY|SECRET_KEY|CLIENT_SECRET|"
            r"AUTH_TOKEN|TOKEN|PASSWORD|PASSWD|[A-Z][A-Z0-9_]+_"
            r"(?:KEY|TOKEN|SECRET|PASSWORD)))\s*[:=]\s*"
            r"(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\s,;}]+)"
        ),
        _credential_assignment,
    ),
    _Rule(
        "uri-password",
        re.compile(
            r"(?P<scheme>https?://)(?P<user>[^:/\s]+):[^@/\s]+@",
            re.IGNORECASE,
        ),
        _uri_userinfo,
    ),
    _Rule(
        "home-path",
        re.compile(
            r"(?<![A-Za-z0-9])(?:/(?:home|Users)/[^/\s]+|/root\b|"
            r"[A-Za-z]:[\\/]Users[\\/][^\\/\s]+)",
            re.IGNORECASE,
        ),
        "~",
    ),
)


_NATIVE_SESSION_UUID = re.compile(
    r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}(?![0-9A-Fa-f])"
)
_OPENCODE_SESSION_ID = re.compile(r"(?<![A-Za-z0-9_])ses_[A-Za-z0-9_-]+")


class Redactor:
    """Apply a stable ordered corpus of conservative secret patterns."""

    def __init__(self, rules: tuple[_Rule, ...] = DEFAULT_RULES) -> None:
        self._rules = rules

    def redact(self, text: str) -> RedactionResult:
        redacted = text
        total = 0
        labels: list[str] = []
        for rule in self._rules:
            redacted, count = rule.pattern.subn(rule.replacement, redacted)
            if count:
                total += count
                labels.append(rule.label)
        return RedactionResult(redacted, total, tuple(labels))

    def redact_at(self, seam: RedactionSeam, text: str) -> RedactionResult:
        """Apply the one shared policy at a declared persistence/display seam."""

        if not isinstance(seam, RedactionSeam):
            raise TypeError("seam must be a RedactionSeam")
        return self.redact(text)

    def redact_content(
        self, seam: RedactionSeam, kind: ContentKind, text: str
    ) -> RedactionResult | None:
        """Exclude forbidden native kinds before applying pattern redaction."""

        if not isinstance(kind, ContentKind):
            raise TypeError("kind must be a ContentKind")
        if kind in FORBIDDEN_CONTENT_KINDS:
            return None
        return self.redact_at(seam, text)


def required_redaction(
    redactor: Redactor,
    seam: RedactionSeam,
    kind: ContentKind,
    text: str,
) -> RedactionResult:
    """Redact content that its declared kind requires to remain visible."""

    result = redactor.redact_content(seam, kind, text)
    if result is None:
        raise RuntimeError(
            f"{kind.value} content was unexpectedly excluded at {seam.value}"
        )
    return result


def conceal_native_session_ids(text: str) -> str:
    """Hide supported native session handles on human discovery surfaces."""

    return _OPENCODE_SESSION_ID.sub(
        "[session]", _NATIVE_SESSION_UUID.sub("[session]", text)
    )


DEFAULT_REDACTOR = Redactor()
