"""Local run isolation, atomic artifacts and explicit retention."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .contracts import canonical
from .errors import BIError

_ATOMIC_REPLACE_MAX_RETRIES = 2
_ATOMIC_REPLACE_RETRY_DELAYS = (0.01, 0.05)
_WINDOWS_TRANSIENT_REPLACE_ERRORS = frozenset({5, 32, 33})


def _is_windows_replace_transient(error: OSError) -> bool:
    """Recognize only bounded Windows replace contention, never arbitrary OSError."""
    if os.name != "nt":
        return False
    winerror = getattr(error, "winerror", None)
    if winerror is not None:
        return winerror in _WINDOWS_TRANSIENT_REPLACE_ERRORS
    return isinstance(error, PermissionError)


def _replace_atomically(source: Path, target: Path) -> None:
    for attempt in range(_ATOMIC_REPLACE_MAX_RETRIES + 1):
        try:
            os.replace(source, target)
            return
        except OSError as error:
            if (
                not _is_windows_replace_transient(error)
                or attempt >= _ATOMIC_REPLACE_MAX_RETRIES
            ):
                raise
            time.sleep(_ATOMIC_REPLACE_RETRY_DELAYS[attempt])


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def default_root() -> Path:
    configured = os.environ.get("BI_ANALYST_RUNTIME")
    if configured:
        return Path(configured)
    suffix = f"-{os.getuid()}" if hasattr(os, "getuid") else ""
    return Path(tempfile.gettempdir()) / f"evidence-bi{suffix}"


def safe_directory(path: Path) -> Path:
    path = Path(path).absolute()
    # Resolve the existing ancestor (e.g. /tmp -> /private/tmp), but never an app-owned link.
    if path.is_symlink():
        raise BIError("UNSAFE_PATH", "Managed directories must not be symbolic links.")
    for parent in path.parents:
        if parent.is_symlink() and str(parent) not in {"/tmp", "/var"}:
            raise BIError(
                "UNSAFE_PATH", "Managed storage has an unexpected symbolic-link ancestor."
            )
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not path.is_dir():
        raise BIError("UNSAFE_PATH", "Managed storage is not a directory.")
    resolved = path.resolve()
    os.chmod(resolved, 0o700)
    return resolved


def atomic_bytes(path: Path, content: bytes) -> None:
    if path.is_symlink():
        raise BIError("UNSAFE_PATH", "Managed artifacts must not be symbolic links.")
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".partial-", delete=False
        ) as stream:
            temp_path = Path(stream.name)
            os.chmod(temp_path, 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        _replace_atomically(temp_path, path)
    except OSError:
        raise BIError("STORAGE_ERROR", "Artifact could not be written atomically.") from None
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


class RunStore:
    def __init__(self, root: Path | None = None, *, owner: str = "local"):
        try:
            self.root = safe_directory(root or default_root())
            self.runs = safe_directory(self.root / "runs")
        except OSError:
            raise BIError("STORAGE_ERROR", "Runtime storage is unavailable.") from None
        self.owner = owner

    def _path(self, run_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise BIError("INVALID_RUN_ID", "Invalid run identifier.")
        if self.root.is_symlink() or self.runs.is_symlink():
            raise BIError("UNSAFE_PATH", "Managed directories must not be symbolic links.")
        path = self.runs / run_id
        if path.is_symlink() or path.resolve().parent != self.runs:
            raise BIError("UNSAFE_PATH", "Run directory is outside managed storage.")
        return path

    def create(self, *, ttl_hours: int = 24, metadata: dict | None = None) -> str:
        run_id = uuid.uuid4().hex
        path = self._path(run_id)
        path.mkdir(mode=0o700)
        moment = now_utc()
        manifest = {
            **(metadata or {}),
            "schema_version": "1.0",
            "run_id": run_id,
            "owner": self.owner,
            "created_at": moment.isoformat(),
            "updated_at": moment.isoformat(),
            "expires_at": (moment + timedelta(hours=ttl_hours)).isoformat(),
            "saved": False,
            "status": "CREATED",
        }
        atomic_bytes(path / "manifest.json", canonical(manifest).encode())
        return run_id

    def manifest(self, run_id: str, *, allow_expired=False) -> dict:
        path = self._path(run_id) / "manifest.json"
        if path.is_symlink():
            raise BIError("UNSAFE_PATH", "Managed artifacts must not be symbolic links.")
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            if manifest.get("schema_version") != "1.0" or manifest.get("run_id") != run_id:
                raise BIError("INVALID_MANIFEST", "Run manifest is incompatible or corrupt.")
            if manifest.get("owner") != self.owner:
                raise BIError("ACCESS_DENIED", "This run belongs to a different session.")
            if (
                not allow_expired
                and not manifest["saved"]
                and now_utc() >= datetime.fromisoformat(manifest["expires_at"])
            ):
                raise BIError("RUN_EXPIRED", "Run retention expired; start a new run.")
            return manifest
        except (OSError, ValueError, KeyError, TypeError):
            raise BIError("RUN_UNAVAILABLE", "Run is missing, unreadable or corrupt.") from None

    def write(self, run_id: str, name: str, value: dict | list) -> None:
        self.manifest(run_id)
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}\.json", name) or name == "manifest.json":
            raise BIError("INVALID_ARTIFACT", "Artifact name is not allowed.")
        atomic_bytes(self._path(run_id) / name, canonical(value).encode("utf-8"))

    def read(self, run_id: str, name: str) -> dict | list:
        self.manifest(run_id)
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}\.json", name):
            raise BIError("INVALID_ARTIFACT", "Artifact name is not allowed.")
        path = self._path(run_id) / name
        if path.is_symlink():
            raise BIError("UNSAFE_PATH", "Managed artifacts must not be symbolic links.")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise BIError("ARTIFACT_UNAVAILABLE", "Artifact is missing or unreadable.") from None

    def update(self, run_id: str, **changes) -> dict:
        manifest = self.manifest(run_id)
        if set(changes) & {"owner", "run_id", "schema_version", "created_at"}:
            raise BIError("INVALID_UPDATE", "Run identity cannot be changed.")
        manifest.update(changes, updated_at=now_utc().isoformat())
        atomic_bytes(self._path(run_id) / "manifest.json", canonical(manifest).encode())
        return manifest

    def delete(self, run_id: str) -> None:
        self.manifest(run_id, allow_expired=True)
        path = self._path(run_id)
        if any(child.is_symlink() for child in path.rglob("*")):
            raise BIError("UNSAFE_PATH", "Run contains an unexpected link; deletion stopped.")
        try:
            shutil.rmtree(path)
        except OSError:
            raise BIError("DELETE_FAILED", "Not all run artifacts could be deleted.") from None

    def list_runs(self) -> list[dict]:
        result = []
        for path in sorted(self.runs.iterdir()):
            if not re.fullmatch(r"[a-f0-9]{32}", path.name):
                continue
            try:
                result.append(self.manifest(path.name, allow_expired=True))
            except BIError:
                continue
        return result

    def cleanup_expired(self) -> list[str]:
        deleted = []
        for manifest in self.list_runs():
            if not manifest["saved"] and now_utc() >= datetime.fromisoformat(
                manifest["expires_at"]
            ):
                self.delete(manifest["run_id"])
                deleted.append(manifest["run_id"])
        return deleted


def local_session_manifests(root: Path | None = None):
    """Trusted OS-user maintenance only; never expose owner selection to HTTP/model tools."""
    maintenance = RunStore(root)
    for path in maintenance.runs.iterdir():
        if not re.fullmatch(r"[a-f0-9]{32}", path.name) or path.is_symlink():
            continue
        manifest_path = path / "manifest.json"
        if manifest_path.is_symlink():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            owner = manifest.get("owner")
            if not isinstance(owner, str) or len(owner) > 128:
                continue
            scoped = RunStore(maintenance.root, owner=owner)
            checked = scoped.manifest(path.name, allow_expired=True)
            yield scoped, checked
        except (BIError, OSError, ValueError, TypeError, KeyError):
            continue


def cleanup_expired_sessions(root: Path | None = None) -> int:
    """Clean abandoned browser sessions using the trusted local maintenance boundary."""
    deleted = 0
    for scoped, checked in local_session_manifests(root):
        if not checked["saved"] and now_utc() >= datetime.fromisoformat(checked["expires_at"]):
            try:
                scoped.delete(checked["run_id"])
                deleted += 1
            except BIError:
                continue
    return deleted
