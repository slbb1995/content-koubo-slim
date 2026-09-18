"""Independent deliverables, immutable batch plans, and verified progress.

The host interprets the requested quantity and item angles. This module validates
that structured plan; it does not infer intent from Chinese number expressions.
"""
from __future__ import annotations

import hashlib
import json
import re
import tempfile
from pathlib import Path
from uuid import UUID
from .error_model import SlimRuntimeError
from .run_store import RunStore
from .client_manifest import load_manifest, resolve_asset_root


def _fail(detail):
    raise SlimRuntimeError("SLIM_ANALYZER_INPUT_INVALID", "batch_tasks", detail=detail,
        workflow_stage="正在准备多篇口播", recovery_action="核对本次需要的篇数和逐篇安排，再继续原批次；不要把多篇合并为一篇。")


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), default=str).encode()).hexdigest()


def _batch_id(value):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError()
    except (ValueError, AttributeError):
        _fail("batch_id must be a canonical UUID generated once and reused on retries")
    return value


def validate_single_request(output_count, batch_item=None):
    if type(output_count) is not int or output_count != 1:
        _fail("a single Run must contain exactly one deliverable; use a batch plan")
    if batch_item is not None:
        if not isinstance(batch_item, dict) or set(batch_item) != {"batch_id", "item_id"}:
            _fail("invalid batch item identity")
        _batch_id(batch_item["batch_id"])
        if not isinstance(batch_item["item_id"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", batch_item["item_id"]):
            _fail("invalid batch item_id")


def batch_item_digest(item):
    validate_single_request(1, item)
    return _digest(item)


def save_suffix(item):
    if item is None:
        return None
    validate_single_request(1, item)
    return f"{item['item_id']}-{UUID(item['batch_id']).hex}"


def validate_plan(plan, output_count):
    if type(output_count) is not int or output_count < 2:
        _fail("a batch needs at least two independent deliverables")
    if not isinstance(plan, dict) or set(plan) != {"batch_id", "output_count", "items"}:
        _fail("batch plan fields are invalid")
    _batch_id(plan["batch_id"])
    if type(plan["output_count"]) is not int or plan["output_count"] != output_count:
        _fail("batch plan count differs from requested output_count")
    if not isinstance(plan["items"], list) or len(plan["items"]) != output_count:
        _fail("batch item count differs from requested output_count")
    ids = set()
    for item in plan["items"]:
        if not isinstance(item, dict) or not {"item_id"} <= set(item) or set(item) - {"item_id", "user_thoughts"}:
            _fail("batch item fields are invalid")
        validate_single_request(1, {"batch_id": plan["batch_id"], "item_id": item["item_id"]})
        if item["item_id"] in ids:
            _fail("batch item ids must be unique")
        ids.add(item["item_id"])
        if "user_thoughts" in item and (not isinstance(item["user_thoughts"], str) or not item["user_thoughts"].strip()):
            _fail("per-item direction must be nonempty text")
    return plan


def _batch_path(root, batch_id):
    directory = root / "batches"
    directory.mkdir(exist_ok=True)
    if directory.is_symlink() or not directory.is_dir():
        _fail("batch directory must be a real directory")
    return directory / (_batch_id(batch_id) + ".json")


def start_request(prepare, request, *, output_count=1, plan_path=None):
    if plan_path is None:
        validate_single_request(output_count)
        response, record = prepare(**request)
        return {**response, "task_record": record}
    try:
        plan = validate_plan(json.loads(Path(plan_path).read_text(encoding="utf-8")), output_count)
    except (OSError, UnicodeError, ValueError) as exc:
        _fail(f"cannot read batch plan: {exc}")
    store = RunStore(request["runs_root"])
    requests, previews = [], []
    # Fully validate every initial Analyzer input in disposable staging before any
    # real batch/Run is created. File/permission failures during real writes remain
    # recoverable through the same immutable plan; no completion is inferred.
    with tempfile.TemporaryDirectory(prefix="koubo-batch-preflight-") as stage:
        for item in plan["items"]:
            args = dict(request)
            identity = {"batch_id": plan["batch_id"], "item_id": item["item_id"]}
            args["batch_item"] = identity
            if "user_thoughts" in item:
                args["user_thoughts"] = "\n".join(filter(None, [request.get("user_thoughts"), item["user_thoughts"]]))
            staging_args = {**args, "runs_root": str(Path(stage) / "runs")}
            _, record = prepare(**staging_args)
            temporary_store = RunStore(staging_args["runs_root"])
            key = temporary_store.resolve_task_record(record)
            frozen = temporary_store.read_task_input(key)
            previews.append({"item_id": item["item_id"], "task_record": record,
                "frozen_input_sha256": _digest(frozen)})
            requests.append(args)
    manifest = {"contract_version": "content-koubo-batch-v1", "plan": plan,
        "request_sha256": _digest(request), "items": previews}
    with store._exclusive_lock() as root:
        path = _batch_path(root, plan["batch_id"])
        if path.is_symlink():
            _fail("batch manifest cannot be a symlink")
        if path.exists():
            if store._read_json(path) != manifest:
                _fail("batch plan or its frozen client/source/input changed; preserve existing batch")
        else:
            store._create_json(path, manifest)
    for args, preview in zip(requests, previews):
        _, record = prepare(**args)
        if record != preview["task_record"]:
            _fail("batch input changed during initialization; retry with original frozen sources")
        key = store.resolve_task_record(record)
        if _digest(store.read_task_input(key)) != preview["frozen_input_sha256"]:
            _fail("batch frozen input differs from its preflight snapshot")
    return batch_status(store, plan["batch_id"])


def _verified_pair(store, key):
    version, _, _ = store.latest_version(key, "draft")
    receipt = store.read_fixed_json(key, f"saved_pair_v{version}.json")
    frozen = store.read_task_input(key)
    if frozen.get("backend_type") == "feishu":
        from .feishu_binding import space_from_binding
        from .feishu_source import FeishuDocument
        from .feishu_save import verify_saved_feishu_pair
        space = space_from_binding({"locator": {"knowledge_base_ref": frozen["vault_root_resolved"]}})
        manifest = load_manifest(FeishuDocument(space, frozen["manifest_path_resolved"]), expected_client_id=frozen["client_id"])
        if manifest.manifest_sha256 != frozen.get("manifest_sha256"):
            return False
        return verify_saved_feishu_pair(
            output_root=resolve_asset_root(space, manifest, "output"),
            output_template=manifest.output_template,
            receipt_dir=store.run_directory(key) / "feishu-save" / f"v{version}",
            expected_result=receipt, draft_version=version,
            item_suffix=save_suffix(frozen.get("batch_item")))
    from .client_registry import _reject_reparse
    _reject_reparse(Path(frozen["vault_root_resolved"]))
    vault = Path(frozen["vault_root_resolved"]).resolve(strict=True)
    manifest = load_manifest(Path(frozen["manifest_path_resolved"]), expected_client_id=frozen["client_id"])
    authorized = resolve_asset_root(vault, manifest, "output").resolve(strict=True)
    for kind in ("oral", "package"):
        path = Path(receipt[f"{kind}_path"])
        _reject_reparse(path)
        if not path.is_absolute() or ".." in path.parts or path.is_symlink() or not path.is_file():
            return False
        if authorized not in path.parents:
            return False
        path.resolve(strict=True).relative_to(authorized)
        # Reject symlink ancestors inside the vault as well as the leaf.
        current = path
        while current != authorized:
            if current.is_symlink():
                return False
            current = current.parent
        if hashlib.sha256(path.read_bytes()).hexdigest() != receipt[f"{kind}_sha256"]:
            return False
    return receipt.get("publish_status") == "not_requested"


def batch_status(store, batch_id):
    with store._exclusive_lock() as root:
        path = _batch_path(root, batch_id)
        if path.is_symlink() or not path.is_file():
            _fail("batch does not exist")
        manifest = store._read_json(path)
    plan = validate_plan(manifest.get("plan"), manifest.get("plan", {}).get("output_count"))
    if plan["batch_id"] != batch_id or len(manifest.get("items", [])) != plan["output_count"]:
        _fail("batch manifest identity or count is invalid")
    items = []
    for expected, item in zip(plan["items"], manifest["items"]):
        if item.get("item_id") != expected["item_id"]:
            _fail("batch manifest item order is invalid")
        result = {"item_id": item["item_id"], "task_record": item["task_record"],
            "state": "not_started", "saved_verified": False}
        try:
            key = store.resolve_task_record(item["task_record"])
            state = store.get_task(key)
            frozen = store.read_task_input(key)
            if _digest(frozen) != item["frozen_input_sha256"]:
                result["state"] = "input_changed"
            else:
                result["state"] = state["state"]
                if state["state"] == "saved":
                    result["saved_verified"] = _verified_pair(store, key)
                    if not result["saved_verified"]:
                        result["state"] = "saved_files_changed"
        except (SlimRuntimeError, OSError, ValueError, KeyError):
            result["state"] = "incomplete_or_unverifiable"
        items.append(result)
    count = sum(item["saved_verified"] for item in items)
    return {"status": "completed" if count == plan["output_count"] else "working",
        "batch_id": batch_id, "output_count": plan["output_count"], "saved_count": count,
        "message": f"已核验保存 {count}/{plan['output_count']} 篇，每篇独立确认和保存。",
        "items": items, "publish_status": "not_requested"}
