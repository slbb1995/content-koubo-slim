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
    source_lines: tuple[int, int] | None = None

    def private_index_item(self) -> dict[str, Any]:
        item = {
            "reference_id": self.reference_id,
            "source_type": "local_file",
            "source_locator": str(self.source_path),
            "source_sha256": self.source_sha256,
            "title": self.title,
            "prepared_file": f"{self.reference_id}.md",
            "content_sha256": self.content_sha256,
            "source_boundary": f"{self.reference_id} 独立本地来源；不得与其他参考合并冒充单一来源",
        }
        if self.source_lines is not None:
            item["source_lines"] = list(self.source_lines)
            item["source_boundary"] = self._boundary()
        return item

    def _boundary(self) -> str:
        start, end = self.source_lines
        return f"{self.reference_id} 原始文档第 {start}—{end} 行的独立篇目；与同文档其他篇分开分析；只迁移通用内容价值与表达机制"

    def analyzer_item(self) -> dict[str, Any]:
        return {
            "reference_id": self.reference_id,
            "title": self.title,
            "content": self.content,
            "source_boundary": self._boundary() if self.source_lines else f"{self.reference_id} 独立本地来源；只迁移通用内容价值与表达机制",
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


def _read_reference(source: Path) -> tuple[Path, bytes, str]:
    if not source.is_absolute() or source.is_symlink() or not source.is_file():
        raise ValueError("reference must be an absolute regular file")
    resolved = source.resolve(strict=True)
    if resolved.suffix.casefold() not in SUPPORTED_SUFFIXES:
        raise ValueError("reference must be Markdown or plain text")
    raw = resolved.read_bytes()
    text = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    if not _clean_text(text):
        raise ValueError("reference is empty")
    return resolved, raw, text


def _mapped_pieces(map_path: Path) -> list[tuple[Path, bytes, str, str, tuple[int, int]]]:
    """Validate AI-selected piece boundaries against the complete original text."""
    if not map_path.is_absolute() or map_path.is_symlink() or not map_path.is_file():
        raise ValueError("reference map must be an absolute regular file")
    plan = json.loads(map_path.read_text(encoding="utf-8"))
    if not isinstance(plan, dict) or set(plan) != {"source_path", "source_sha256", "items", "excluded_ranges"}:
        raise ValueError("reference map fields are invalid")
    if not isinstance(plan["source_path"], str):
        raise ValueError("reference source path must be text")
    source, raw, text = _read_reference(Path(plan["source_path"]))
    if hashlib.sha256(raw).hexdigest() != plan["source_sha256"]:
        raise ValueError("reference map source changed")
    lines = text.splitlines()
    if not isinstance(plan["items"], list) or not 1 <= len(plan["items"]) <= 5:
        raise ValueError("reference map needs one to five independent pieces")
    if not isinstance(plan["excluded_ranges"], list):
        raise ValueError("excluded ranges must be a list")
    covered: set[int] = set()
    result = []
    last_end = 0
    for included, entries in ((True, plan["items"]), (False, plan["excluded_ranges"])):
        for entry in entries:
            label = "title" if included else "reason"
            if not isinstance(entry, dict) or set(entry) != {"start_line", "end_line", label}:
                raise ValueError("reference range fields are invalid")
            start, end = entry["start_line"], entry["end_line"]
            if type(start) is not int or type(end) is not int or not 1 <= start <= end <= len(lines):
                raise ValueError("reference range is outside source")
            if not isinstance(entry[label], str) or not entry[label].strip():
                raise ValueError("range needs a title or exclusion reason")
            selected = set(range(start, end + 1))
            if covered & selected:
                raise ValueError("reference ranges overlap")
            covered.update(selected)
            if included:
                if start <= last_end:
                    raise ValueError("reference pieces must preserve original order")
                last_end = end
                content = _clean_text("\n".join(lines[start - 1:end]))
                if not content:
                    raise ValueError("reference piece is empty")
                result.append((source, raw, content, entry[label].strip(), (start, end)))
    if any(line.strip() and number not in covered for number, line in enumerate(lines, 1)):
        raise ValueError("nonempty source lines were silently omitted")
    return result


def preflight_references(paths: Iterable[str | Path]) -> list[PreparedReference]:
    source_paths = list(paths)
    if not 0 <= len(source_paths) <= 5:
        raise SlimRuntimeError(
            "SLIM_REFERENCE_INVALID",
            "reference_prep",
            detail=f"reference_count={len(source_paths)}",
            workflow_stage="正在准备参考",
        )
    prepared: list[PreparedReference] = []
    seen_ranges: dict[Path, list[tuple[int, int] | None]] = {}
    try:
        pieces = []
        for value in source_paths:
            source = Path(value)
            if source.name.endswith(".reference-map.json"):
                pieces.extend(_mapped_pieces(source))
            else:
                resolved, raw, text = _read_reference(source)
                content = _clean_text(text)
                pieces.append((resolved, raw, content, _title(resolved, content), None))
        if len(pieces) > 5:
            raise ValueError("at most five independent reference pieces are supported")
        for index, (resolved, raw, content, title, line_range) in enumerate(pieces, 1):
            prior = seen_ranges.setdefault(resolved, [])
            if prior and (line_range is None or any(old is None or max(old[0], line_range[0]) <= min(old[1], line_range[1]) for old in prior)):
                raise ValueError("duplicate or overlapping reference source")
            prior.append(line_range)
            reference_id = f"REF-{index:03d}"
            prepared.append(
                PreparedReference(
                    reference_id=reference_id,
                    source_path=resolved,
                    source_sha256=hashlib.sha256(raw).hexdigest(),
                    title=title,
                    content=content,
                    content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    source_lines=line_range,
                )
            )
        return prepared
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
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
        "contract_version": "content-koubo-slim-reference-index-v1",
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
