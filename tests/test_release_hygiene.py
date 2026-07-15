"""Release-archive hygiene tests; this directory is excluded from distributions."""

from __future__ import annotations

import importlib.util
import io
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github" / "scripts" / "package_release.py"
SPEC = importlib.util.spec_from_file_location("loyalty_radar_package_release", SCRIPT)
assert SPEC and SPEC.loader
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


def test_zip_release_rejects_test_paths(tmp_path: Path) -> None:
    archive = tmp_path / "candidate.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("loyalty-radar/tests/test_report.py", "print('isolated test')")

    with pytest.raises(ValueError, match="test, or private path"):
        release.validate_release_archive(archive)


def test_zip_release_rejects_mock_report_markers(tmp_path: Path) -> None:
    archive = tmp_path / "candidate.whl"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("loyalty_radar/report.json", '{"source": "synthetic-member"}')

    with pytest.raises(ValueError, match="Mock-data marker"):
        release.validate_release_archive(archive)


def test_tar_release_accepts_runtime_source_without_fixture_content(tmp_path: Path) -> None:
    archive = tmp_path / "candidate.tar.gz"
    payload = b"__version__ = '0.1.1'\n"
    info = tarfile.TarInfo("loyalty_radar-0.1.1/loyalty_radar/__init__.py")
    info.size = len(payload)
    with tarfile.open(archive, "w:gz") as handle:
        handle.addfile(info, io.BytesIO(payload))

    release.validate_release_archive(archive)

