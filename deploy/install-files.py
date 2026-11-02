"""Installer file transactions: user paths never inherit root filesystem rights.

Only trusted, synchronous file operations belong inside account_access. Child
processes must drop their real/saved identities too (runuser or Popen user=).
Rollback copies stay outside the station account's writable directory tree.
"""
from contextlib import contextmanager, nullcontext
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile


@contextmanager
def account_access(account):
    if os.geteuid() != 0:
        if os.geteuid() != account.pw_uid:
            raise PermissionError("Les fichiers de la station exigent son compte utilisateur.")
        yield
        return
    uid, gid, groups = os.geteuid(), os.getegid(), os.getgroups()
    try:
        os.setgroups(os.getgrouplist(account.pw_name, account.pw_gid))
        os.setegid(account.pw_gid)
        os.seteuid(account.pw_uid)
        yield
    finally:
        os.seteuid(uid)
        os.setegid(gid)
        os.setgroups(groups)


def child_identity(account):
    """Popen permanently drops UID, GID and supplementary groups before exec."""
    return dict(user=account.pw_uid, group=account.pw_gid,
                extra_groups=os.getgrouplist(account.pw_name, account.pw_gid))


def private_directory(path):
    if os.geteuid() == 0:
        if not path.is_absolute():
            raise ValueError("Une sauvegarde système exige un chemin absolu.")
        descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        try:
            # Pin each ancestor while opening/creating the next one. A sticky
            # root-owned /tmp is safe only because every child is also root-owned.
            for part in path.parts[1:]:
                try:
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                except FileNotFoundError:
                    os.mkdir(part, mode=0o700, dir_fd=descriptor)
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
                info = os.fstat(descriptor)
                if info.st_uid != 0 or (info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX):
                    raise ValueError(f"Parent de sauvegarde accessible à un autre compte : {path}")
            os.fchmod(descriptor, 0o700)
        finally:
            os.close(descriptor)
        return
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
        raise ValueError(f"Dossier de sauvegarde système non reconnu : {path}")
    path.chmod(0o700)


class Transaction:
    """Save selected files privately; restore each with its original authority."""
    def __init__(self, folder, account=None):
        self.folder, self.account = Path(folder), account
        if account and self.folder.is_relative_to(Path(account.pw_dir)):
            raise ValueError("Les sauvegardes système doivent rester hors du dossier utilisateur.")
        private_directory(self.folder.parent)
        private_directory(self.folder)
        self.saved = []
        self.created_dirs, self.directory_modes = [], []

    def access(self, path):
        if self.account and Path(path).is_relative_to(Path(self.account.pw_dir)):
            return account_access(self.account)
        return nullcontext()

    def capture(self, path):
        path = Path(path)
        if any(item[0] == path for item in self.saved):
            return
        copy, link, descriptor = None, None, None
        with self.access(path):
            try:
                old = path.lstat()
            except FileNotFoundError:
                old = None
            if old:
                if stat.S_ISLNK(old.st_mode):
                    link = os.readlink(path)
                elif stat.S_ISREG(old.st_mode):
                    # Open the source with user rights, never reopen it as root.
                    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                    old = os.fstat(descriptor)
                    if not stat.S_ISREG(old.st_mode):
                        os.close(descriptor)
                        raise ValueError(f"Fichier de configuration non reconnu : {path}")
                else:
                    raise ValueError(f"Ce chemin doit être un fichier ou un lien : {path}")
        if descriptor is not None:
            copy = self.folder / str(len(self.saved))
            with os.fdopen(descriptor, "rb") as source, copy.open("xb") as output:
                os.fchmod(output.fileno(), 0o600)
                shutil.copyfileobj(source, output)
        self.saved.append((path, old, copy, link))
        (self.folder / "manifest.json").write_text(json.dumps([
            {"path": str(p), "existed": info is not None, "copy": saved.name if saved else None,
             "link": target, "uid": info.st_uid if info else None, "gid": info.st_gid if info else None,
             "mode": stat.S_IMODE(info.st_mode) if info else None}
            for p, info, saved, target in self.saved], indent=2) + "\n")

    def _write(self, path, content, uid, gid, mode):
        # Callers already selected the path's authority. Metadata is applied to
        # the open temporary file, even for system paths and HTTPS setup.
        descriptor, temporary = tempfile.mkstemp(prefix=".opt-install-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as output:
                os.fchmod(output.fileno(), mode)
                if os.geteuid() == 0:
                    os.fchown(output.fileno(), uid, gid)
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def write(self, path, text, uid=0, gid=0, mode=0o600):
        path = Path(path)
        self.capture(path)
        with self.access(path):
            if path.is_symlink():
                raise ValueError(f"Un fichier de configuration est un lien symbolique : {path}")
            parents, parent = [], path.parent
            while not parent.exists():
                parents.append(parent)
                parent = parent.parent
            for parent in reversed(parents):
                permissions = 0o755 if uid == 0 else 0o700
                parent.mkdir(mode=permissions)
                parent.chmod(permissions)
                if os.geteuid() == 0:
                    os.chown(parent, uid, gid)
                self.created_dirs.append(parent)
            parent = path.parent
            if (uid == 0 and mode & 0o044 and parent not in self.created_dirs
                    and parent.stat().st_uid == 0 and not any(parent.iterdir())):
                previous = stat.S_IMODE(parent.stat().st_mode)
                if previous != 0o755:
                    self.directory_modes.append((parent, previous))
                    parent.chmod(0o755)
            self._write(path, text.encode(), uid, gid, mode)
        (self.folder / "directories.json").write_text(json.dumps({
            "created": list(map(str, self.created_dirs)),
            "permissions_before": [{"path": str(p), "mode": old} for p, old in self.directory_modes],
        }, indent=2) + "\n")

    def link(self, path, target):
        self.capture(path)
        with self.access(path):
            temporary = path.with_name(path.name + ".install-next")
            if temporary.exists() or temporary.is_symlink():
                raise ValueError(f"Un ancien lien temporaire doit être examiné : {temporary}")
            temporary.symlink_to(target)
            os.replace(temporary, path)

    def restore(self):
        for path, old, copy, link in reversed(self.saved):
            # Read only the protected copy as root; all destination operations
            # on home use the ordinary account, including replaced parents.
            content = copy.read_bytes() if copy else None
            with self.access(path):
                if path.is_symlink() or path.is_file():
                    path.unlink()
                if not old:
                    continue
                if link is not None:
                    path.symlink_to(link)
                    if os.geteuid() == 0:
                        os.lchown(path, old.st_uid, old.st_gid)
                else:
                    self._write(path, content, old.st_uid, old.st_gid, stat.S_IMODE(old.st_mode))
        for path, mode in reversed(self.directory_modes):
            with self.access(path):
                path.chmod(mode)
        for path in reversed(self.created_dirs):
            with self.access(path):
                try:
                    path.rmdir()
                except OSError:
                    pass  # Keep directories now containing other components' files.
