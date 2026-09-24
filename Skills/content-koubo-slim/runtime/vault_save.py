"""Create-only two-file save below one Manifest-authorized output root."""

from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .error_model import SlimRuntimeError


def _reject_reparse(path: Path) -> None:
    """Check the supplied spelling before resolve can hide a symlink/junction."""
    for item in (path, *path.parents):
        if item.is_symlink() or (item.exists() and getattr(item.lstat(), "st_file_attributes", 0) & 0x400):
            _fail("save path contains a symlink or reparse point")


def _fail(detail: str) -> None:
    raise SlimRuntimeError(
        "SLIM_SAVE_FAILED",
        "vault_save",
        detail=detail,
        workflow_stage="等待你确认并保存",
        run_exists=True,
        artifacts_exist=True,
        artifacts_preserved=True,
    )


def _render_template(template: str, client_id: str, now: datetime) -> PurePosixPath:
    if not isinstance(template, str) or not template or "\\" in template:
        _fail("output template is not a non-empty POSIX relative path")
    if not isinstance(client_id, str) or not client_id.strip():
        _fail("client id is missing")
    rendered = template.replace("{profile_or_brand}", client_id)
    rendered = rendered.replace("{profile_id}", client_id)
    rendered = rendered.replace("YYYY", f"{now.year:04d}")
    rendered = re.sub(r"(?<![A-Za-z])M(?![A-Za-z])", str(now.month), rendered)
    rendered = re.sub(
        r"(?<![A-Za-z])W(?![A-Za-z])", str((now.day - 1) // 7 + 1), rendered
    )
    if "{" in rendered or "}" in rendered:
        _fail("output template contains an unsupported placeholder")
    if ":" in rendered or any(part in {"", ".", ".."} for part in rendered.split("/")):
        _fail("output template contains unsafe path segments")
    relative = PurePosixPath(rendered)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        _fail("output template escapes the authorized output root")
    return relative


def _safe_directory(output_root: Path, relative: PurePosixPath) -> Path:
    try:
        if not output_root.is_absolute() or output_root.is_symlink() or not output_root.is_dir():
            raise ValueError("output root must be an existing real directory")
        _reject_reparse(output_root)
        root = output_root.resolve(strict=True)
        current = root
        for part in relative.parts:
            candidate = current / part
            _reject_reparse(candidate)
            candidate.mkdir(exist_ok=True)
            if candidate.is_symlink() or not candidate.is_dir():
                raise ValueError("output template contains a symlink or non-directory")
            current = candidate.resolve(strict=True)
            current.relative_to(root)
        return current
    except (OSError, ValueError) as exc:
        _fail(str(exc))


def _filename_stem(publish_title: str) -> str:
    if not isinstance(publish_title, str) or not publish_title.strip():
        _fail("selected publish title is empty")
    stem = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", " ", publish_title)
    stem = re.sub(r"\s+", " ", stem).strip(" .")
    if not stem:
        _fail("selected publish title cannot form a safe filename")
    return stem[:60].rstrip(" .")


def _write_pair(targets: tuple[tuple[Path, bytes], tuple[Path, bytes]]) -> None:
    if any(path.exists() or path.is_symlink() for path, _ in targets):
        _fail("one or both target files already exist")
    created: list[tuple[Path, tuple[int, int]]] = []
    try:
        for path, payload in targets:
            with path.open("xb") as handle:
                stat = os.fstat(handle.fileno())
                # Own the file immediately after exclusive create, before any
                # operation that can fail. Never clean up a replacement inode.
                created.append((path, (stat.st_dev, stat.st_ino)))
                if handle.write(payload) != len(payload):
                    raise OSError("short output write")
                handle.flush()
                os.fsync(handle.fileno())
        for path, payload in targets:
            if path.is_symlink() or path.read_bytes() != payload:
                raise OSError(f"saved file did not read back exactly: {path.name}")
    except OSError as exc:
        for path, identity in reversed(created):
            try:
                _reject_reparse(path)
                if path.exists():
                    stat = path.stat()
                    if (stat.st_dev, stat.st_ino) == identity:
                        path.unlink()
            except OSError:
                pass
        _fail(str(exc))


def save_markdown_pair(
    *,
    output_root: str | Path,
    output_template: str,
    client_id: str,
    selected_publish_title: str,
    oral_body: str,
    package_markdown: str,
    now: datetime | None = None,
    draft_version: int = 1,
    package_version: int = 1,
    item_suffix: str | None = None,
    receipt_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Save both final Markdown files or leave neither final file behind."""

    if not isinstance(oral_body, str) or not oral_body.strip():
        _fail("approved oral body is empty")
    if not isinstance(package_markdown, str) or not package_markdown.strip():
        _fail("approved package Markdown is empty")
    if receipt_dir is not None:
        from .local_save_receipt import save_with_receipt
        return save_with_receipt(output_root=output_root, output_template=output_template,
            client_id=client_id, selected_publish_title=selected_publish_title,
            oral_body=oral_body, package_markdown=package_markdown,
            now=now, receipt_dir=receipt_dir, draft_version=draft_version,
            package_version=package_version, item_suffix=item_suffix)
    timestamp = now or datetime.now().astimezone()
    relative_dir = _render_template(output_template, client_id, timestamp)
    root = Path(output_root)
    if not root.is_absolute():
        _fail("output root must be absolute")
    _reject_reparse(root)
    try:
        root = root.resolve(strict=True)
    except OSError as exc:
        _fail(str(exc))
    target_dir = _safe_directory(root, relative_dir)
    stem = _versioned_stem(selected_publish_title, draft_version, item_suffix)
    oral_path = target_dir / f"{stem}-口播稿.md"
    package_path = target_dir / _package_filename(stem, package_version)
    oral_bytes = (oral_body + "\n").encode("utf-8")
    package_bytes = (package_markdown.rstrip() + "\n").encode("utf-8")
    _write_pair(((oral_path, oral_bytes), (package_path, package_bytes)))
    return {
        "oral_path": oral_path,
        "package_path": package_path,
        "oral_relative_path": oral_path.relative_to(root).as_posix(),
        "package_relative_path": package_path.relative_to(root).as_posix(),
        "oral_sha256": hashlib.sha256(oral_bytes).hexdigest(),
        "package_sha256": hashlib.sha256(package_bytes).hexdigest(),
        "publish_status": "not_requested",
    }


def save_markdown_package_revision(
    *, output_root: str | Path, output_template: str, client_id: str,
    archive_title: str, package_markdown: str, verified_oral: dict[str, Any],
    receipt_dir: str | Path, draft_version: int, package_version: int,
    item_suffix: str | None = None, now: datetime | None = None,
) -> dict[str, Any]:
    """Create only a new package revision after verifying the saved oral artifact."""
    from .local_save_receipt import save_package_revision_with_receipt
    return save_package_revision_with_receipt(
        output_root=output_root, output_template=output_template, client_id=client_id,
        archive_title=archive_title, package_markdown=package_markdown,
        verified_oral=verified_oral, receipt_dir=receipt_dir,
        draft_version=draft_version, package_version=package_version,
        item_suffix=item_suffix, now=now,
    )


def _versioned_stem(title: str, draft_version: int = 1, item_suffix: str | None = None) -> str:
    """One naming rule for local output, remote output and receipt verification."""
    if type(draft_version) is not int or draft_version < 1:
        _fail("draft version must be a positive integer")
    stem = _filename_stem(title)
    if item_suffix is not None:
        if not isinstance(item_suffix, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}-[0-9a-f]{32}", item_suffix):
            _fail("batch item filename suffix is invalid")
        stem = stem[:40].rstrip(" .") + f"-{item_suffix}"
    if draft_version > 1:
        stem += f"-第{draft_version}版"
    return stem


def _package_filename(stem: str, package_version: int) -> str:
    if type(package_version) is not int or package_version < 1:
        _fail("package version must be a positive integer")
    suffix = "" if package_version == 1 else f"-第{package_version}版"
    return f"{stem}-配套文案{suffix}.md"
