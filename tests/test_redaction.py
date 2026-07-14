from __future__ import annotations

import pytest

from tang.redaction import DEFAULT_REDACTOR


@pytest.mark.parametrize(
    ("text", "secret", "label"),
    [
        ("API_KEY=supersecretvalue", "supersecretvalue", "credential"),
        ("Authorization: Bearer abcdefghijklmnop", "abcdefghijklmnop", "token"),
        ("token ghp_abcdefghijklmnopqrstuvwxyz", "ghp_abcdefghijklmnopqrstuvwxyz", "token"),
        ("key sk-abcdefghijklmnop1234", "sk-abcdefghijklmnop1234", "token"),
        ("https://alice:hunter2@example.test/repo", "hunter2", "password"),
        ("open /home/alice/private/file.txt", "/home/alice", "~"),
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
