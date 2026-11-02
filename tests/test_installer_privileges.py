"""Optional Linux/root qualification, entirely inside a disposable fixture.

Run with the standard library: sudo python3 tests/test_installer_privileges.py
No packages, real services or station data are changed. Regular pytest skips
these checks without Linux/root; the ordinary installer tests remain portable.
"""
import importlib.util
import os
from pathlib import Path
import pwd
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "deploy" / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


files = module("privilege_files", "install-files.py")
station = module("privilege_installer", "install-station.py")


@unittest.skipUnless(sys.platform == "linux" and os.geteuid() == 0, "isolated Linux/root qualification")
class InstallerPrivileges(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="opt-station-security-", dir="/var/tmp")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.base.chmod(0o711)
        ordinary = pwd.getpwnam(os.environ.get("SUDO_USER") or "nobody")
        self.assertNotEqual(ordinary.pw_uid, 0)
        self.home = self.base / "home"
        self.home.mkdir(mode=0o700)
        os.chown(self.home, ordinary.pw_uid, ordinary.pw_gid)
        self.account = SimpleNamespace(pw_dir=str(self.home), pw_name=ordinary.pw_name,
                                       pw_uid=ordinary.pw_uid, pw_gid=ordinary.pw_gid)
        self.protected = self.base / "system"
        self.protected.mkdir(mode=0o700)
        self.victim = self.protected / "unit.conf"
        self.victim.write_text("root-only sentinel\n")
        self.victim.chmod(0o600)
        self.before = self.victim.stat()

    def user_file(self):
        with files.account_access(self.account):
            folder = self.home / "config"
            folder.mkdir(mode=0o700, exist_ok=True)
            path = folder / "unit.conf"
            path.write_text("user configuration\n")
            path.chmod(0o640)
        return path

    def transaction(self):
        return files.Transaction(self.base / "backups/files", self.account)

    def assert_protected(self):
        self.assertEqual(self.victim.read_text(), "root-only sentinel\n")
        now = self.victim.stat()
        self.assertEqual((now.st_uid, now.st_gid, now.st_mode),
                         (self.before.st_uid, self.before.st_gid, self.before.st_mode))
        self.assertEqual(os.geteuid(), 0)

    def test_legitimate_capture_write_and_restore_keep_user_and_system_ownership(self):
        path = self.user_file()
        tx = self.transaction()
        tx.write(path, "updated user\n", self.account.pw_uid, self.account.pw_gid)
        tx.write(self.victim, "updated system\n")
        with files.account_access(self.account):
            with self.assertRaises(PermissionError):
                list(tx.folder.iterdir())
        tx.restore()
        self.assertEqual(path.read_text(), "user configuration\n")
        self.assertEqual(path.stat().st_uid, self.account.pw_uid)
        self.assertEqual(path.stat().st_mode & 0o777, 0o640)
        self.assert_protected()

    def test_replaced_parent_cannot_redirect_privileged_write(self):
        path = self.user_file()
        tx = self.transaction()
        with files.account_access(self.account):
            path.parent.rename(self.home / "original-config")
            path.parent.symlink_to(self.protected, target_is_directory=True)
        with self.assertRaises(PermissionError):
            tx.write(path, "must not escape\n", self.account.pw_uid, self.account.pw_gid)
        self.assert_protected()

    def test_replaced_parent_cannot_redirect_privileged_rollback(self):
        path = self.user_file()
        tx = self.transaction()
        tx.write(path, "updated user\n", self.account.pw_uid, self.account.pw_gid)
        # The system copy is restored before encountering the poisoned user path.
        tx.write(self.victim, "updated system\n")
        with files.account_access(self.account):
            path.parent.rename(self.home / "original-config")
            path.parent.symlink_to(self.protected, target_is_directory=True)
        with self.assertRaises(PermissionError):
            tx.restore()
        self.assert_protected()

    def test_source_link_substituted_between_stat_and_open_is_not_copied(self):
        path = self.user_file()
        tx = self.transaction()
        original = os.open

        def substitute(value, *args, **kwargs):
            if value == path:
                self.assertEqual(os.geteuid(), self.account.pw_uid)
                path.unlink()
                path.symlink_to(self.victim)
            return original(value, *args, **kwargs)

        with patch.object(os, "open", substitute):
            with self.assertRaises(OSError):
                tx.capture(path)
        self.assertFalse((tx.folder / "0").exists())
        self.assert_protected()

    def test_temporary_link_cannot_redirect_file_metadata(self):
        path = self.user_file()
        tx = self.transaction()
        original = tempfile.mkstemp

        def substitute(*args, **kwargs):
            descriptor, name = original(*args, **kwargs)
            self.assertEqual(os.geteuid(), self.account.pw_uid)
            Path(name).unlink()
            Path(name).symlink_to(self.victim)
            return descriptor, name

        with patch.object(tempfile, "mkstemp", substitute):
            tx.write(path, "user update\n", self.account.pw_uid, self.account.pw_gid)
        self.assert_protected()

    def test_unit_validation_refuses_preplanted_link_with_user_rights(self):
        with files.account_access(self.account):
            folder = self.home / "unit-check"
            folder.mkdir(mode=0o700)
            (folder / "openprinttag.service").symlink_to(self.victim)
        instance = SimpleNamespace(account=self.account, home=self.home, source=self.home,
                                   data=self.home / "data", mode="hardware", camera=True)
        temporary = SimpleNamespace(name=str(folder), cleanup=lambda: None)
        with patch.object(tempfile, "TemporaryDirectory", return_value=temporary):
            with self.assertRaises(FileExistsError):
                station.Installer.validate_service(instance)
        self.assert_protected()

    def test_user_owned_backup_ancestor_is_refused(self):
        parent = self.base / "unsafe-backups"
        parent.mkdir()
        os.chown(parent, self.account.pw_uid, self.account.pw_gid)
        with self.assertRaises(ValueError):
            files.Transaction(parent / "snapshot/files", self.account)
        self.assertFalse((parent / "snapshot").exists())
        self.assert_protected()

    def test_archive_child_drops_real_uid_and_cannot_read_protected_files(self):
        path = self.user_file()
        archive = self.base / "snapshot.tar.gz"
        identity = files.child_identity(self.account)
        for flag in ("-u", "-ru"):
            result = subprocess.run(["/usr/bin/id", flag], capture_output=True, text=True, check=True, **identity)
            self.assertEqual(int(result.stdout), self.account.pw_uid)
        with archive.open("xb") as output:
            subprocess.run(["/usr/bin/tar", "-czpf", "-", "-C", str(path.parent), "."],
                           check=True, stdout=output, **identity)
        with tarfile.open(archive) as saved:
            self.assertEqual(saved.extractfile("./unit.conf").read(), b"user configuration\n")
        result = subprocess.run(["/usr/bin/tar", "-czpf", "-", "-C", str(self.protected), "."],
                                capture_output=True, **identity)
        self.assertNotEqual(result.returncode, 0)
        self.assert_protected()


if __name__ == "__main__":
    unittest.main(verbosity=2)
