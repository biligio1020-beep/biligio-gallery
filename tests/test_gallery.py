import contextlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import build_gallery as build
import homepage_links as home
# These tests exercise filesystem safeguards, not a live SSH implementation.
try:
    import paramiko
except ImportError:
    sys.modules['paramiko'] = types.SimpleNamespace(MissingHostKeyPolicy=object, SSHException=RuntimeError)
import sftp_deploy as deploy

class FakeSFTP:
    def __init__(self, root):
        self.root = Path(root)
        self.writes = 0
    def path(self, value):
        path = self.root / value.lstrip('/')
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise ValueError('outside sandbox')
        return path
    def normalize(self, value): return '/biligio'
    def lstat(self, value): return self.path(value).lstat()
    def listdir(self, value): return [p.name for p in self.path(value).iterdir()]
    def listdir_attr(self, value):
        return [types.SimpleNamespace(filename=p.name, st_mode=p.lstat().st_mode, st_size=p.stat().st_size) for p in self.path(value).iterdir()]
    def open(self, value, mode):
        if 'w' in mode: self.writes += 1
        return self.path(value).open(mode)
    def mkdir(self, value):
        self.writes += 1
        self.path(value).mkdir()
    def remove(self, value):
        self.writes += 1
        self.path(value).unlink()
    def rmdir(self, value):
        self.writes += 1
        self.path(value).rmdir()
    def put(self, local, remote, confirm=True):
        self.writes += 1
        shutil.copyfile(local, self.path(remote))

class GalleryTests(unittest.TestCase):
    def test_public_output_excludes_draft_images_and_hides_date(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for folder in ['assets', 'content/gallery', 'media/gallery']:
                (root/folder).mkdir(parents=True)
            for name in ['gallery.css', 'gallery.js']:
                shutil.copyfile(ROOT/'assets'/name, root/'assets'/name)
            (root/'media/gallery/public.jpg').write_bytes(b'public')
            (root/'media/gallery/private.jpg').write_bytes(b'private')
            case = dict(url_id='test-case', title='<Test>', summary='A & B', date='2026-10-22', date_display='hidden', category='performance', instruments='첼로', cover='/gallery/media/public.jpg', published=True)
            (root/'content/gallery/test-case.json').write_text(json.dumps(case))
            (root/'content/gallery/draft.json').write_text(json.dumps(dict(case, url_id='draft', published=False, cover='/gallery/media/private.jpg')))
            with patch.multiple(build, ROOT=root, CONTENT=root/'content/gallery', MEDIA=root/'media/gallery', OUT=root/'dist/gallery'):
                build.main()
                output=root/'dist/gallery'
                self.assertTrue((output/'media/public.jpg').exists())
                self.assertFalse((output/'media/private.jpg').exists())
                self.assertFalse((output/'draft').exists())
                html=(output/'test-case/index.html').read_text()
                self.assertNotIn('2026-10-22', html)
                self.assertIn('&lt;Test&gt;', html)
                self.assertIn('qr.kakao.com', html)
                self.assertNotIn('#contact', html)
    def test_date_modes(self):
        self.assertEqual(build.display_date({'date':'2026-10-22','date_display':'month'}), '2026-10')
        self.assertEqual(build.display_date({'date':'2026-10-22','date_display':'hidden'}), '')
    def test_image_traversal_is_rejected(self):
        self.assertEqual(build.image_url('/gallery/media/../secret.jpg'), '')
        self.assertEqual(build.image_url('https://example.com/photo.jpg'), '')

class DeploymentTests(unittest.TestCase):
    def test_check_never_writes_and_rejects_unmanaged_gallery(self):
        with tempfile.TemporaryDirectory() as td:
            sftp=FakeSFTP(td)
            sftp.path('/biligio/www/mobile').mkdir(parents=True)
            output=Path(td)/'build';output.mkdir();(output/'index.html').write_text('gallery')
            with patch.object(deploy, 'OUTPUT', output):
                destination, managed=deploy.check_destination(sftp)
                deploy.sync(sftp, destination, managed, 'check')
                self.assertEqual(sftp.writes,0)
                sftp.path(destination).mkdir()
                sftp.path(destination+'/manual.txt').write_text('preserve')
                with self.assertRaises(RuntimeError): deploy.check_destination(sftp)
                self.assertEqual(sftp.path(destination+'/manual.txt').read_text(),'preserve')
    def test_deploy_removes_only_managed_old_files(self):
        with tempfile.TemporaryDirectory() as td:
            sftp=FakeSFTP(td)
            folder=sftp.path('/biligio/www/gallery');folder.mkdir(parents=True)
            (folder/deploy.MARKER).write_text(deploy.MARKER_TEXT)
            (folder/'old.html').write_text('old')
            (folder/deploy.MANIFEST).write_text(json.dumps({'old.html':'old-hash'}))
            output=Path(td)/'build';output.mkdir();(output/'index.html').write_text('new')
            with patch.object(deploy,'OUTPUT',output):
                deploy.sync(sftp,'/biligio/www/gallery',True,'deploy')
                self.assertFalse((folder/'old.html').exists())
                self.assertEqual((folder/'index.html').read_text(),'new')
                (folder/'manual.txt').write_text('manual')
                writes=sftp.writes
                with self.assertRaises(RuntimeError): deploy.sync(sftp,'/biligio/www/gallery',True,'deploy')
                self.assertEqual(sftp.writes,writes)

class HomepageTests(unittest.TestCase):
    def fixture(self, td):
        sftp=FakeSFTP(td)
        sftp.path('/biligio/www/mobile').mkdir(parents=True)
        sftp.path('/biligio/DataBackup').mkdir()
        plan={}
        for name in sorted(home.ALLOWED):
            before=b'<nav>HOME</nav>';after=b'<nav>HOME GALLERY</nav>'
            sftp.path('/biligio/www/'+name).write_bytes(before)
            plan[name]=dict(before_sha256=home.digest(before), after_sha256=home.digest(after), replacements=[['HOME','HOME GALLERY']])
        path=Path(td)/'plan.json';path.write_text(json.dumps(plan))
        return sftp,path
    def test_backup_install_and_idempotence(self):
        with tempfile.TemporaryDirectory() as td:
            sftp,plan=self.fixture(td)
            with patch.object(home,'PLAN',plan):
                changes=home.prepare(sftp,'/biligio/www')
                self.assertEqual(sftp.writes,0)
                home.apply(sftp,'/biligio/www',changes)
                self.assertEqual(home.prepare(sftp,'/biligio/www'),[])
                backups=list(sftp.path('/biligio/DataBackup').glob('*/*'))
                self.assertEqual(len(backups),2)
                self.assertTrue(all(p.read_bytes()==b'<nav>HOME</nav>' for p in backups))
    def test_changed_server_file_blocks_all_writes(self):
        with tempfile.TemporaryDirectory() as td:
            sftp,plan=self.fixture(td)
            sftp.path('/biligio/www/mobile/index.html').write_text('new owner edit')
            with patch.object(home,'PLAN',plan):
                with self.assertRaises(RuntimeError): home.prepare(sftp,'/biligio/www')
                self.assertEqual(sftp.writes,0)
    def test_symlink_mobile_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            sftp,plan=self.fixture(td)
            shutil.rmtree(sftp.path('/biligio/www/mobile'))
            sftp.path('/biligio/www/mobile').symlink_to(sftp.path('/biligio/DataBackup'),target_is_directory=True)
            with patch.object(home,'PLAN',plan):
                with self.assertRaises(RuntimeError): home.prepare(sftp,'/biligio/www')
                self.assertEqual(sftp.writes,0)

if __name__=='__main__': unittest.main()
