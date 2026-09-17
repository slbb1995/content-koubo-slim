"""Durable acknowledgement of a verified local pair, bound to one Run.

Only a completed receipt may adopt existing files, with exact inode and content
checks. A crash before acknowledgement leaves an unknown outcome: stop for
manual reconciliation, never infer ownership from title or matching bytes.
"""
from __future__ import annotations
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from .run_store import RunStore
from .vault_save import _fail, _reject_reparse, save_markdown_pair
from .error_model import SlimRuntimeError


def _persist(path, state):
    temporary = path.with_suffix('.tmp')
    _reject_reparse(temporary)
    # Existing temp means the previous acknowledgement is uncertain.
    with temporary.open('xb') as handle:
        payload = (json.dumps(state, ensure_ascii=False, sort_keys=True) + '\n').encode('utf-8')
        try:
            if handle.write(payload) != len(payload):
                raise OSError('short receipt write')
            handle.flush()
            os.fsync(handle.fileno())
        except OSError:
            # Do not replace the last durable receipt with a partial one.
            raise
    _reject_reparse(path)
    os.replace(temporary, path)


def save_with_receipt(*, output_root, output_template, client_id,
                      selected_publish_title, oral_body, package_markdown,
                      receipt_dir, now=None, draft_version=1, item_suffix=None):
    receipt = Path(receipt_dir)
    lock = None
    locked = False
    try:
        if not receipt.is_absolute():
            _fail('receipt directory must be absolute')
        _reject_reparse(receipt)
        _reject_reparse(Path(output_root))
        root = Path(output_root)
        if not root.is_absolute() or not root.is_dir():
            _fail('output root must be an existing absolute directory')
        root = root.resolve(strict=True)
        receipt.mkdir(parents=True, exist_ok=True)
        path = receipt / 'local-save.json'
        lock_path = receipt / 'local-save.lock'
        _reject_reparse(lock_path)
        lock = lock_path.open('a+b')
        RunStore._lock_file(lock)
        locked = True
        _reject_reparse(path)
        request = dict(root=str(root), output_template=output_template,
            client_id=client_id, selected_publish_title=selected_publish_title,
            draft_version=draft_version, item_suffix=item_suffix,
            oral_sha256=hashlib.sha256((oral_body+'\n').encode('utf-8')).hexdigest(),
            package_sha256=hashlib.sha256((package_markdown.rstrip()+'\n').encode('utf-8')).hexdigest())
        if path.exists():
            state = json.loads(path.read_text(encoding='utf-8'))
            if (not isinstance(state, dict) or set(state) != {'version','request','timestamp','result','identities'}
                    or state['version'] != 1 or state['request'] != request):
                _fail('save receipt does not match the approved request')
            timestamp = datetime.fromisoformat(state['timestamp'])
        else:
            timestamp = now or datetime.now().astimezone()
            state = dict(version=1, request=request, timestamp=timestamp.isoformat(), result=None, identities={})
            _persist(path, state)
        if state['result'] is not None:
            from .vault_save import _render_template, _versioned_stem
            relative = _render_template(output_template, client_id, timestamp)
            stem = _versioned_stem(selected_publish_title, draft_version, item_suffix)
            result = dict(state['result'])
            if set(result) != {'oral_path','package_path','oral_relative_path','package_relative_path','oral_sha256','package_sha256','publish_status'} or result['publish_status'] != 'not_requested':
                _fail('malformed local save result')
            for kind, suffix in (('oral','口播稿'),('package','配套文案')):
                target = root.joinpath(*relative.parts, stem+'-'+suffix+'.md')
                _reject_reparse(target)
                if result[kind+'_path'] != str(target) or result[kind+'_relative_path'] != target.relative_to(root).as_posix():
                    _fail('saved location changed')
                stat = target.stat()
                if state['identities'].get(kind) != [stat.st_dev, stat.st_ino]:
                    _fail('acknowledged output identity changed')
                expected = request[kind+'_sha256']
                if result[kind+'_sha256'] != expected or hashlib.sha256(target.read_bytes()).hexdigest() != expected:
                    _fail('acknowledged output content changed')
                result[kind+'_path'] = target
            return result
        # Pending receipts do not acknowledge any files. The create-only saver
        # rejects every existing name, even if its bytes equal the requested body.
        result = save_markdown_pair(output_root=root, output_template=output_template,
            client_id=client_id, selected_publish_title=selected_publish_title,
            oral_body=oral_body, package_markdown=package_markdown, now=timestamp,
            draft_version=draft_version, item_suffix=item_suffix)
        state['result'] = {k: str(v) if isinstance(v, Path) else v for k,v in result.items()}
        state['identities'] = {kind: [result[kind+'_path'].stat().st_dev, result[kind+'_path'].stat().st_ino] for kind in ('oral','package')}
        _persist(path, state)
        return result
    except SlimRuntimeError:
        raise
    except (OSError, ValueError, TypeError, KeyError) as exc:
        _fail('local save receipt stopped: '+str(exc))
    finally:
        if lock is not None:
            try:
                if locked:
                    RunStore._unlock_file(lock)
            finally:
                lock.close()
