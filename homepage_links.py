"""One-time home links installation against verified uploaded originals.

Only index.html and mobile/index.html are allowed. Product data is never touched.
All originals must match before any write; backups are kept outside www.
"""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import posixpath
import stat

ALLOWED = {'index.html', 'mobile/index.html'}
PLAN = Path(__file__).with_name('homepage_patch.json')

def digest(data):
    return hashlib.sha256(data).hexdigest()

def read(sftp, path):
    if not stat.S_ISREG(sftp.lstat(path).st_mode):
        raise RuntimeError(f'일반 파일이 아닙니다: {path}')
    with sftp.open(path, 'rb') as f:
        return f.read()

def prepare(sftp, root):
    if root != '/biligio/www':
        raise RuntimeError('확인되지 않은 웹 루트입니다.')
    if not stat.S_ISDIR(sftp.lstat(root + '/mobile').st_mode):
        raise RuntimeError('mobile 폴더가 일반 디렉터리가 아닙니다.')
    plan = json.loads(PLAN.read_text(encoding='utf-8'))
    if set(plan) != ALLOWED:
        raise RuntimeError('허용된 홈페이지 수정 범위와 다릅니다.')
    changes = []
    for name, item in plan.items():
        data = read(sftp, root + '/' + name)
        if digest(data) == item['after_sha256']:
            continue
        if digest(data) != item['before_sha256']:
            raise RuntimeError(f'{name}: 서버 원본이 첨부본 이후 변경되어 덮어쓰지 않습니다.')
        text = data.decode('utf-8')
        for old, new in item['replacements']:
            if text.count(old) != 1:
                raise RuntimeError(f'{name}: 메뉴 위치가 일치하지 않습니다.')
            text = text.replace(old, new)
        output = text.encode('utf-8')
        if digest(output) != item['after_sha256']:
            raise RuntimeError(f'{name}: 수정 결과 검증 실패')
        changes.append((name, data, output))
    print(f'홈페이지 메뉴 수정 사전검사 통과: {len(changes)}개 파일')
    return changes

def apply(sftp, root, changes):
    if not changes:
        print('홈페이지 메뉴는 이미 연결되어 있습니다.')
        return
    # Recheck all live originals immediately before writing.
    for name, before, after in changes:
        if read(sftp, root + '/' + name) != before:
            raise RuntimeError('사전검사 이후 서버 파일이 변경되었습니다.')
    backup_parent = '/biligio/DataBackup'
    if not stat.S_ISDIR(sftp.lstat(backup_parent).st_mode):
        raise RuntimeError('확인된 DataBackup 폴더가 없습니다.')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = backup_parent + '/gallery-menu-' + stamp
    sftp.mkdir(backup)
    # Save and verify every backup before changing the homepage.
    for name, before, after in changes:
        path = backup + '/' + name.replace('/', '__')
        with sftp.open(path, 'wb') as f:
            f.write(before)
        if read(sftp, path) != before:
            raise RuntimeError('원본 백업 검증 실패')
    changed = []
    try:
        for name, before, after in changes:
            path = root + '/' + name
            if read(sftp, path) != before:
                raise RuntimeError('설치 도중 원본이 변경되었습니다.')
            changed.append((path, before))
            with sftp.open(path, 'wb') as f:
                f.write(after)
            if read(sftp, path) != after:
                raise RuntimeError('메뉴 반영 후 내용 검증 실패')
    except Exception:
        for path, before in reversed(changed):
            try:
                with sftp.open(path, 'wb') as f:
                    f.write(before)
            except Exception:
                print(f'자동 복구 실패. 백업 경로 확인: {backup}')
        raise
    print(f'PC·모바일 메뉴 연결 완료. 원본 백업: {backup}')
