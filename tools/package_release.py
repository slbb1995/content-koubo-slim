#!/usr/bin/env python3
"""Build a complete verified ZIP from the current clean Git commit."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', required=True, type=Path)
    a = p.parse_args()
    out = a.out
    if not out.is_absolute() or out.exists() or not out.parent.is_dir():
        p.error('output must be a new absolute file with an existing parent')
    def git(*args):
        return subprocess.check_output(['git', '-C', str(ROOT), *args], text=True).strip()
    if git('status', '--porcelain', '--untracked-files=all'):
        p.error('source checkout must be clean')
    commit = git('rev-parse', 'HEAD')
    version = (ROOT/'VERSION').read_text(encoding='utf-8').strip()
    with tempfile.TemporaryDirectory(prefix='koubo-package-') as temporary:
        stage = Path(temporary)
        archive = stage/'package.zip'
        subprocess.run(['git','-C',str(ROOT),'archive','--format=zip','--output='+str(archive),commit],check=True)
        unpacked=stage/'unpacked'
        with zipfile.ZipFile(archive) as z:
            z.extractall(unpacked)
        # zipfile does not restore Unix executable bits.
        manifest=json.loads((unpacked/'release-manifest.json').read_text(encoding='utf-8'))
        for item in manifest['runtime']['files']:
            (unpacked/item['path']).chmod(int(item['mode'],8))
        env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONUTF8':'1'}
        subprocess.run([sys.executable,'-B',str(unpacked/'tools/verify.py')],env=env,check=True)
        if git('rev-parse','HEAD') != commit or git('status','--porcelain','--untracked-files=all'):
            raise RuntimeError('source changed during packaging')
        with out.open('xb') as target:
            target.write(archive.read_bytes())
    print(json.dumps({'version':version,'commit':commit,'zip':str(out),'sha256':hashlib.sha256(out.read_bytes()).hexdigest()},ensure_ascii=False))

if __name__=='__main__': main()
