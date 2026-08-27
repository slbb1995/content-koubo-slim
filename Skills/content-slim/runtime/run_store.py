"""Cross-process safe single-Run store with create-only artifact versions."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import secrets
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .error_model import SlimRuntimeError
from .state_machine import SlimStateMachine


ARTIFACT_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
FIXED_JSON_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}\.json$")
RUN_ID_PATTERN = re.compile(r"^run-\d{8}T\d{6}\.\d{6}Z-[0-9a-f]{8}$")
TASK_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
TASK_KEY_GENERATORS = {"host", "deterministic_program"}
LOCK_NAME = ".run-store.lock"
TASK_KEY_DIRECTORY = "task-keys"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        if not self.root.is_absolute():
            raise SlimRuntimeError(
                "SLIM_RUN_STORE_INVALID", "run_store", detail="run root must be absolute"
            )

    @property
    def index_path(self) -> Path:
        return self.root / "run-index.json"

    @staticmethod
    def _task_digest(task_key: str) -> str:
        if not isinstance(task_key, str) or not task_key.strip():
            raise SlimRuntimeError(
                "SLIM_RUN_STORE_INVALID", "run_store", detail="empty task key"
            )
        return hashlib.sha256(task_key.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_task_key_generator(value: str) -> str:
        if value not in TASK_KEY_GENERATORS:
            raise SlimRuntimeError(
                "SLIM_TASK_KEY_UNTRUSTED",
                "run_store",
                detail="task key must come from host or deterministic_program",
            )
        return value

    @staticmethod
    def _business_identity_digest(business_identity: dict[str, Any]) -> str:
        required = {
            "client_id",
            "speaker_mode",
            "topic_original",
            "reference_set_sha256",
        }
        if not isinstance(business_identity, dict) or set(business_identity) != required:
            raise SlimRuntimeError(
                "SLIM_TASK_KEY_UNTRUSTED",
                "run_store",
                detail="frozen business identity fields are invalid",
            )
        for field in ("client_id", "speaker_mode", "topic_original"):
            value = business_identity[field]
            if not isinstance(value, str) or not value.strip():
                raise SlimRuntimeError(
                    "SLIM_TASK_KEY_UNTRUSTED",
                    "run_store",
                    detail=f"frozen business identity {field} is invalid",
                )
        reference_hash = business_identity["reference_set_sha256"]
        if not isinstance(reference_hash, str) or not TASK_DIGEST_PATTERN.fullmatch(
            reference_hash
        ):
            raise SlimRuntimeError(
                "SLIM_TASK_KEY_UNTRUSTED",
                "run_store",
                detail="frozen reference identity is invalid",
            )
        encoded = json.dumps(
            business_identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def resolve_program_task_key(
        self, business_identity: dict[str, Any]
    ) -> tuple[str, str]:
        """Create or reuse a deterministic task record from frozen business identity."""

        identity_digest = self._business_identity_digest(business_identity)
        task_key = hashlib.sha256(
            b"content-v2-slim-task-key-v2\0" + identity_digest.encode("ascii")
        ).hexdigest()
        record_relative = f"{TASK_KEY_DIRECTORY}/{identity_digest}.json"
        record = {
            "contract_version": "content-v2-slim-task-key-v2",
            "business_identity_sha256": identity_digest,
            "task_key": task_key,
            "generated_by": "deterministic_program",
            "retry_policy": "reuse_same_record_for_same_frozen_business_identity",
        }
        with self._exclusive_lock() as root:
            record_root = root / TASK_KEY_DIRECTORY
            try:
                record_root.mkdir(exist_ok=True)
                if record_root.is_symlink() or not record_root.is_dir():
                    raise ValueError("task-key root must be a real directory")
            except (OSError, ValueError) as exc:
                raise SlimRuntimeError(
                    "SLIM_RUN_STORE_INVALID", "run_store", detail=str(exc)
                ) from exc
            record_path = record_root / f"{identity_digest}.json"
            if record_path.exists():
                if record_path.is_symlink() or not record_path.is_file():
                    raise SlimRuntimeError(
                        "SLIM_RUN_STORE_INVALID",
                        "run_store",
                        detail="task-key record is not a regular file",
                    )
                existing = self._read_json(record_path)
                if existing != record:
                    raise SlimRuntimeError(
                        "SLIM_RUN_STORE_INVALID",
                        "run_store",
                        detail="persisted task-key record does not match deterministic input",
                    )
            else:
                self._create_json(
                    record_path,
                    record,
                    error_code="SLIM_RUN_STORE_INVALID",
                )
        return task_key, record_relative

    def resolve_task_record(self, record_relative: str) -> str:
        """Resolve an existing controlled task record; never trust a raw task string."""

        if not isinstance(record_relative, str) or not re.fullmatch(
            rf"{TASK_KEY_DIRECTORY}/[0-9a-f]{{64}}\.json", record_relative
        ):
            raise SlimRuntimeError(
                "SLIM_TASK_KEY_UNTRUSTED",
                "run_store",
                detail="task record locator is invalid",
            )
        with self._exclusive_lock() as root:
            path = root / record_relative
            if path.is_symlink() or not path.is_file():
                raise SlimRuntimeError(
                    "SLIM_TASK_KEY_UNTRUSTED",
                    "run_store",
                    detail="controlled task record does not exist",
                )
            record = self._read_json(path)
        expected_fields = {
            "contract_version",
            "business_identity_sha256",
            "task_key",
            "generated_by",
            "retry_policy",
        }
        identity_digest = Path(record_relative).stem
        expected_task_key = hashlib.sha256(
            b"content-v2-slim-task-key-v2\0" + identity_digest.encode("ascii")
        ).hexdigest()
        if (
            set(record) != expected_fields
            or record["contract_version"] != "content-v2-slim-task-key-v2"
            or record["business_identity_sha256"] != identity_digest
            or record["task_key"] != expected_task_key
            or record["generated_by"] != "deterministic_program"
            or record["retry_policy"]
            != "reuse_same_record_for_same_frozen_business_identity"
        ):
            raise SlimRuntimeError(
                "SLIM_TASK_KEY_UNTRUSTED",
                "run_store",
                detail="controlled task record failed integrity validation",
            )
        state = self.get_task(expected_task_key)
        if (
            state.get("task_key_record") != record_relative
            or state.get("task_key_generated_by") != "deterministic_program"
        ):
            raise SlimRuntimeError(
                "SLIM_TASK_KEY_UNTRUSTED",
                "run_store",
                detail="controlled task record is not bound to the registered Run",
                run_exists=True,
            )
        return expected_task_key

    def _prepare_root(self) -> Path:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            if self.root.is_symlink() or not self.root.is_dir():
                raise ValueError("run root must be a real directory")
            return self.root.resolve(strict=True)
        except (OSError, ValueError) as exc:
            raise SlimRuntimeError(
                "SLIM_RUN_STORE_INVALID", "run_store", detail=str(exc)
            ) from exc

    @contextmanager
    def _exclusive_lock(self) -> Iterator[Path]:
        root = self._prepare_root()
        lock_path = root / LOCK_NAME
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(lock_path, flags, 0o600)
            with os.fdopen(descriptor, "a+b") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield root
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except SlimRuntimeError:
            raise
        except OSError as exc:
            raise SlimRuntimeError(
                "SLIM_RUN_STORE_INVALID", "run_store", detail=str(exc)
            ) from exc

    @staticmethod
    def _read_json(
        path: Path,
        *,
        workflow_stage: str = "任务准备",
        run_exists: bool = False,
        artifacts_exist: bool = False,
    ) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("JSON root must be an object")
            return value
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise SlimRuntimeError(
                "SLIM_RUN_STORE_INVALID",
                "run_store",
                detail=str(exc),
                workflow_stage=workflow_stage,
                run_exists=run_exists,
                artifacts_exist=artifacts_exist,
                artifacts_preserved=artifacts_exist,
            ) from exc

    @staticmethod
    def _encoded_json(value: dict[str, Any]) -> bytes:
        return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        )

    @classmethod
    def _create_json(
        cls,
        path: Path,
        value: dict[str, Any],
        *,
        error_code: str = "SLIM_VERSION_WRITE_FAILED",
        workflow_stage: str = "任务准备",
        run_exists: bool = False,
        run_created_now: bool = False,
        artifacts_exist: bool = False,
    ) -> None:
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
        try:
            payload = cls._encoded_json(value)
            with temporary.open("xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.link(temporary, path)
        except (OSError, TypeError, ValueError) as exc:
            raise SlimRuntimeError(
                error_code,
                "run_store",
                detail=str(exc),
                workflow_stage=workflow_stage,
                run_exists=run_exists,
                run_created_now=run_created_now,
                artifacts_exist=artifacts_exist,
                artifacts_preserved=artifacts_exist,
            ) from exc
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    @classmethod
    def _create_text(
        cls,
        path: Path,
        value: str,
        *,
        workflow_stage: str,
        run_exists: bool,
        artifacts_exist: bool,
    ) -> None:
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
        try:
            if not isinstance(value, str) or not value:
                raise ValueError("text artifact must be non-empty")
            with temporary.open("xb") as handle:
                handle.write(value.encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
            os.link(temporary, path)
        except (OSError, UnicodeError, TypeError, ValueError) as exc:
            raise SlimRuntimeError(
                "SLIM_VERSION_WRITE_FAILED",
                "run_store",
                detail=str(exc),
                workflow_stage=workflow_stage,
                run_exists=run_exists,
                artifacts_exist=artifacts_exist,
                artifacts_preserved=artifacts_exist,
            ) from exc
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    @classmethod
    def _replace_json(
        cls,
        path: Path,
        value: dict[str, Any],
        *,
        workflow_stage: str = "任务准备",
        run_exists: bool = False,
        run_created_now: bool = False,
        artifacts_exist: bool = False,
    ) -> None:
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
        try:
            payload = cls._encoded_json(value)
            with temporary.open("xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except (OSError, TypeError, ValueError) as exc:
            raise SlimRuntimeError(
                "SLIM_RUN_STORE_INVALID",
                "run_store",
                detail=str(exc),
                workflow_stage=workflow_stage,
                run_exists=run_exists,
                run_created_now=run_created_now,
                artifacts_exist=artifacts_exist,
                artifacts_preserved=artifacts_exist,
            ) from exc
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def _validate_run_id(run_id: Any) -> str:
        if not isinstance(run_id, str) or not RUN_ID_PATTERN.fullmatch(run_id):
            raise SlimRuntimeError(
                "SLIM_RUN_STORE_INVALID", "run_store", detail="invalid run id in index"
            )
        return run_id

    @classmethod
    def _run_dir(cls, root: Path, run_id: Any) -> Path:
        validated = cls._validate_run_id(run_id)
        candidate = root / validated
        try:
            if candidate.is_symlink() or not candidate.is_dir():
                raise ValueError("indexed Run is missing or is a symlink")
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root)
            if resolved.parent != root:
                raise ValueError("indexed Run is outside runs_root")
            return resolved
        except (OSError, ValueError) as exc:
            raise SlimRuntimeError(
                "SLIM_RUN_STORE_INVALID", "run_store", detail=str(exc)
            ) from exc

    @classmethod
    def _load_index(cls, root: Path) -> dict[str, Any]:
        path = root / "run-index.json"
        if not path.exists():
            return {"store_version": "2.0", "tasks": {}}
        if path.is_symlink() or not path.is_file():
            raise SlimRuntimeError(
                "SLIM_RUN_STORE_INVALID", "run_store", detail="invalid run index file"
            )
        index = cls._read_json(path)
        if set(index) != {"store_version", "tasks"} or index["store_version"] != "2.0":
            raise SlimRuntimeError(
                "SLIM_RUN_STORE_INVALID", "run_store", detail="invalid run index"
            )
        tasks = index["tasks"]
        if not isinstance(tasks, dict):
            raise SlimRuntimeError(
                "SLIM_RUN_STORE_INVALID", "run_store", detail="invalid task index"
            )
        seen_run_ids: set[str] = set()
        for digest, run_id in tasks.items():
            if not isinstance(digest, str) or not TASK_DIGEST_PATTERN.fullmatch(digest):
                raise SlimRuntimeError(
                    "SLIM_RUN_STORE_INVALID", "run_store", detail="invalid task digest in index"
                )
            validated = cls._validate_run_id(run_id)
            if validated in seen_run_ids:
                raise SlimRuntimeError(
                    "SLIM_RUN_STORE_INVALID", "run_store", detail="one Run maps to multiple tasks"
                )
            seen_run_ids.add(validated)
        return index

    @classmethod
    def _read_state(cls, root: Path, run_id: Any) -> tuple[dict[str, Any], Path]:
        run_dir = cls._run_dir(root, run_id)
        artifact_dir = run_dir / "artifacts"
        if artifact_dir.is_symlink() or not artifact_dir.is_dir():
            raise SlimRuntimeError(
                "SLIM_RUN_STORE_INVALID",
                "run_store",
                detail="Run artifact directory is missing or is a symlink",
                run_exists=True,
            )
        artifacts_exist = any(artifact_dir.iterdir())
        state_path = run_dir / "state.json"
        if state_path.is_symlink() or not state_path.is_file():
            raise SlimRuntimeError(
                "SLIM_RUN_STORE_INVALID",
                "run_store",
                detail="Run state is missing or is a symlink",
                run_exists=True,
                artifacts_exist=artifacts_exist,
                artifacts_preserved=artifacts_exist,
            )
        state = cls._read_json(
            state_path, run_exists=True, artifacts_exist=artifacts_exist
        )
        if state.get("run_id") != run_dir.name:
            raise SlimRuntimeError(
                "SLIM_RUN_STORE_INVALID",
                "run_store",
                detail="Run state id does not match its directory",
                run_exists=True,
                artifacts_exist=artifacts_exist,
                artifacts_preserved=artifacts_exist,
            )
        return state, run_dir

    @classmethod
    def _find_recovery_candidate(
        cls, root: Path, task_digest: str
    ) -> tuple[dict[str, Any], Path] | None:
        matches: list[tuple[dict[str, Any], Path]] = []
        for child in root.iterdir():
            if child.name in {"run-index.json", LOCK_NAME} or not child.name.startswith("run-"):
                continue
            if not RUN_ID_PATTERN.fullmatch(child.name):
                raise SlimRuntimeError(
                    "SLIM_RUN_STORE_INVALID",
                    "run_store",
                    detail="malformed Run directory blocks safe recovery",
                )
            state, run_dir = cls._read_state(root, child.name)
            if state.get("task_key_sha256") == task_digest:
                matches.append((state, run_dir))
        if len(matches) > 1:
            raise SlimRuntimeError(
                "SLIM_RUN_STORE_INVALID",
                "run_store",
                detail="multiple unindexed Runs match one task",
                run_exists=True,
            )
        return matches[0] if matches else None

    @staticmethod
    def _validate_identity(
        state: dict[str, Any],
        *,
        task_digest: str,
        task_key_generated_by: str,
        task_key_record: str,
        client_id: str,
        speaker_mode: str,
        artifacts_exist: bool = False,
    ) -> None:
        if (
            state.get("task_key_sha256") != task_digest
            or state.get("task_key_generated_by") != task_key_generated_by
            or state.get("task_key_record") != task_key_record
            or state.get("client_id") != client_id
            or state.get("speaker_mode") != speaker_mode
        ):
            raise SlimRuntimeError(
                "SLIM_RUN_STORE_INVALID",
                "run_store",
                detail="task identity mismatch",
                run_exists=True,
                artifacts_exist=artifacts_exist,
                artifacts_preserved=artifacts_exist,
            )

    @classmethod
    def _get_task_locked(
        cls, root: Path, task_digest: str
    ) -> tuple[dict[str, Any], Path]:
        index = cls._load_index(root)
        try:
            run_id = index["tasks"][task_digest]
        except KeyError as exc:
            raise SlimRuntimeError(
                "SLIM_RUN_STORE_INVALID", "run_store", detail="task is not registered"
            ) from exc
        return cls._read_state(root, run_id)

    def start_task(
        self,
        *,
        task_key: str,
        task_key_generated_by: str,
        task_key_record: str,
        client_id: str,
        speaker_mode: str,
    ) -> tuple[dict[str, Any], bool]:
        generator = self._validate_task_key_generator(task_key_generated_by)
        if not isinstance(task_key_record, str) or not task_key_record.strip():
            raise SlimRuntimeError(
                "SLIM_TASK_KEY_UNTRUSTED",
                "run_store",
                detail="task-key persistence record is missing",
            )
        digest = self._task_digest(task_key)
        with self._exclusive_lock() as root:
            index = self._load_index(root)
            existing = index["tasks"].get(digest)
            if existing is not None:
                state, run_dir = self._read_state(root, existing)
                artifacts_exist = any((run_dir / "artifacts").iterdir())
                self._validate_identity(
                    state,
                    task_digest=digest,
                    task_key_generated_by=generator,
                    task_key_record=task_key_record,
                    client_id=client_id,
                    speaker_mode=speaker_mode,
                    artifacts_exist=artifacts_exist,
                )
                return state, False

            recovered = self._find_recovery_candidate(root, digest)
            if recovered is not None:
                state, run_dir = recovered
                self._validate_identity(
                    state,
                    task_digest=digest,
                    task_key_generated_by=generator,
                    task_key_record=task_key_record,
                    client_id=client_id,
                    speaker_mode=speaker_mode,
                    artifacts_exist=any((run_dir / "artifacts").iterdir()),
                )
                artifacts_exist = any((run_dir / "artifacts").iterdir())
                if run_dir.name in index["tasks"].values():
                    raise SlimRuntimeError(
                        "SLIM_RUN_STORE_INVALID",
                        "run_store",
                        detail="recovery candidate is already mapped to another task",
                        run_exists=True,
                        artifacts_exist=artifacts_exist,
                        artifacts_preserved=artifacts_exist,
                    )
                index["tasks"][digest] = run_dir.name
                self._replace_json(
                    root / "run-index.json",
                    index,
                    run_exists=True,
                    artifacts_exist=artifacts_exist,
                )
                return state, False

            run_id = (
                datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%S.%fZ-")
                + secrets.token_hex(4)
            )
            run_dir = root / run_id
            try:
                run_dir.mkdir()
                (run_dir / "artifacts").mkdir()
            except OSError as exc:
                raise SlimRuntimeError(
                    "SLIM_RUN_STORE_INVALID", "run_store", detail=str(exc)
                ) from exc
            state = {
                "run_store_version": "2.0",
                "run_id": run_id,
                "task_key_sha256": digest,
                "task_key_generated_by": generator,
                "task_key_record": task_key_record,
                "task_key_retry_policy": "reuse_persisted_record_and_digest",
                "client_id": client_id,
                "speaker_mode": speaker_mode,
                "state": "started",
                "blocked_resume_state": None,
                "created_at": _now(),
                "updated_at": _now(),
            }
            self._create_json(
                run_dir / "state.json",
                state,
                error_code="SLIM_RUN_STORE_INVALID",
                run_exists=True,
                run_created_now=True,
            )
            index["tasks"][digest] = run_id
            try:
                self._replace_json(
                    root / "run-index.json",
                    index,
                    run_exists=True,
                    run_created_now=True,
                )
            except OSError as exc:
                raise SlimRuntimeError(
                    "SLIM_RUN_STORE_INVALID",
                    "run_store",
                    detail=str(exc),
                    run_exists=True,
                    run_created_now=True,
                ) from exc
            return state, True

    def start_program_task(
        self,
        *,
        business_identity: dict[str, Any],
        client_id: str,
        speaker_mode: str,
    ) -> tuple[dict[str, Any], bool, str]:
        task_key, record = self.resolve_program_task_key(business_identity)
        state, created = self.start_task(
            task_key=task_key,
            task_key_generated_by="deterministic_program",
            task_key_record=record,
            client_id=client_id,
            speaker_mode=speaker_mode,
        )
        return state, created, task_key

    def get_task(self, task_key: str) -> dict[str, Any]:
        digest = self._task_digest(task_key)
        with self._exclusive_lock() as root:
            state, _ = self._get_task_locked(root, digest)
            return state

    def artifacts_exist(self, task_key: str) -> bool:
        digest = self._task_digest(task_key)
        with self._exclusive_lock() as root:
            _, run_dir = self._get_task_locked(root, digest)
            return any((run_dir / "artifacts").iterdir())

    def run_directory(self, task_key: str) -> Path:
        digest = self._task_digest(task_key)
        with self._exclusive_lock() as root:
            _, run_dir = self._get_task_locked(root, digest)
            return run_dir

    def freeze_task_input(self, task_key: str, payload: dict[str, Any]) -> Path:
        digest = self._task_digest(task_key)
        with self._exclusive_lock() as root:
            state, run_dir = self._get_task_locked(root, digest)
            input_dir = run_dir / "input"
            try:
                input_dir.mkdir(exist_ok=True)
                if input_dir.is_symlink() or not input_dir.is_dir():
                    raise ValueError("Run input directory must be a real directory")
            except (OSError, ValueError) as exc:
                raise SlimRuntimeError(
                    "SLIM_RUN_STORE_INVALID",
                    "run_store",
                    detail=str(exc),
                    run_exists=True,
                    artifacts_exist=any((run_dir / "artifacts").iterdir()),
                ) from exc
            target = input_dir / "task_input.json"
            if target.exists():
                existing = self._read_json(target, run_exists=True)
                if existing != payload:
                    raise SlimRuntimeError(
                        "SLIM_TASK_IDENTITY_CHANGED",
                        "run_store",
                        detail="frozen task input differs from retry input",
                        workflow_stage=SlimStateMachine.user_label(state["state"]),
                        run_exists=True,
                        artifacts_exist=any((run_dir / "artifacts").iterdir()),
                        artifacts_preserved=any((run_dir / "artifacts").iterdir()),
                    )
                return target
            self._create_json(
                target,
                payload,
                error_code="SLIM_RUN_STORE_INVALID",
                run_exists=True,
                run_created_now=False,
                artifacts_exist=any((run_dir / "artifacts").iterdir()),
            )
            return target

    def read_task_input(self, task_key: str) -> dict[str, Any]:
        run_dir = self.run_directory(task_key)
        target = run_dir / "input" / "task_input.json"
        if target.is_symlink() or not target.is_file():
            raise SlimRuntimeError(
                "SLIM_RUN_STORE_INVALID",
                "run_store",
                detail="frozen task input is missing",
                run_exists=True,
                artifacts_exist=self.artifacts_exist(task_key),
                artifacts_preserved=self.artifacts_exist(task_key),
            )
        return self._read_json(target, run_exists=True)

    def write_fixed_json(
        self, task_key: str, filename: str, payload: dict[str, Any]
    ) -> Path:
        if not FIXED_JSON_NAME_PATTERN.fullmatch(filename):
            raise SlimRuntimeError(
                "SLIM_VERSION_WRITE_FAILED", "run_store", detail="invalid fixed artifact name"
            )
        digest = self._task_digest(task_key)
        with self._exclusive_lock() as root:
            state, run_dir = self._get_task_locked(root, digest)
            artifact_dir = run_dir / "artifacts"
            target = artifact_dir / filename
            existing_artifacts = list(artifact_dir.iterdir())
            if target.exists():
                existing = self._read_json(
                    target,
                    workflow_stage=SlimStateMachine.user_label(state["state"]),
                    run_exists=True,
                    artifacts_exist=True,
                )
                if existing != payload:
                    raise SlimRuntimeError(
                        "SLIM_VERSION_WRITE_FAILED",
                        "run_store",
                        detail="create-only artifact already exists with different content",
                        workflow_stage=SlimStateMachine.user_label(state["state"]),
                        run_exists=True,
                        artifacts_exist=True,
                        artifacts_preserved=True,
                    )
                return target
            self._create_json(
                target,
                payload,
                workflow_stage=SlimStateMachine.user_label(state["state"]),
                run_exists=True,
                artifacts_exist=bool(existing_artifacts),
            )
            return target

    def read_fixed_json(self, task_key: str, filename: str) -> dict[str, Any]:
        if not FIXED_JSON_NAME_PATTERN.fullmatch(filename):
            raise SlimRuntimeError(
                "SLIM_RUN_STORE_INVALID", "run_store", detail="invalid fixed artifact name"
            )
        run_dir = self.run_directory(task_key)
        target = run_dir / "artifacts" / filename
        if target.is_symlink() or not target.is_file():
            raise SlimRuntimeError(
                "SLIM_RUN_STORE_INVALID",
                "run_store",
                detail="required artifact is missing",
                run_exists=True,
                artifacts_exist=self.artifacts_exist(task_key),
                artifacts_preserved=self.artifacts_exist(task_key),
            )
        return self._read_json(target, run_exists=True, artifacts_exist=True)

    def latest_version(self, task_key: str, artifact_name: str) -> tuple[int, dict[str, Any], Path]:
        if not ARTIFACT_NAME_PATTERN.fullmatch(artifact_name):
            raise SlimRuntimeError(
                "SLIM_RUN_STORE_INVALID", "run_store", detail="invalid artifact name"
            )
        run_dir = self.run_directory(task_key)
        pattern = re.compile(rf"^{re.escape(artifact_name)}_v(\d+)\.json$")
        versions = sorted(
            (int(match.group(1)), child)
            for child in (run_dir / "artifacts").iterdir()
            if (match := pattern.fullmatch(child.name)) is not None
        )
        if not versions:
            raise SlimRuntimeError(
                "SLIM_RUN_STORE_INVALID",
                "run_store",
                detail=f"no {artifact_name} version exists",
                run_exists=True,
                artifacts_exist=self.artifacts_exist(task_key),
                artifacts_preserved=self.artifacts_exist(task_key),
            )
        version, path = versions[-1]
        return version, self._read_json(path, run_exists=True, artifacts_exist=True), path

    def transition(self, task_key: str, target: str) -> dict[str, Any]:
        digest = self._task_digest(task_key)
        with self._exclusive_lock() as root:
            state, run_dir = self._get_task_locked(root, digest)
            current = state["state"]
            artifacts_exist = any((run_dir / "artifacts").iterdir())
            SlimStateMachine.ensure_transition(
                current,
                target,
                blocked_resume_state=state.get("blocked_resume_state"),
                artifacts_exist=artifacts_exist,
            )
            state["blocked_resume_state"] = current if target == "blocked" else None
            state["state"] = target
            state["updated_at"] = _now()
            self._replace_json(
                run_dir / "state.json",
                state,
                workflow_stage=SlimStateMachine.user_label(current),
                run_exists=True,
                artifacts_exist=artifacts_exist,
            )
            return state

    def write_version(
        self, task_key: str, artifact_name: str, payload: dict[str, Any]
    ) -> Path:
        digest = self._task_digest(task_key)
        with self._exclusive_lock() as root:
            state, run_dir = self._get_task_locked(root, digest)
            artifact_dir = run_dir / "artifacts"
            existing_artifacts = list(artifact_dir.iterdir())
            if not ARTIFACT_NAME_PATTERN.fullmatch(artifact_name):
                raise SlimRuntimeError(
                    "SLIM_VERSION_WRITE_FAILED",
                    "run_store",
                    detail="invalid artifact name",
                    workflow_stage=SlimStateMachine.user_label(state["state"]),
                    run_exists=True,
                    artifacts_exist=bool(existing_artifacts),
                    artifacts_preserved=bool(existing_artifacts),
                )
            version_pattern = re.compile(rf"^{re.escape(artifact_name)}_v(\d+)\.json$")
            versions = [
                int(match.group(1))
                for child in existing_artifacts
                if (match := version_pattern.fullmatch(child.name)) is not None
            ]
            target = artifact_dir / f"{artifact_name}_v{max(versions, default=0) + 1}.json"
            self._create_json(
                target,
                payload,
                workflow_stage=SlimStateMachine.user_label(state["state"]),
                run_exists=True,
                artifacts_exist=bool(existing_artifacts),
            )
            return target

    def write_version_bundle(
        self,
        task_key: str,
        artifact_name: str,
        *,
        expected_version: int,
        json_payload: dict[str, Any],
        markdown_text: str,
    ) -> tuple[Path, Path]:
        """Create one JSON/Markdown version pair without overwriting either file."""

        digest = self._task_digest(task_key)
        with self._exclusive_lock() as root:
            state, run_dir = self._get_task_locked(root, digest)
            artifact_dir = run_dir / "artifacts"
            existing_artifacts = list(artifact_dir.iterdir())
            if not ARTIFACT_NAME_PATTERN.fullmatch(artifact_name):
                raise SlimRuntimeError(
                    "SLIM_VERSION_WRITE_FAILED",
                    "run_store",
                    detail="invalid artifact name",
                    workflow_stage=SlimStateMachine.user_label(state["state"]),
                    run_exists=True,
                    artifacts_exist=bool(existing_artifacts),
                    artifacts_preserved=bool(existing_artifacts),
                )
            version_pattern = re.compile(rf"^{re.escape(artifact_name)}_v(\d+)\.json$")
            versions = [
                int(match.group(1))
                for child in existing_artifacts
                if (match := version_pattern.fullmatch(child.name)) is not None
            ]
            actual_version = max(versions, default=0) + 1
            if expected_version != actual_version:
                raise SlimRuntimeError(
                    "SLIM_VERSION_WRITE_FAILED",
                    "run_store",
                    detail=(
                        f"expected {artifact_name}_v{expected_version}, "
                        f"next is v{actual_version}"
                    ),
                    workflow_stage=SlimStateMachine.user_label(state["state"]),
                    run_exists=True,
                    artifacts_exist=bool(existing_artifacts),
                    artifacts_preserved=bool(existing_artifacts),
                )
            json_target = artifact_dir / f"{artifact_name}_v{actual_version}.json"
            markdown_target = artifact_dir / f"{artifact_name}_v{actual_version}.md"
            created: list[Path] = []
            try:
                self._create_json(
                    json_target,
                    json_payload,
                    workflow_stage=SlimStateMachine.user_label(state["state"]),
                    run_exists=True,
                    artifacts_exist=bool(existing_artifacts),
                )
                created.append(json_target)
                self._create_text(
                    markdown_target,
                    markdown_text,
                    workflow_stage=SlimStateMachine.user_label(state["state"]),
                    run_exists=True,
                    artifacts_exist=True,
                )
                created.append(markdown_target)
            except SlimRuntimeError:
                for target in created:
                    try:
                        target.unlink(missing_ok=True)
                    except OSError:
                        pass
                raise
            return json_target, markdown_target
