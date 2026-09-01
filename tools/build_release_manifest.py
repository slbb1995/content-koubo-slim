#!/usr/bin/env python3
"""Regenerate Content 口播 Slim runtime metadata and checksums."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTENT_SKILLS = (
    "content-koubo-analyzer",
    "content-koubo-context-retriever",
    "content-koubo-publish-pack",
    "content-koubo-slim",
    "content-koubo-writer",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def runtime_files() -> list[dict[str, object]]:
    files: list[dict[str, object]] = []
    for skill in CONTENT_SKILLS:
        for path in sorted((ROOT / "Skills" / skill).rglob("*")):
            if (
                not path.is_file()
                or path.is_symlink()
                or path.name == "__pycache__"
                or path.suffix in {".pyc", ".pyo"}
            ):
                continue
            files.append(
                {
                    "bytes": path.stat().st_size,
                    "mode": "0644",
                    "path": path.relative_to(ROOT).as_posix(),
                    "sha256": sha256(path),
                    "skill": skill,
                }
            )
    return sorted(files, key=lambda item: str(item["path"]))


def tree_sha256(files: list[dict[str, object]]) -> str:
    digest = hashlib.sha256()
    for item in files:
        digest.update(
            b"F\0"
            + str(item["path"]).encode("utf-8")
            + b"\0"
            + str(item["mode"]).encode("ascii")
            + b"\0"
            + str(item["sha256"]).encode("ascii")
            + b"\0"
        )
    return digest.hexdigest()


def main() -> int:
    manifest_path = ROOT / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    files = runtime_files()
    tree = tree_sha256(files)
    source = manifest.get("source", {})
    if (
        not isinstance(source.get("commit"), str)
        or len(source["commit"]) != 40
        or source.get("selection_path") != "packages/content-koubo-slim.json"
    ):
        raise SystemExit("release manifest lacks a valid Factory source binding")
    manifest["schema_version"] = "content-koubo-slim-release-v1"
    manifest["package"] = {"id": "content-koubo-slim", "version": version}
    manifest["runtime"] = {
        "file_count": len(files),
        "files": files,
        "legacy_v1_runtime_dependency_count": 0,
        "skill_count": len(CONTENT_SKILLS),
        "skills": list(CONTENT_SKILLS),
        "tree_sha256": tree,
    }
    manifest["source"] = source
    manifest["integrity"] = {"hash_algorithm": "sha256"}
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    checksum_paths = [
        *(ROOT / item["path"] for item in files),
        ROOT / "VERSION",
        manifest_path,
    ]
    (ROOT / "SHA256SUMS").write_text(
        "".join(
            f"{sha256(path)}  {path.relative_to(ROOT).as_posix()}\n"
            for path in checksum_paths
        ),
        encoding="utf-8",
    )
    print(f"Updated {version}: {len(files)} runtime files, tree {tree}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
