"""Resolve an explicitly configured Feishu binding without local mirrors."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from .error_model import SlimRuntimeError


def space_from_binding(binding):
    from . import feishu_source
    try:
        locator = binding['locator']['knowledge_base_ref']
        url = urlsplit(locator)
        if url.scheme != 'https' or url.username or url.password or not url.hostname:
            raise ValueError('Feishu locator must be an HTTPS Wiki space URL')
        if not (url.hostname == 'feishu.cn' or url.hostname.endswith('.feishu.cn')
                or url.hostname == 'larksuite.com' or url.hostname.endswith('.larksuite.com')):
            raise ValueError('Feishu locator host is unsupported')
        match = re.fullmatch(r'/wiki/space/([0-9]+)/?', url.path)
        if not match:
            raise ValueError('Feishu binding needs an explicit Wiki space URL')
        return feishu_source.FeishuSpace(locator, match[1], feishu_source.get_client())
    except (KeyError, TypeError, ValueError) as exc:
        raise SlimRuntimeError('SLIM_CLIENT_NOT_CONFIGURED', 'feishu_binding', detail=str(exc)) from exc


def verify_remote_manifest(space, binding, data):
    from .content_source import validate_common_manifest
    from .feishu_source import assert_below
    validate_common_manifest(data, expected=binding)
    if data['locator'] != space.locator or data['profile_index_ref'] != binding['profile_index_ref']:
        raise SlimRuntimeError('SLIM_MANIFEST_INVALID', 'feishu_binding', detail='Registry/Manifest locator or index differs')
    roots = data['asset_roots']
    # Resolve each role to a genuine node in the selected space. An output
    # nested beneath a source root is forbidden, even with a different token.
    canonical = {}
    for role, ref in roots.items():
        node = assert_below(space, ref, ref)
        if node is None:
            node = space.client.get_node(ref)
        canonical[role] = node['node_token']
    if len(set(canonical.values())) != len(canonical):
        raise SlimRuntimeError('SLIM_MANIFEST_INVALID', 'feishu_binding', detail='logical roots alias the same node')
    for role, ref in canonical.items():
        seen = set()
        current = space.client.get_node(ref)
        while current.get('parent_node_token'):
            parent = current['parent_node_token']
            if parent in seen or len(seen) >= 64:
                raise SlimRuntimeError('SLIM_MANIFEST_INVALID', 'feishu_binding', detail='root ancestry is cyclic or too deep')
            if parent in canonical.values():
                raise SlimRuntimeError('SLIM_MANIFEST_INVALID', 'feishu_binding', detail='logical roots overlap')
            seen.add(parent)
            current = space.client.get_node(parent)
            if current.get('space_id') != space.space_id or current.get('node_type', 'origin') != 'origin':
                raise SlimRuntimeError('SLIM_MANIFEST_INVALID', 'feishu_binding', detail='root ancestry leaves this space')
    assert_below(space, binding['manifest_ref'], roots['workflow'])
    assert_below(space, binding['profile_index_ref'], roots['workflow'])


def resolve_feishu_binding(registry, binding):
    from .client_registry import ClientLocation
    from .content_source import WORKFLOW
    from .feishu_source import FeishuDocument, remote_json
    if binding.get('status') != 'active' or WORKFLOW not in binding.get('supported_workflows', []):
        raise SlimRuntimeError('SLIM_CLIENT_NOT_CONFIGURED', 'feishu_binding', detail='Feishu binding is not enabled for Koubo')
    space = space_from_binding(binding)
    document = FeishuDocument(space, binding['manifest_ref'])
    data, digest = remote_json(document)
    verify_remote_manifest(space, binding, data)
    document = FeishuDocument(space, binding['manifest_ref'], expected_sha256=digest)
    default = binding.get('workflow_defaults', {}).get(WORKFLOW, {})
    return ClientLocation(client_id=binding['client_id'], vault_root=space, manifest_path=document,
        binding_id=binding['binding_id'], knowledge_base_id=binding['knowledge_base_id'],
        backend_type='feishu', profile_index_path=FeishuDocument(space, binding['profile_index_ref']),
        default_profile_id=default.get('profile_id'), registry_sha256=registry.get('_registry_sha256'),
        common_contract=True)
