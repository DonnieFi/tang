#!/usr/bin/env python3
"""Build byte-reproducible Tang wheel and source-distribution artifacts."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tang.release import normalize_sdist  # noqa: E402


DEFAULT_EPOCH = 1_783_987_200  # 2026-07-13T00:00:00Z


def build(output: Path, epoch: int) -> tuple[Path, Path]:
    output.mkdir(parents=True, exist_ok=True)
    environment = {**os.environ, "SOURCE_DATE_EPOCH": str(epoch)}
    with TemporaryDirectory(prefix="tang-release-build-") as temporary:
        raw = Path(temporary)
        subprocess.run(
            ["uv", "build", "--out-dir", str(raw)],
            check=True,
            env=environment,
        )
        wheel = next(raw.glob("*.whl"))
        sdist = next(raw.glob("*.tar.gz"))
        wheel_destination = output / wheel.name
        sdist_destination = output / sdist.name
        shutil.copyfile(wheel, wheel_destination)
        normalize_sdist(sdist, sdist_destination, epoch)
    return sdist_destination, wheel_destination


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--epoch",
        type=int,
        default=int(os.environ.get("SOURCE_DATE_EPOCH", DEFAULT_EPOCH)),
    )
    arguments = parser.parse_args()
    for artifact in build(arguments.output, arguments.epoch):
        print(artifact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
