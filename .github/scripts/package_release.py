#!/usr/bin/env python3
"""Create deterministic Plugin/Skill archives and SHA256SUMS."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins" / "loyalty-radar"
SKILL = PLUGIN / "skills" / "loyalty-radar"
EXCLUDED_PARTS = {"__pycache__", ".DS_Store", ".pytest_cache", ".translation-cache", "output", "reports"}
FORBIDDEN_ARCHIVE_NAMES = {"demo-report.json", "profile.demo.yaml", "demo-en.gif", "build_demo.py"}
FORBIDDEN_RELEASE_PARTS = EXCLUDED_PARTS | {"tests", "fixtures", "test-results"}
FORBIDDEN_TEXT_MARKERS = (
    "example.invalid",
    "synthetic-member",
    "synthetic-industry",
    "fictional limited transfer window",
    "合成示例",
)
TEXT_SUFFIXES = {".md", ".py", ".toml", ".yaml", ".yml", ".json", ".txt", ".html", ".css", ".js"}
PRIVATE_PATTERNS = (
    re.compile(r"/" r"Users/[^/\s]+/"),
    re.compile(r"[A-Za-z]:\\" r"Users\\[^\\\s]+\\"),
    re.compile(r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
)


def archive_tree(source: Path, archive: Path, archive_root: str) -> None:
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as handle:
        for path in sorted(source.rglob("*")):
            if path.is_symlink():
                raise ValueError(f"Release archives cannot contain symlinks: {path}")
            if re.search(r"\s+\d+\.[^.]+$", path.name):
                raise ValueError(f"Conflict-copy filename cannot be released: {path}")
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


def _validate_member(
    path: Path,
    name: str,
    payload: bytes | None = None,
    *,
    allow_egg_info: bool = False,
) -> None:
    parts = Path(name).parts
    if any(
        part in FORBIDDEN_RELEASE_PARTS or (part.endswith(".egg-info") and not allow_egg_info)
        for part in parts
    ):
        raise ValueError(f"Generated, test, or private path leaked into {path.name}: {name}")
    if any(part in FORBIDDEN_ARCHIVE_NAMES for part in parts):
        raise ValueError(f"Non-production public artifact leaked into {path.name}: {name}")
    if payload is None or Path(name).suffix.lower() not in TEXT_SUFFIXES:
        return
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return
    lower = text.lower()
    for marker in FORBIDDEN_TEXT_MARKERS:
        if marker in lower:
            raise ValueError(f"Mock-data marker leaked into {path.name}: {name}")
    for pattern in PRIVATE_PATTERNS:
        if pattern.search(text):
            raise ValueError(f"Private path or secret marker leaked into {path.name}: {name}")


def validate_zip_archive(path: Path) -> None:
    with zipfile.ZipFile(path) as handle:
        files = [info for info in handle.infolist() if not info.is_dir()]
        if not files:
            raise ValueError(f"Release archive is empty: {path.name}")
        for info in files:
            _validate_member(path, info.filename, handle.read(info))


def validate_tar_archive(path: Path) -> None:
    with tarfile.open(path, "r:gz") as handle:
        files = [member for member in handle.getmembers() if member.isfile()]
        if not files:
            raise ValueError(f"Release archive is empty: {path.name}")
        for member in files:
            extracted = handle.extractfile(member)
            _validate_member(
                path,
                member.name,
                extracted.read() if extracted else None,
                allow_egg_info=True,
            )


def validate_release_archive(path: Path) -> None:
    if path.name.endswith(".tar.gz"):
        validate_tar_archive(path)
    elif path.suffix.lower() in {".zip", ".whl"}:
        validate_zip_archive(path)
    else:
        raise ValueError(f"Unsupported release archive: {path.name}")


def declared_version() -> str:
    manifest = json.loads((PLUGIN / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    return str(manifest.get("version") or "").strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=declared_version())
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
    for path in [*wheels, *sdists, plugin_zip, skill_zip]:
        validate_release_archive(path)

    sums_path = dist / "SHA256SUMS"
    release_files = sorted([*wheels, *sdists, plugin_zip, skill_zip], key=lambda path: path.name)
    sums_path.write_text("".join(f"{sha256(path)}  {path.name}\n" for path in release_files), encoding="ascii")
    print("Created release assets:")
    for path in release_files + [sums_path]:
        print(f"- {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
