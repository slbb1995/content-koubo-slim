"""Prepare one to five independent UTF-8 reference files without changing sources."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .error_model import SlimRuntimeError


SUPPORTED_SUFFIXES = {".md", ".txt"}


@dataclass(frozen=True)
class PreparedReference:
    reference_id: str
    source_path: Path
    source_sha256: str
    title: str
    content: str
    content_sha256: str

    def private_index_item(self) -> dict[str, Any]:
        return {
            "reference_id": self.reference_id,
            "source_type": "local_file",
            "source_locator": str(self.source_path),
            "source_sha256": self.source_sha256,
            "title": self.title,
            "prepared_file": f"{self.reference_id}.md",
            "content_sha256": self.content_sha256,
            "source_boundary": f"{self.reference_id} 独立本地来源；不得与其他参考合并冒充单一来源",
        }

    def analyzer_item(self) -> dict[str, Any]:
        return {
            "reference_id": self.reference_id,
            "title": self.title,
            "content": self.content,
            "source_boundary": f"{self.reference_id} 独立本地来源；只迁移通用内容价值与表达机制",
        }


def _clean_text(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\ufeff", "").replace("\u200b", "")
    lines = [line.rstrip() for line in normalized.split("\n")]
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return cleaned


def _title(path: Path, content: str) -> str:
    match = re.search(r"(?m)^#\s+(.+?)\s*$", content)
    title = match.group(1).strip() if match else path.stem.strip()
    return title[:200] or "未命名参考"


def preflight_references(paths: Iterable[str | Path]) -> list[PreparedReference]:
    source_paths = list(paths)
    if not 1 <= len(source_paths) <= 5:
        raise SlimRuntimeError(
            "SLIM_REFERENCE_INVALID",
            "reference_prep",
            detail=f"reference_count={len(source_paths)}",
            workflow_stage="正在准备参考",
        )
    prepared: list[PreparedReference] = []
    seen_paths: set[Path] = set()
    try:
        for index, value in enumerate(source_paths, 1):
            source = Path(value)
            if not source.is_absolute() or source.is_symlink() or not source.is_file():
                raise ValueError(f"reference #{index} must be an absolute regular file")
            resolved = source.resolve(strict=True)
            if resolved in seen_paths:
                raise ValueError(f"reference #{index} duplicates another source")
            if resolved.suffix.casefold() not in SUPPORTED_SUFFIXES:
                raise ValueError(f"reference #{index} must be Markdown or plain text")
            raw = resolved.read_bytes()
            text = raw.decode("utf-8")
            content = _clean_text(text)
            if not content:
                raise ValueError(f"reference #{index} is empty")
            reference_id = f"REF-{index:03d}"
            prepared.append(
                PreparedReference(
                    reference_id=reference_id,
                    source_path=resolved,
                    source_sha256=hashlib.sha256(raw).hexdigest(),
                    title=_title(resolved, content),
                    content=content,
                    content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                )
            )
            seen_paths.add(resolved)
        return prepared
    except (OSError, UnicodeError, ValueError) as exc:
        raise SlimRuntimeError(
            "SLIM_REFERENCE_INVALID",
            "reference_prep",
            detail=str(exc),
            workflow_stage="正在准备参考",
        ) from exc


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_reference_index(prepared: list[PreparedReference]) -> dict[str, Any]:
    items = [item.private_index_item() for item in prepared]
    return {
        "contract_version": "content-v2-slim-reference-index-v1",
        "reference_count": len(items),
        "references": items,
        "reference_set_sha256": _canonical_hash(items),
    }


def write_prepared_references(
    run_dir: str | Path, prepared: list[PreparedReference]
) -> tuple[Path, dict[str, Any]]:
    run_root = Path(run_dir)
    target = run_root / "references"
    index = build_reference_index(prepared)
    if target.exists():
        try:
            if target.is_symlink() or not target.is_dir():
                raise ValueError("references path is not a real directory")
            existing = json.loads((target / "reference_index.json").read_text(encoding="utf-8"))
            if existing != index:
                raise ValueError("prepared reference set differs from frozen set")
            for item in prepared:
                expected = f"# {item.title}\n\n{item.content}\n"
                if (target / f"{item.reference_id}.md").read_text(encoding="utf-8") != expected:
                    raise ValueError("prepared reference content drifted")
            return target, index
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise SlimRuntimeError(
                "SLIM_TASK_IDENTITY_CHANGED",
                "reference_prep",
                detail=str(exc),
                workflow_stage="正在准备参考",
                run_exists=True,
                artifacts_exist=True,
                artifacts_preserved=True,
            ) from exc

    temporary = run_root / f".references.{secrets.token_hex(4)}.tmp"
    try:
        temporary.mkdir()
        for item in prepared:
            (temporary / f"{item.reference_id}.md").write_text(
                f"# {item.title}\n\n{item.content}\n", encoding="utf-8"
            )
        (temporary / "reference_index.json").write_text(
            json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.rename(temporary, target)
        return target, index
    except (OSError, TypeError, ValueError) as exc:
        if target.exists():
            return write_prepared_references(run_root, prepared)
        raise SlimRuntimeError(
            "SLIM_REFERENCE_INVALID",
            "reference_prep",
            detail=str(exc),
            workflow_stage="正在准备参考",
            run_exists=True,
        ) from exc
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
