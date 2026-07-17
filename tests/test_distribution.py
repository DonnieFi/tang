from __future__ import annotations

import tomllib
import tarfile
from io import BytesIO
from pathlib import Path

from tang.release import normalize_sdist

ROOT = Path(__file__).parents[1]


def test_release_metadata_and_manifest_are_explicit() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    manifest = (ROOT / "MANIFEST.in").read_text()

    assert project["name"] == "tang-multiverse"
    assert project["version"] == "0.2.0"
    assert project["requires-python"] == ">=3.11"
    assert project["license"] == "MIT"
    assert project["scripts"] == {"tang": "tang.cli:main"}
    assert project["urls"]["Repository"] == "https://github.com/DonnieFi/tang.git"
    assert "recursive-include tests/fixtures" in manifest
    assert "include CONTEXT.md" in manifest
    assert "include docs/getting-started.md" in manifest
    assert "include docs/assets/tang-multiverse-demo.svg" in manifest
    assert "include docs/assets/tang-samurai.webp" in manifest
    assert "include skills/tang/SKILL.md" in manifest
    assert "exclude docs/assets/tang-mascot-concept.png" in manifest
    assert "prune plan" in manifest
    assert "prune .beads" in manifest


def test_mit_license_is_complete() -> None:
    license_text = (ROOT / "LICENSE").read_text()
    assert license_text.startswith("MIT License")
    assert "Permission is hereby granted, free of charge" in license_text
    assert 'THE SOFTWARE IS PROVIDED "AS IS"' in license_text


def test_sdist_normalization_is_reproducible(tmp_path: Path) -> None:
    source = tmp_path / "source.tar.gz"
    with tarfile.open(source, "w:gz") as archive:
        payload = b"release input"
        member = tarfile.TarInfo("tang_multiverse-0.2.0/input.txt")
        member.size = len(payload)
        member.mtime = 123456
        archive.addfile(member, BytesIO(payload))

    first = tmp_path / "first.tar.gz"
    second = tmp_path / "second.tar.gz"
    normalize_sdist(source, first, 1_783_987_200)
    normalize_sdist(source, second, 1_783_987_200)

    assert first.read_bytes() == second.read_bytes()
    with tarfile.open(first, "r:gz") as normalized:
        item = normalized.getmembers()[0]
        assert item.mtime == 1_783_987_200
        assert item.uid == item.gid == 0
