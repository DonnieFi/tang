"""Deterministic release-artifact normalization."""

from __future__ import annotations

import gzip
import shutil
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory


def normalize_sdist(source: Path, destination: Path, epoch: int) -> None:
    """Rewrite setuptools' generated mtimes and ownership deterministically."""

    with tarfile.open(source, "r:gz") as archive, TemporaryDirectory() as temporary:
        tar_path = Path(temporary) / "normalized.tar"
        with tarfile.open(tar_path, "w", format=tarfile.PAX_FORMAT) as normalized:
            for member in archive.getmembers():
                payload = archive.extractfile(member) if member.isfile() else None
                member.uid = member.gid = 0
                member.uname = member.gname = ""
                member.mtime = epoch
                member.pax_headers = {}
                normalized.addfile(member, payload)
        with tar_path.open("rb") as raw, destination.open("wb") as output:
            with gzip.GzipFile(
                filename="", fileobj=output, mode="wb", mtime=epoch, compresslevel=9
            ) as compressed:
                shutil.copyfileobj(raw, compressed)
