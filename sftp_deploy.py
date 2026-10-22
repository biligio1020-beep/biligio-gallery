#!/usr/bin/env python3
"""Deploy only dist/gallery/ over SFTP to <SFTP login directory>/www/gallery/.

Requires Paramiko and a trusted SHA256 host-key fingerprint. There is no FTP,
no SSH shell execution, and no ability to write outside the gallery directory.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import io
import json
import os
import posixpath
import stat
import sys
from pathlib import Path

try:
    import paramiko
except ImportError as e:
    raise SystemExit("paramiko 가 필요합니다: python -m pip install paramiko") from e

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "dist" / "gallery"
REMOTE_PARENT_NAME = "www"
EXPECTED_LOGIN = "/biligio"
REMOTE_GALLERY_NAME = "gallery"
MARKER = ".biligio-gallery-managed"
MANIFEST = ".biligio-gallery-manifest.json"
MARKER_TEXT = "BILIGIO_GALLERY_SFTP_V1\n"


def required_env(key: str) -> str:
    value = os.getenv(key, "")
    if "PASSWORD" not in key:
        value = value.strip()
    if not value:
        raise ValueError(f"GitHub Secret '{key}' 값이 없습니다.")
    return value


class PinnedFingerprint(paramiko.MissingHostKeyPolicy):
    def __init__(self, trusted: str):
        self.trusted = trusted.strip().rstrip("=")
        if not self.trusted.startswith("SHA256:"):
            raise ValueError("서버 호스트 키 지문은 SHA256:... 형식이어야 합니다.")

    def missing_host_key(self, client, hostname, key):
        actual = "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode("ascii").rstrip("=")
        if not hmac.compare_digest(actual, self.trusted):
            raise paramiko.SSHException(
                f"서버 호스트 키 불일치! 기대값: {self.trusted}, 응답값: {actual}. "
                "FileZilla/호스팅 업체의 신뢰할 수 있는 지문과 비교하세요."
            )
        client.get_host_keys().add(hostname, key.get_name(), key)


def remote_kind(sftp, path: str) -> str:
    try:
        mode = sftp.lstat(path).st_mode
    except FileNotFoundError:
        return "missing"
    if stat.S_ISLNK(mode):
        raise RuntimeError(f"보안상 원격 심볼릭 링크는 허용하지 않습니다: {path}")
    if stat.S_ISDIR(mode):
        return "dir"
    if stat.S_ISREG(mode):
        return "file"
    raise RuntimeError(f"예상하지 않은 원격 파일 유형: {path}")


def safe_local_files() -> dict[str, Path]:
    if not (OUTPUT / "index.html").is_file():
        raise RuntimeError("빌드 출력이 없습니다: dist/gallery/index.html")
    result = {}
    for path in OUTPUT.rglob("*"):
        if path.is_symlink():
            raise RuntimeError(f"심볼릭 링크는 배포할 수 없습니다: {path}")
        if path.is_file():
            relative = path.relative_to(OUTPUT).as_posix()
            if relative in {MARKER, MANIFEST}:
                raise RuntimeError("관리용 파일명 충돌이 있습니다.")
            result[relative] = path
    return result


def files_in_remote(sftp, root: str) -> tuple[dict[str, int], list[str]]:
    files = {}
    directories = []

    def walk(path: str, rel: str):
        for x in sftp.listdir_attr(path):
            name = x.filename
            if name in (".", "..") or "/" in name or "\\" in name:
                raise RuntimeError(f"안전하지 않은 원격 파일명: {name}")
            r = f"{rel}/{name}" if rel else name
            p = posixpath.join(path, name)
            if stat.S_ISLNK(x.st_mode):
                raise RuntimeError(f"보안상 심볼릭 링크는 허용하지 않습니다: {p}")
            if stat.S_ISDIR(x.st_mode):
                directories.append(r)
                walk(p, r)
            elif stat.S_ISREG(x.st_mode):
                files[r] = x.st_size
            else:
                raise RuntimeError(f"지원되지 않는 원격 파일 유형: {p}")

    walk(root, "")
    return files, directories


def remote_read(sftp, path):
    with sftp.open(path, "rb") as f:
        return f.read()


def check_destination(sftp) -> tuple[str, bool]:
    start = sftp.normalize(".")
    if start != EXPECTED_LOGIN:
        raise RuntimeError(f"접속 시작 경로가 확인된 /biligio 와 다릅니다: {start}")
    parent = posixpath.join(start, REMOTE_PARENT_NAME)
    if remote_kind(sftp, parent) != "dir":
        raise RuntimeError(f"SFTP 접속 위치 {start} 바로 아래에서 www 폴더를 찾지 못했습니다. FileZilla 원격 경로 확인 필요.")
    names = sftp.listdir(parent)
    if not any(x in names for x in ("index.html", "index.php", "mobile")):
        raise RuntimeError(
            f"{parent} 에서 index.html/index.php/mobile이 발견되지 않았습니다. "
            "여기가 실제 홈페이지 루트인지 확인하세요."
        )
    destination = posixpath.join(parent, REMOTE_GALLERY_NAME)
    kind = remote_kind(sftp, destination)
    if kind not in ("dir", "missing"):
        raise RuntimeError("www/gallery가 폴더가 아니라 파일입니다. 수동 점검이 필요합니다.")
    managed = False
    if kind == "dir":
        items = sftp.listdir(destination)
        if MARKER in items:
            if remote_kind(sftp, posixpath.join(destination, MARKER)) != "file":
                raise RuntimeError("갤러리 관리용 표식 파일이 손상되었습니다.")
            marker_value = remote_read(sftp, posixpath.join(destination, MARKER)).decode("utf-8")
            if marker_value != MARKER_TEXT:
                raise RuntimeError("다른 갤러리 관리 표식이 있어 배포를 중단했습니다.")
            managed = True
        elif items:
            raise RuntimeError(
                f"{destination} 폴더에 기존 파일이 있지만 관리 표식이 없습니다. "
                "자동 배포는 기존 파일을 보호하기 위해 중단합니다."
            )
    print(f"SFTP 시작 폴더: {start}")
    print(f"검증된 웹 루트: {parent}")
    print(f"갤러리 대상: {destination} / {'기존 관리 대상' if managed else '새 폴더 또는 빈 폴더'}")
    print(f"웹 루트 확인 항목: {', '.join(x for x in ('index.html', 'index.php', 'mobile') if x in names)}")
    return destination, managed


def remote_manifest(sftp, destination, managed):
    if not managed:
        return {}
    path = posixpath.join(destination, MANIFEST)
    if remote_kind(sftp, path) == "missing":
        return {}
    result = json.loads(remote_read(sftp, path).decode("utf-8"))
    if not isinstance(result, dict):
        raise RuntimeError("원격 manifest 형식이 잘못되었습니다.")
    return result


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sync(sftp, destination: str, managed: bool, mode: str):
    local = safe_local_files()
    hashes = {k: sha256(v) for k, v in local.items()}
    remote_old = remote_manifest(sftp, destination, managed)
    remote_files, remote_dirs = files_in_remote(sftp, destination) if remote_kind(sftp, destination) == "dir" else ({}, [])
    target_upload = [k for k in sorted(local) if remote_old.get(k) != hashes[k] or k not in remote_files]
    target_remove = sorted((set(remote_files) & set(remote_old)) - set(local) - {MARKER, MANIFEST})
    unmanaged = set(remote_files) - set(remote_old) - {MARKER, MANIFEST}
    if unmanaged:
        raise RuntimeError("갤러리에 자동배포가 관리하지 않는 파일이 있습니다. 보존을 위해 중단합니다.")
    print(f"배포 대상 파일: {len(local)}개, 새로 전송/변경: {len(target_upload)}개, 기존 삭제 예정: {len(target_remove)}개")
    if mode == "check":
        print("CHECK ONLY: 원격 서버에 어떠한 쓰기/삭제 작업도 하지 않았습니다.")
        for rel in target_remove[:10]:
            print(f"  삭제 예정: gallery/{rel}")
        return

    if remote_kind(sftp, destination) == "missing":
        sftp.mkdir(destination)
    if not managed:
        # Allow only an empty, dedicated folder to be claimed.
        if sftp.listdir(destination):
            raise RuntimeError("초기 갤러리 폴더가 비어 있지 않습니다.")
        with sftp.open(posixpath.join(destination, MARKER), "wb") as f:
            f.write(MARKER_TEXT.encode("utf-8"))

    created = {""}
    for rel in target_upload:
        parent_rel = posixpath.dirname(rel)
        if parent_rel and parent_rel not in created:
            pieces = parent_rel.split("/")
            for i in range(1, len(pieces) + 1):
                rp = "/".join(pieces[:i])
                if rp not in created:
                    remote_dir = posixpath.join(destination, rp)
                    typ = remote_kind(sftp, remote_dir)
                    if typ == "missing":
                        sftp.mkdir(remote_dir)
                    elif typ != "dir":
                        raise RuntimeError(f"원격 폴더를 만들 수 없습니다: {remote_dir}")
                    created.add(rp)
        remote_path = posixpath.join(destination, rel)
        sftp.put(str(local[rel]), remote_path, confirm=True)
        print(f"업로드: gallery/{rel}")

    # Remove only files in the dedicated marker-verified gallery folder.
    for rel in target_remove:
        sftp.remove(posixpath.join(destination, rel))
        print(f"갤러리에서 제거: gallery/{rel}")
    _, post_dirs = files_in_remote(sftp, destination)
    for rel in sorted(post_dirs, key=lambda s: (-s.count("/"), -len(s))):
        remote_dir = posixpath.join(destination, rel)
        if not sftp.listdir(remote_dir):
            sftp.rmdir(remote_dir)

    manifest_bytes = json.dumps(hashes, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    with sftp.open(posixpath.join(destination, MANIFEST), "wb") as f:
        f.write(manifest_bytes)
    print("SFTP 배포 완료: 갤러리 폴더만 동기화했습니다.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("check", "deploy", "install"), default="check")
    args = parser.parse_args()

    host = required_env("CAFE24_SFTP_HOST")
    user = required_env("CAFE24_SFTP_USER")
    password = required_env("CAFE24_SFTP_PASSWORD")
    fingerprint = required_env("CAFE24_SFTP_HOSTKEY_SHA256")
    safe_local_files()

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(PinnedFingerprint(fingerprint))
    try:
        client.connect(
            hostname=host, port=3822, username=user, password=password,
            look_for_keys=False, allow_agent=False,
            timeout=20, auth_timeout=20, banner_timeout=20,
        )
        sftp = client.open_sftp()
        try:
            destination, managed = check_destination(sftp)
            if args.mode == "install":
                from homepage_links import prepare, apply
                changes = prepare(sftp, "/biligio/www")
                sync(sftp, destination, managed, "deploy")
                apply(sftp, "/biligio/www", changes)
            else:
                if args.mode == "check":
                    from homepage_links import prepare
                    prepare(sftp, "/biligio/www")
                sync(sftp, destination, managed, args.mode)
        finally:
            sftp.close()
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        sys.exit(f"SFTP 확인/배포 실패: {exc}")
