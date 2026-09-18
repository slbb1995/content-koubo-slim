"""Explicit remote references and fail-closed, read-only Wiki membership checks.

The client owns transport and pagination. No remote object is a filesystem path.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Iterator

from .error_model import SlimRuntimeError


def get_client():
    """Late construction provides a single injection seam for offline callers."""
    from .feishu_client import FeishuClient
    return FeishuClient()


@dataclass(frozen=True)
class FeishuSpace:
    locator: str
    space_id: str
    client: Any

    def __str__(self) -> str:
        return self.locator


@dataclass(frozen=True)
class FeishuDocument:
    space: FeishuSpace
    token: str
    title: str | None = None
    expected_sha256: str | None = None

    def __str__(self) -> str:
        return self.token


@dataclass(frozen=True)
class FeishuRoot:
    space: FeishuSpace
    token: str
    logical_name: str

    @property
    def client(self):
        return self.space.client

    @property
    def space_id(self) -> str:
        return self.space.space_id

    @property
    def name(self) -> str:
        return self.logical_name


def _fail(detail: str) -> None:
    raise SlimRuntimeError('SLIM_MANIFEST_INVALID', 'feishu_source', detail=detail)


def raw_token(value: str) -> str:
    """Validate an unprefixed registry/index token without rewriting it."""
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9]+', value):
        _fail('Feishu reference must be an alphanumeric token')
    return value


def parse_relative_ref(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'feishu:[A-Za-z0-9]+', value):
        _fail('remote asset path must be feishu:<alphanumeric token>')
    return value[7:]


def canonical_markdown(text: str) -> str:
    if not isinstance(text, str):
        _fail('Feishu Markdown response must be a string')
    return text.replace('\r\n', '\n').replace('\r', '\n').strip() + '\n'


def _node(space: FeishuSpace, ref: str) -> dict[str, Any]:
    ref = raw_token(ref)
    node = space.client.get_node(ref)
    if not isinstance(node, dict) or str(node.get('space_id')) != space.space_id:
        _fail('Feishu node is outside the authorized space')
    token = raw_token(node.get('node_token'))
    obj = raw_token(node.get('obj_token'))
    if ref not in (token, obj):
        _fail('Feishu node resolution changed the requested identity')
    # Never follow shortcuts: their placement is not target authorization.
    if node.get('node_type') != 'origin':
        _fail('Feishu shortcut or unknown node type is not authorized')
    parent = node.get('parent_node_token')
    if not isinstance(parent, str):
        _fail('Feishu node has no verifiable parent')
    if parent:
        raw_token(parent)
    return node


def assert_below(
    space: FeishuSpace, ref: str, root_token: str | None, *, max_depth: int = 64
) -> dict[str, Any]:
    """Resolve node/doc tokens, validate ancestry, return the requested node.

    None authorizes space membership only (for bootstrap config documents).
    Otherwise root_token must be a node token and ancestry is inclusive.
    """
    if root_token is not None:
        raw_token(root_token)
    first = _node(space, ref)
    node = first
    seen: set[str] = set()
    for _ in range(max_depth):
        token = node['node_token']
        if token in seen:
            _fail('cycle in Feishu node ancestry')
        seen.add(token)
        if root_token is not None and token == root_token:
            return first
        parent = node['parent_node_token']
        if not parent:
            if root_token is None:
                return first
            _fail('Feishu document is outside the authorized root')
        node = _node(space, parent)
        if node['node_token'] != parent:
            _fail('Feishu parent must resolve to its exact node token')
    _fail('Feishu ancestry exceeds the bounded depth')


def read_document(document: FeishuDocument, root_token: str | None = None) -> str:
    node = assert_below(document.space, document.token, root_token)
    if node.get('obj_type') != 'docx':
        _fail('Feishu source must be a Markdown-readable docx node')
    return canonical_markdown(document.space.client.fetch_markdown(document.token))


def remote_json(document: FeishuDocument) -> tuple[dict[str, Any], str]:
    """Read one strict JSON object, optionally wrapped in headings/json fence.

    The digest always covers the entire canonical fetched Markdown, wrappers
    included, so a frozen configuration detects every source change.
    """
    text = read_document(document)
    digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
    if document.expected_sha256 is not None and document.expected_sha256 != digest:
        _fail('Feishu JSON configuration changed after its verified binding')
    from .feishu_client import strip_native_title
    payload = strip_native_title(text).strip()
    while re.match(r'^#{1,6}\s+[^\n]+(?:\n|$)', payload):
        payload = re.sub(r'^#{1,6}\s+[^\n]+(?:\n|$)', '', payload, count=1).lstrip()
    if payload.startswith('```'):
        match = re.fullmatch(r'```json\s*\n(.*?)\n```', payload, flags=re.DOTALL)
        if not match:
            _fail('configuration must contain one complete JSON fence')
        payload = match.group(1)

    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('duplicate JSON key')
            value[key] = item
        return value

    def invalid_constant(value):
        raise ValueError('non-finite JSON constant: ' + value)

    try:
        value = json.loads(payload, object_pairs_hook=pairs, parse_constant=invalid_constant)
        if not isinstance(value, dict):
            raise ValueError('configuration must be a JSON object')
    except (ValueError, RecursionError) as exc:
        _fail('invalid Feishu JSON configuration: ' + str(exc))
    return value, digest


def iter_documents(
    root: FeishuRoot, *, max_nodes: int = 256, max_depth: int = 32
) -> Iterator[FeishuDocument]:
    """Enumerate descendants only; client.list_children handles bounded pages.

    Reject inconsistent edges, duplicate nodes, cycles, and traversal overflow.
    Read no bodies here and never enumerate a sibling root or the space itself.
    """
    assert_below(root.space, root.token, root.token)
    pending = deque([(root.token, 0)])
    seen = {root.token}
    count = 0
    while pending:
        parent, depth = pending.popleft()
        for advertised in root.client.list_children(root.space_id, parent):
            count += 1
            if count > max_nodes or depth >= max_depth:
                _fail('Feishu candidate traversal exceeds its bound')
            if not isinstance(advertised, dict):
                _fail('invalid Feishu child listing')
            token = raw_token(advertised.get('node_token'))
            if (str(advertised.get('space_id')) != root.space_id
                    or advertised.get('parent_node_token') != parent
                    or advertised.get('node_type') != 'origin'):
                _fail('Feishu child listing contains an unauthorized edge or shortcut')
            if token in seen:
                _fail('duplicate or cyclic Feishu child listing')
            seen.add(token)
            # BFS already verified this parent back to root. Verify each fresh
            # child once instead of re-fetching every ancestor for every leaf.
            # read_document rechecks full ancestry immediately before the fetch.
            node = _node(root.space, token)
            if node['parent_node_token'] != parent:
                _fail('Feishu child moved during enumeration')
            if node.get('obj_type') == 'docx':
                title = node.get('title')
                yield FeishuDocument(root.space, token, title if isinstance(title, str) else None)
            if node.get('has_child') is not False:
                pending.append((token, depth + 1))
