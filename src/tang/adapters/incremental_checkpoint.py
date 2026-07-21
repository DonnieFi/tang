"""Shared incremental-scan checkpoint helpers for read-only adapters."""

from __future__ import annotations

import json
from typing import Any

from tang.adapters.base import AdapterCheckpoint, AdapterWarning


def decode_fingerprint_checkpoint(
    checkpoint: AdapterCheckpoint | None,
    *,
    adapter_key: str,
    source_namespace: str,
    allowed_schema_versions: frozenset[int],
    legacy_rescan_versions: frozenset[int],
    warnings: list[AdapterWarning],
    invalid_code: str = "checkpoint-invalid",
    scope_code: str = "checkpoint-scope",
) -> tuple[dict[str, str], frozenset[str]]:
    """Decode schema-versioned fingerprint checkpoints shared by Codex/Grok/OpenCode."""

    if checkpoint is None:
        return {}, frozenset()
    if (
        checkpoint.adapter != adapter_key
        or checkpoint.source_namespace != source_namespace
    ):
        warnings.append(
            AdapterWarning(
                scope_code,
                "The checkpoint belongs to another adapter namespace; a full scan ran.",
            )
        )
        return {}, frozenset()
    try:
        payload = json.loads(checkpoint.cursor)
        fingerprints = payload["fingerprints"]
        schema_version = payload.get("schema_version")
        if schema_version not in allowed_schema_versions or not isinstance(
            fingerprints, dict
        ):
            raise ValueError
        if not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in fingerprints.items()
        ):
            raise ValueError
        if schema_version in legacy_rescan_versions:
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
                invalid_code,
                "The checkpoint was invalid; a full scan ran.",
            )
        )
        return {}, frozenset()


def encode_fingerprint_checkpoint(
    fingerprints: dict[str, str],
    validated: frozenset[str],
    *,
    schema_version: int = 4,
) -> str:
    payload: dict[str, Any] = {
        "schema_version": schema_version,
        "fingerprints": fingerprints,
        "validated": sorted(validated),
    }
    return json.dumps(payload, sort_keys=True)
