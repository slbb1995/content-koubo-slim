"""Create-only oral/package save, with durable receipts and conservative recovery.

Wiki directories are ordinary origin docx nodes. An unacknowledged create is
never adopted by title alone: leave pending for manual reconciliation. Reuse the
same receipt_dir on every retry. A stale lock after process death fails closed.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .error_model import SlimRuntimeError
from .feishu_client import canonical_markdown, document_body_variants
from .vault_save import _versioned_stem, _render_template

if TYPE_CHECKING:
    from .feishu_source import FeishuRoot


def _fail(detail):
    raise SlimRuntimeError('SLIM_SAVE_FAILED', 'feishu_save', detail=detail,
                           run_exists=True, artifacts_exist=True, artifacts_preserved=True,
                           workflow_stage='等待你确认并保存')


def _sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _persist(path, state):
    temporary = path.with_suffix('.tmp')
    if temporary.is_symlink() or path.is_symlink():
        _fail('Unsafe receipt path')
    with temporary.open('w', encoding='utf-8', newline='\n') as handle:
        json.dump(state, handle, ensure_ascii=False, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def save_feishu_pair(*, output_root: FeishuRoot, output_template, client_id,
                     selected_publish_title, oral_body, package_markdown,
                     receipt_dir: Path, now=None, draft_version=1, item_suffix=None) -> dict:
    """Return token refs and SHA256 only after both remote bodies match."""
    lock = None
    try:
        if output_root.logical_name != 'output':
            _fail('Only the Manifest output root is writable')
        if any(not isinstance(body, str) or not body.strip() for body in (oral_body, package_markdown)):
            _fail('Approved content is empty')
        stem = _versioned_stem(selected_publish_title, draft_version, item_suffix)
        client, space_id = output_root.client, output_root.space_id

        def check_node(node, *, token=None, parent=None, title=None):
            if (node.get('space_id') != space_id or node.get('node_type') != 'origin'
                    or node.get('obj_type') != 'docx' or not node.get('obj_token')
                    or not node.get('node_token') or (token is not None and node['node_token'] != token)
                    or (parent is not None and node.get('parent_node_token') != parent)
                    or (title is not None and node.get('title') != title)):
                _fail('Remote node moved, changed, or is outside authorized origin nodes')
            return node

        root = check_node(client.get_node(output_root.token), token=output_root.token)
        bodies = [canonical_markdown(oral_body), canonical_markdown(package_markdown)]
        titles = [stem + '-口播稿', stem + '-配套文案']
        request = dict(space_id=space_id, root=root['node_token'],
                       draft_version=draft_version, item_suffix=item_suffix,
                       client_id=client_id, titles=titles, sha=[_sha(body) for body in bodies])
        receipt_dir = Path(receipt_dir)
        if receipt_dir.is_symlink() or any(p.is_symlink() for p in receipt_dir.parents):
            _fail('Receipt directory must not use symlinks')
        receipt_dir.mkdir(parents=True, exist_ok=True)
        lock_path = receipt_dir / 'feishu-save.lock'
        lock = lock_path.open('x')
        path = receipt_dir / 'feishu-save.json'
        if path.is_symlink():
            _fail('Receipt is a symlink')
        if path.exists():
            state = json.loads(path.read_text(encoding='utf-8'))
            if (not isinstance(state, dict) or not isinstance(state.get('request'), dict)
                    or not isinstance(state.get('entries'), dict)):
                _fail('Receipt is invalid')
            frozen = state['request']
            if frozen.get('output_template') != output_template:
                _fail('Output template differs from the frozen save request')
            # Missing/malformed timestamps fail closed; never infer a new date
            # for an existing receipt or redirect its acknowledged documents.
            timestamp = datetime.fromisoformat(frozen['timestamp'])
        else:
            state = None
            timestamp = now or datetime.now().astimezone()
        relative = _render_template(output_template, client_id, timestamp)
        request.update(output_template=output_template, timestamp=timestamp.isoformat(),
                       relative=relative.as_posix())
        if state is not None:
            # Re-render using ONLY the frozen timestamp to check the stored
            # destination's integrity while preserving it across date boundaries.
            if state['request'] != request:
                _fail('Receipt is invalid or belongs to different approved content')
        else:
            state = dict(request=request, entries={})
            _persist(path, state)

        def matches(parent, title):
            children = client.list_children(space_id, parent)
            found = [n for n in children if n.get('title') == title]
            if len(found) > 1:
                _fail('Ambiguous duplicate remote titles')
            return found

        def ensure(key, parent, title, body, folder=False):
            entry = state['entries'].get(key)
            if entry is None:
                existing = matches(parent, title)
                if existing:
                    if not folder:
                        _fail('Unrelated existing document title')
                    node = check_node(client.get_node(existing[0]['node_token']), parent=parent, title=title)
                    entry = dict(status='reused', refs=node)
                    state['entries'][key] = entry
                    _persist(path, state)
                else:
                    entry = dict(status='pending')
                    state['entries'][key] = entry
                    _persist(path, state)  # durable intent MUST precede remote mutation
                    try:
                        refs = client.create_document(parent, title, body)
                    except Exception as exc:
                        if getattr(exc, 'received_refs', None):
                            entry.update(status='received', refs=exc.received_refs)
                            _persist(path, state)
                        _fail('Create stopped; preserve receipt for reconciliation: ' + str(exc))
                    entry.update(status='received', refs=refs)
                    _persist(path, state)  # preserve acknowledgement before any reads
            if entry.get('status') == 'pending' or not isinstance(entry.get('refs'), dict):
                _fail('Unacknowledged create: reconcile manually; never recreate or adopt by title')
            refs = entry['refs']
            ref = refs.get('node_token') or refs.get('obj_token')
            node = check_node(client.get_node(ref), token=refs.get('node_token'), parent=parent, title=title)
            if node['obj_token'] != refs.get('obj_token'):
                _fail('Receipt object identity changed')
            found = matches(parent, title)
            if len(found) != 1 or found[0].get('node_token') != node['node_token']:
                _fail('Acknowledged document is not the unique child at its saved location')
            if entry['status'] != 'reused':
                actual = canonical_markdown(client.fetch_markdown(node['obj_token']))
                # CLI versions may include the document title in their Markdown.
                if canonical_markdown(body) not in document_body_variants(actual, title):
                    _fail('Remote Markdown readback does not match approved content')
                entry['status'] = 'verified'
            entry['refs'] = node
            _persist(path, state)
            return node

        parent = root['node_token']
        for index, part in enumerate(relative.parts):
            parent = ensure('folder:' + str(index), parent, part, '# ' + part + '\n', folder=True)['node_token']
        # Preflight BOTH names before creating either final document.
        for key, title in zip(('oral', 'package'), titles):
            if key not in state['entries'] and matches(parent, title):
                _fail('Unrelated existing document title')
        oral = ensure('oral', parent, titles[0], bodies[0])
        package = ensure('package', parent, titles[1], bodies[1])
        if oral['node_token'] == package['node_token'] or oral['obj_token'] == package['obj_token']:
            _fail('The two outputs must be distinct documents')
        # Recheck ancestors and both outputs after all writes.
        check_node(client.get_node(root['node_token']), token=root['node_token'])
        ancestor = root['node_token']
        for index, part in enumerate(relative.parts):
            node = state['entries']['folder:' + str(index)]['refs']
            check_node(client.get_node(node['node_token']), token=node['node_token'], parent=ancestor, title=part)
            ancestor = node['node_token']
        ensure('oral', parent, titles[0], bodies[0])
        ensure('package', parent, titles[1], bodies[1])
        result = dict(oral_ref=oral['node_token'], package_ref=package['node_token'],
                      oral_sha256=_sha(bodies[0]), package_sha256=_sha(bodies[1]),
                      publish_status='not_requested')
        state['result'] = result
        _persist(path, state)
        return result
    except SlimRuntimeError as exc:
        if exc.error_code == 'SLIM_SAVE_FAILED':
            raise
        _fail(exc.detail)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        _fail('Feishu save stopped: ' + str(exc))
    finally:
        if lock is not None:
            lock.close()
            lock_path.unlink()


def verify_saved_feishu_pair(*, output_root, output_template, receipt_dir,
                            expected_result, draft_version, item_suffix):
    """Read-only batch status verification; never creates or rewrites receipts."""
    from .feishu_source import assert_below
    from .vault_save import _reject_reparse
    path = Path(receipt_dir) / 'feishu-save.json'
    _reject_reparse(path)
    state = json.loads(path.read_text(encoding='utf-8'))
    request = state['request']
    if (output_root.logical_name != 'output' or request['space_id'] != output_root.space_id
            or request['root'] != output_root.token or request['output_template'] != output_template
            or request.get('draft_version') != draft_version or request.get('item_suffix') != item_suffix
            or state.get('result') != expected_result
            or expected_result.get('publish_status') != 'not_requested'):
        return False
    relative = _render_template(output_template, request['client_id'], datetime.fromisoformat(request['timestamp']))
    if relative.as_posix() != request['relative']:
        return False
    client = output_root.client
    parent = output_root.token
    assert_below(output_root.space, parent, parent)
    for index, part in enumerate(relative.parts):
        saved = state['entries']['folder:' + str(index)]['refs']
        node = assert_below(output_root.space, saved['node_token'], output_root.token)
        if (node.get('parent_node_token') != parent or node.get('title') != part
                or node.get('obj_token') != saved['obj_token'] or node.get('obj_type') != 'docx'):
            return False
        parent = node['node_token']
    for index, kind in enumerate(('oral', 'package')):
        entry = state['entries'][kind]
        if entry.get('status') != 'verified':
            return False
        saved = entry['refs']
        node = assert_below(output_root.space, saved['node_token'], output_root.token)
        title = request['titles'][index]
        if (node.get('obj_type') != 'docx' or node.get('obj_token') != saved['obj_token']
                or node.get('parent_node_token') != parent or node.get('title') != title
                or expected_result[kind + '_ref'] != node['node_token']):
            return False
        matches = [n for n in client.list_children(output_root.space_id, parent) if n.get('title') == title]
        if len(matches) != 1 or matches[0].get('node_token') != node['node_token']:
            return False
        actual = canonical_markdown(client.fetch_markdown(node['obj_token']))
        body_hashes = {_sha(body) for body in document_body_variants(actual, title)}
        if expected_result[kind + '_sha256'] != request['sha'][index] or request['sha'][index] not in body_hashes:
            return False
    return (expected_result['oral_ref'] != expected_result['package_ref']
            and state['entries']['oral']['refs']['obj_token'] != state['entries']['package']['refs']['obj_token'])
