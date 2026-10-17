"""Back up and atomically replace only the five verified runtime directories."""
import argparse
from datetime import datetime
from zoneinfo import ZoneInfo
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('release', ROOT/'content_koubo_slim_release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def update(host, package, backup_root):
    host = host.resolve(strict=True)
    verified = release.verify(package)
    backup_root.mkdir(parents=True, exist_ok=False)
    backup_path = backup_root/'before-update'
    release.backup_host(host, package, backup_path)
    backup = release.load_backup(backup_path, host, verified)
    for item in backup['targets']:
        expected = {k:item[k] for k in ('exists','file_count','tree_sha256')}
        assert release.target_snapshot(host/'skills'/item['skill']) == expected
        assert release.target_snapshot(backup_path/'before-skills'/item['skill']) == expected
    stage = Path(tempfile.mkdtemp(prefix='.koubo-upgrade-', dir=host/'skills'))
    originals = backup_root/'moved-originals'
    originals.mkdir()
    moved, installed, modes = [], [], {}
    try:
        for skill in release.EXPECTED_SKILLS:
            shutil.copytree(package/'Skills'/skill, stage/skill, copy_function=shutil.copy2)
        for item in backup['targets']:
            skill = item['skill']
            target = host/'skills'/skill
            if item['exists']:
                modes[skill] = stat.S_IMODE(target.stat().st_mode)
                target.chmod(modes[skill] | stat.S_IWUSR)
                os.rename(target, originals/skill)
                moved.append(skill)
            os.rename(stage/skill, target)
            installed.append(skill)
        stage.rmdir()
        for skill in installed:
            release.set_installed_permissions(host/'skills'/skill)
        health = release.doctor(host, package)
        release.assert_control_unchanged(host, backup)
        if release.unrelated_host_drift(host, backup)[0]:
            raise RuntimeError('Unrelated skills changed during installation; own changes restored')
    except BaseException:
        for skill in reversed(installed):
            release.make_writable_tree(host/'skills'/skill)
            shutil.rmtree(host/'skills'/skill)
        for skill in reversed(moved):
            os.rename(originals/skill, host/'skills'/skill)
            (host/'skills'/skill).chmod(modes[skill])
        if stage.exists():
            release.make_writable_tree(stage)
            shutil.rmtree(stage)
        originals.rmdir()
        raise
    for skill in moved:
        release.make_writable_tree(originals/skill)
        shutil.rmtree(originals/skill)
    originals.rmdir()
    receipt = dict(status='updated_and_verified', installed_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
        host=str(host), backup=str(backup_path), health=health, backup_verified=True,
        host_control_files_unchanged=True, unrelated_skills_unchanged_at_install=True)
    (backup_root/'installation-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    return receipt


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host-root', required=True, type=Path)
    p.add_argument('--package', required=True, type=Path)
    p.add_argument('--backup-root', required=True, type=Path)
    a = p.parse_args()
    print(json.dumps(update(a.host_root, a.package, a.backup_root),ensure_ascii=False,indent=2))
