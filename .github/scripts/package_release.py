#!/usr/bin/env python3
"""Create deterministic Plugin/Skill archives and SHA256SUMS."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins" / "loyalty-radar"
SKILL = PLUGIN / "skills" / "loyalty-radar"
EXCLUDED_PARTS = {"__pycache__", ".DS_Store", ".pytest_cache", ".translation-cache", "output", "reports"}
FORBIDDEN_ARCHIVE_NAMES = {"demo-report.json", "profile.demo.yaml", "demo-en.gif", "build_demo.py"}


def archive_tree(source: Path, archive: Path, archive_root: str) -> None:
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as handle:
        for path in sorted(source.rglob("*")):
            if path.is_symlink():
                raise ValueError(f"Release archives cannot contain symlinks: {path}")
            if not path.is_file() or any(
                part in EXCLUDED_PARTS or part.endswith(".egg-info") for part in path.parts
            ):
                continue
            relative = path.relative_to(source).as_posix()
            info = zipfile.ZipInfo(f"{archive_root}/{relative}", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o755 if os.access(path, os.X_OK) else 0o644
            info.external_attr = (mode & 0xFFFF) << 16
            handle.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def validate_archive(path: Path) -> None:
    with zipfile.ZipFile(path) as handle:
        names = handle.namelist()
    if not names:
        raise ValueError(f"Release archive is empty: {path.name}")
    for name in names:
        parts = Path(name).parts
        if any(part in EXCLUDED_PARTS or part.endswith(".egg-info") for part in parts):
            raise ValueError(f"Generated/private path leaked into {path.name}: {name}")
        if any(part in FORBIDDEN_ARCHIVE_NAMES for part in parts):
            raise ValueError(f"Non-production public artifact leaked into {path.name}: {name}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    args = parser.parse_args()

    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", args.version):
        parser.error("--version must be a semantic version without a v prefix")
    dist = args.dist.resolve()
    dist.mkdir(parents=True, exist_ok=True)
    wheels = sorted(dist.glob("*.whl"))
    sdists = sorted(dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        print("Expected exactly one wheel and one source distribution before packaging.", file=sys.stderr)
        return 1

    plugin_zip = dist / f"loyalty-radar-plugin-{args.version}.zip"
    skill_zip = dist / f"loyalty-radar-skill-{args.version}.zip"
    archive_tree(PLUGIN, plugin_zip, "loyalty-radar")
    archive_tree(SKILL, skill_zip, "loyalty-radar")
    validate_archive(plugin_zip)
    validate_archive(skill_zip)

    sums_path = dist / "SHA256SUMS"
    release_files = sorted([*wheels, *sdists, plugin_zip, skill_zip], key=lambda path: path.name)
    sums_path.write_text("".join(f"{sha256(path)}  {path.name}\n" for path in release_files), encoding="ascii")
    print("Created release assets:")
    for path in release_files + [sums_path]:
        print(f"- {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
