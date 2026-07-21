"""Single source for per-harness capability flags used by core and docs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HarnessCapabilities:
    adapter_key: str
    display_name: str
    link_source: bool
    link_destination: bool
    native_resume: bool
    host_skill: bool
    release_claim_linux: bool


_CAPABILITIES: tuple[HarnessCapabilities, ...] = (
    HarnessCapabilities(
        "codex", "Codex CLI", True, True, True, True, True
    ),
    HarnessCapabilities(
        "grok", "Grok Build", True, True, False, False, True
    ),
    HarnessCapabilities(
        "opencode", "OpenCode", True, True, True, True, True
    ),
    HarnessCapabilities(
        "cursor", "Cursor IDE", True, False, False, False, False
    ),
)

_BY_KEY = {entry.adapter_key: entry for entry in _CAPABILITIES}


def all_capabilities() -> tuple[HarnessCapabilities, ...]:
    return _CAPABILITIES


def capability_for(adapter_key: str) -> HarnessCapabilities | None:
    return _BY_KEY.get(adapter_key)


def supported_destination_adapters() -> frozenset[str]:
    return frozenset(
        entry.adapter_key
        for entry in _CAPABILITIES
        if entry.link_destination
    )


def supported_resume_adapters() -> frozenset[str]:
    return frozenset(
        entry.adapter_key for entry in _CAPABILITIES if entry.native_resume
    )
