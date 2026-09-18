"""Small lark-cli transport; no write retries or credential persistence."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

from .error_model import SlimRuntimeError

MAX_PAGES = 100
MAX_NODES = 5000


def _lark_command(binary, arguments, *, platform=None):
    """Build a process command without asking Windows to open a launcher file."""
    if (platform or os.name) == 'nt' and binary.lower().endswith(('.cmd', '.bat')):
        command = subprocess.list2cmdline([binary, *arguments])
        comspec = os.environ.get('ComSpec', r'C:\\Windows\\System32\\cmd.exe')
        return [comspec, '/d', '/s', '/c', command]
    return [binary, *arguments]


def canonical_markdown(body: str) -> str:
    """Normalize transport newlines only; retain Markdown escapes and spaces."""
    return body.replace('\r\n', '\n').replace('\r', '\n').rstrip('\n') + '\n'


def _error(detail, *, writing=False):
    return SlimRuntimeError('SLIM_SAVE_FAILED' if writing else 'SLIM_KNOWLEDGE_ASSET_INVALID',
                            'feishu_client', detail=detail)


class FeishuClient:
    def __init__(self, binary=None, identity='user'):
        if identity not in {'user', 'bot'}:
            raise _error('identity must be user or bot')
        self.binary = binary or shutil.which('lark-cli')
        self.identity = identity
        if not self.binary:
            raise _error('lark-cli is not installed')

    def _call(self, args, *, body=None, writing=False):
        try:
            completed = subprocess.run(
                _lark_command(self.binary, [*args, '--as', self.identity, '--format', 'json']),
                input=body, capture_output=True, text=True, encoding='utf-8',
                check=False, timeout=120, shell=False)
            output = completed.stdout if completed.returncode == 0 else completed.stderr
            if completed.returncode == 0 and args[:2] == ['wiki', '+node-list']:
                # This shortcut emits one informational line before its envelope.
                # Remove only that exact prefix, never scan into arbitrary logs.
                output = re.sub(r'\AFound [0-9]+ node\(s\)\r?\n', '', output, count=1)
            value = json.loads(output)  # rejects extra JSON or non-whitespace tails
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise _error('CLI transport or JSON failure; write outcome may be unknown', writing=writing) from exc
        if not isinstance(value, dict) or completed.returncode or value.get('ok') is not True:
            exc = _error('CLI did not return a successful envelope', writing=writing)
            exc.cli_code = value.get('error', {}).get('code') if isinstance(value, dict) else None
            raise exc
        data = value.get('data')
        if not isinstance(data, dict):
            raise _error('CLI data object is missing', writing=writing)
        return data

    @staticmethod
    def _node(data):
        node = data.get('node', data)
        fields = ('space_id', 'node_token', 'obj_token', 'parent_node_token', 'title', 'obj_type', 'node_type')
        if not isinstance(node, dict) or any(not isinstance(node.get(k), str) for k in fields):
            raise _error('Incomplete wiki node')
        if not all(node[k] for k in ('space_id', 'node_token', 'obj_token')):
            raise _error('Empty wiki identifiers')
        return dict(node)

    def _get_node(self, ref, obj_type=None):
        args = ['wiki', '+node-get', '--node-token', ref]
        if obj_type:
            args += ['--obj-type', obj_type]
        return self._node(self._call(args))

    def get_node(self, ref):
        try:
            return self._get_node(ref)
        except SlimRuntimeError as exc:
            # Untyped obj tokens can return not_found (131005) or invalid token
            # (131013). Resolve once as docx; never retry URLs or permissions.
            if '://' not in ref and getattr(exc, 'cli_code', None) in {131005, 131013}:
                return self._get_node(ref, 'docx')
            raise

    def fetch_markdown(self, ref):
        data = self._call(['docs', '+fetch', '--doc', ref, '--doc-format', 'markdown', '--detail', 'simple'])
        content = data.get('document', {}).get('content')
        if not isinstance(content, str):
            raise _error('Document Markdown missing')
        return canonical_markdown(content)

    def list_children(self, space_id, parent_node_token):
        nodes, seen, cursor = [], set(), ''
        for _ in range(MAX_PAGES):
            args = ['wiki', '+node-list', '--space-id', space_id, '--parent-node-token', parent_node_token]
            if cursor:
                args += ['--page-token', cursor]
            data = self._call(args)
            if not isinstance(data.get('nodes'), list) or not isinstance(data.get('has_more'), bool):
                raise _error('Incomplete wiki pagination')
            nodes.extend(self._node(n) for n in data['nodes'])
            if len(nodes) > MAX_NODES:
                raise _error('Wiki listing exceeds the node budget')
            if not data['has_more']:
                return nodes
            cursor = data.get('page_token')
            if not isinstance(cursor, str) or not cursor or cursor in seen:
                raise _error('Invalid or repeated wiki cursor')
            seen.add(cursor)
        raise _error('Wiki listing exceeds the page budget')

    def create_document(self, parent_node_token, title, body):
        data = self._call(['docs', '+create', '--parent-token', parent_node_token,
                           '--title', title, '--doc-format', 'markdown', '--content', '-'],
                          body=body, writing=True)
        document = data.get('document', {})
        obj = document.get('document_id') if isinstance(document, dict) else None
        if not isinstance(obj, str) or not obj:
            raise _error('Create returned no document ID; outcome unknown', writing=True)
        refs = {'obj_token': obj}
        try:
            if data.get('warnings'):
                raise _error('Create returned conversion warnings', writing=True)
            refs.update(self._get_node(obj, 'docx'))
        except SlimRuntimeError as exc:
            exc.received_refs = refs
            raise
        return refs

    def replace_document(self, object_ref, body):
        """Configuration migration only; caller must read before and after."""
        data = self._call(['docs', '+update', '--doc', object_ref, '--command', 'overwrite',
                           '--doc-format', 'markdown', '--content', '-'], body=body, writing=True)
        if data.get('result') != 'success' or data.get('warnings'):
            raise _error('Configuration overwrite was partial or degraded', writing=True)
        return data
