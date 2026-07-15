from __future__ import annotations

import pytest

from tang.redaction import (
    DEFAULT_REDACTOR,
    ContentKind,
    RedactionSeam,
    required_redaction,
)


@pytest.mark.parametrize(
    ("text", "secret", "label"),
    [
        ("API_KEY=supersecretvalue", "supersecretvalue", "credential"),
        (
            'PASSWORD="correct horse battery staple"',
            "correct horse battery staple",
            "credential",
        ),
        (
            "CLIENT_SECRET='space separated secret'",
            "space separated secret",
            "credential",
        ),
        ("Authorization: Bearer abcdefghijklmnop", "abcdefghijklmnop", "token"),
        ("token ghp_abcdefghijklmnopqrstuvwxyz", "ghp_abcdefghijklmnopqrstuvwxyz", "token"),
        ("key sk-abcdefghijklmnop1234", "sk-abcdefghijklmnop1234", "token"),
        ("https://alice:hunter2@example.test/repo", "hunter2", "password"),
        ("open /home/alice/private/file.txt", "/home/alice", "~"),
        (r"open C:\Users\Alice\private\file.txt", r"C:\Users\Alice", "~"),
        ("read /root/.ssh/config", "/root", "~"),
        (
            "-----BEGIN PRIVATE KEY-----\nSECRET\n-----END PRIVATE KEY-----",
            "SECRET",
            "private-key",
        ),
    ],
)
def test_baseline_redaction_corpus(
    text: str, secret: str, label: str
) -> None:
    result = DEFAULT_REDACTOR.redact(text)

    assert secret not in result.text
    assert label in result.text
    assert result.redaction_count >= 1


def test_redaction_is_deterministic_and_leaves_normal_text_unchanged() -> None:
    text = "Use a deterministic fingerprint for the selected session."

    first = DEFAULT_REDACTOR.redact(text)
    second = DEFAULT_REDACTOR.redact(text)

    assert first == second
    assert first.text == text
    assert first.redaction_count == 0


def test_every_declared_seam_uses_the_same_redaction_policy() -> None:
    secret = 'PASSWORD="adversarial spaced value"'

    results = {
        seam: DEFAULT_REDACTOR.redact_at(seam, secret) for seam in RedactionSeam
    }

    assert len(set(results.values())) == 1
    assert "adversarial spaced value" not in next(iter(results.values())).text


@pytest.mark.parametrize(
    "kind",
    [
        ContentKind.SYSTEM_PROMPT,
        ContentKind.HIDDEN_REASONING,
        ContentKind.TOOL_PAYLOAD,
        ContentKind.TOOL_RESULT,
        ContentKind.FILE_BODY,
    ],
)
def test_forbidden_native_content_is_excluded_before_redaction(
    kind: ContentKind,
) -> None:
    result = DEFAULT_REDACTOR.redact_content(
        RedactionSeam.CAPSULE_PERSISTENCE,
        kind,
        "forbidden payload PASSWORD=should-never-be-considered-visible",
    )

    assert result is None


@pytest.mark.parametrize(
    "kind",
    [
        ContentKind.TITLE,
        ContentKind.VISIBLE_TEXT,
        ContentKind.CITATION,
        ContentKind.WARNING,
        ContentKind.DISPLAY_METADATA,
    ],
)
def test_allowed_content_is_redacted_consistently(kind: ContentKind) -> None:
    result = DEFAULT_REDACTOR.redact_content(
        RedactionSeam.SNIPPET_DISPLAY,
        kind,
        "Bearer abcdefghijklmnop",
    )

    assert result is not None
    assert "abcdefghijklmnop" not in result.text


def test_required_redaction_fails_explicitly_for_excluded_content() -> None:
    with pytest.raises(RuntimeError, match="unexpectedly excluded"):
        required_redaction(
            DEFAULT_REDACTOR,
            RedactionSeam.CONTEXT_REREAD,
            ContentKind.TOOL_PAYLOAD,
            "must never become visible",
        )
