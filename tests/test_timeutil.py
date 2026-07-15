from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tang.timeutil import optional_rfc3339, rfc3339


def test_rfc3339_normalizes_utc_and_preserves_meaningful_microseconds() -> None:
    offset = timezone(timedelta(hours=-4))

    assert rfc3339(datetime(2026, 7, 15, 12, 0, tzinfo=offset)) == (
        "2026-07-15T16:00:00Z"
    )
    assert rfc3339(
        datetime(2026, 7, 15, 12, 0, 0, 123456, tzinfo=offset)
    ) == "2026-07-15T16:00:00.123456Z"
    assert optional_rfc3339(None) is None


def test_rfc3339_rejects_naive_timestamps() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        rfc3339(datetime(2026, 7, 15, 16, 0))
