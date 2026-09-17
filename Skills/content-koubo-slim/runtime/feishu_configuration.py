"""Preview and apply a narrow Koubo addition to an existing Feishu binding."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import secrets

from .content_source import (WORKFLOW, _canonical, default_common_registry_path,
    load_common_registry, select_profile, validate_common_registry, validate_profile_index)
from .error_model import SlimRuntimeError
from .feishu_binding import space_from_binding, verify_remote_manifest


def plan_feishu_configuration(*, registry_path=None, binding_id, profile=None):
    from .feishu_source import FeishuDocument, remote_json
    from .vault_reader import read_selected_profile
    from .feishu_source import FeishuRoot
    path = Path(registry_path) if registry_path else default_common_registry_path()
    current, registry_digest = load_common_registry(path)
    binding = current['bindings'].get(binding_id)
    if not binding or binding['backend'] != 'feishu' or binding['status'] != 'active':
        raise SlimRuntimeError('SLIM_CLIENT_NOT_CONFIGURED', 'feishu_configuration', detail='select an existing active Feishu binding')
    space = space_from_binding(binding)
    manifest, manifest_digest = remote_json(FeishuDocument(space, binding['manifest_ref']))
    candidate = copy.deepcopy(manifest)
    candidate['supported_workflows'] = sorted(set(candidate['supported_workflows']) | {WORKFLOW})
    candidate['workflow_outputs'].setdefault(WORKFLOW, 'content-koubo-slim/{profile_id}/weekly')
    if candidate != manifest:
        candidate['revision'] += 1
    verify_remote_manifest(space, binding, candidate)
    index, index_digest = remote_json(FeishuDocument(space, binding['profile_index_ref']))
    validate_profile_index(index, knowledge_base_id=binding['knowledge_base_id'])
    selected = select_profile(index, requested=profile,
        configured_default=binding['workflow_defaults'].get(WORKFLOW, {}).get('profile_id'))
    read_selected_profile(FeishuRoot(space, candidate['asset_roots']['profiles'], 'profile'), selected)
    updated = copy.deepcopy(current)
    target = updated['bindings'][binding_id]
    target['supported_workflows'] = sorted(set(target['supported_workflows']) | {WORKFLOW})
    target['workflow_defaults'][WORKFLOW] = {'profile_id': selected['profile_id'], 'use_no_ip': False}
    updated['workflow_defaults'].setdefault(WORKFLOW, binding_id)
    if updated != current:
        updated['revision'] += 1
    validate_common_registry(updated)
    identity = dict(registry_sha256=registry_digest, manifest_sha256=manifest_digest,
        index_sha256=index_digest, manifest=candidate, registry=updated)
    confirmation = hashlib.sha256(_canonical(identity)).hexdigest()[:24]
    return dict(preview=dict(backend='feishu', knowledge_base_name=candidate['knowledge_base_name'],
        profile_display_name=selected['display_name'], output_template=candidate['workflow_outputs'][WORKFLOW],
        outputs=['口播稿', '配套文案'], manifest_action='reuse' if candidate == manifest else 'merge',
        registry_action='reuse' if updated == current else 'merge', wrote=False),
        confirmation=confirmation, manifest=candidate, registry=updated, registry_sha256=registry_digest,
        manifest_sha256=manifest_digest, profile_index_sha256=index_digest)


def apply_feishu_configuration(*, registry_path=None, binding_id, profile=None, confirmation):
    from .feishu_source import FeishuDocument, remote_json
    plan = plan_feishu_configuration(registry_path=registry_path, binding_id=binding_id, profile=profile)
    if confirmation != plan['confirmation']:
        raise SlimRuntimeError('SLIM_MANIFEST_INVALID', 'feishu_configuration', detail='configuration changed since the reviewed preview')
    path = Path(registry_path) if registry_path else default_common_registry_path()
    binding = plan['registry']['bindings'][binding_id]
    space = space_from_binding(binding)
    document = FeishuDocument(space, binding['manifest_ref'])
    _, remote_digest = remote_json(document)
    if remote_digest != plan['manifest_sha256'] or hashlib.sha256(path.read_bytes()).hexdigest() != plan['registry_sha256']:
        raise SlimRuntimeError('SLIM_MANIFEST_INVALID', 'feishu_configuration', detail='configuration drift before apply')
    if plan['preview']['manifest_action'] == 'merge':
        body = '# content-source-manifest\n\n```json\n' + json.dumps(plan['manifest'], ensure_ascii=False, indent=2) + '\n```\n'
        space.client.replace_document(binding['manifest_ref'], body)
    actual, _ = remote_json(document)
    if actual != plan['manifest']:
        raise SlimRuntimeError('SLIM_MANIFEST_INVALID', 'feishu_configuration', detail='remote Manifest readback differs')
    # If a local failure follows the remote merge, rerunning the preview safely
    # reuses the remote result and completes only the missing Registry merge.
    if path.is_symlink() or path.parent.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != plan['registry_sha256']:
        raise SlimRuntimeError('SLIM_REGISTRY_NOT_READABLE', 'feishu_configuration', detail='Registry changed during remote update')
    temporary = path.with_name('.' + path.name + '.' + secrets.token_hex(8) + '.tmp')
    payload = _canonical(plan['registry'])
    try:
        with temporary.open('xb') as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if path.read_bytes() != payload:
            raise SlimRuntimeError('SLIM_REGISTRY_NOT_READABLE', 'feishu_configuration', detail='Registry readback differs')
    finally:
        temporary.unlink(missing_ok=True)
    return dict(status='configured', **{**plan['preview'], 'wrote': True}, readback='verified')
