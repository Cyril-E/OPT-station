"""The system installer holds this lock while replacing a station's sources.

Read-only health checks remain available. Writes and scheduled backups wait
until activation or rollback finishes. A crashed installer releases the lock.
"""
from pathlib import Path

INSTALL_LOCK = Path("/run/lock/opt-station-install.lock")


def installation_busy():
    try:
        import fcntl
        with INSTALL_LOCK.open("rb") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
        return False
    except FileNotFoundError:
        return False
    except ImportError:
        return False
    except OSError:
        # A present but unreadable system lock must not allow writes.
        return True
