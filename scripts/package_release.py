"""Create a deterministic, public-safe release set from an exact allowlist.

The release set is intentionally separate from the working tree.  Tracked files
are read from their current working-copy bytes; only explicitly listed untracked
files may be added.  No recursive include-all fallback is allowed.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import zipfile
from pathlib import Path, PureWindowsPath

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_EXTRA_MANIFEST = ROOT / "docs" / "RELEASE_PUBLIC_EXTRA_FILES_R3.json"

DENIED_DIR_NAMES = {
    ".git",
    ".venv",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    ".codex",
    "run_store",
    "runtime",
    ".pbi",
    "cache",
    "tmp",
    "temp",
}
DENIED_FILE_NAMES = {
    ".env",
    ".env.local",
    "credentials.json",
    "live_config.json",
    "localsettings.json",
    "cache.abf",
}
DENIED_NAME_PARTS = (
    "live_config.m5_",
    "desktop_screen",
    "scratch_",
    "one_time_key",
)
DENIED_SUFFIXES = {".pyc", ".pyo", ".pyd", ".log", ".tmp", ".zip"}
DENIED_PATH_PREFIXES = (
    "deliverables/PowerBI_Demo_Current/",
    "deliverables/PowerBI_Demo_Refresh_R1/",
)
DENIED_EXACT_PATHS = {
    # Internal checkpoints and historical verification records can contain
    # workstation-specific paths; they are not public release inputs.
    "docs/BUILD_PROGRESS.md",
    "docs/DASHBOARD_REFRESH_REVIEW.md",
    "docs/FINAL_HARDENING_TODO.md",
    "docs/LEARNING_PORTFOLIO_DRAFT.md",
    "docs/RESUME_CHECKPOINT.md",
    "docs/RELEASE_REPAIR_PROGRESS.md",
    "docs/WINDOWS_HANDOFF.md",
    "deliverables/verification/dashboard_refresh_r2/static-verification.json",
    "deliverables/verification/t15-candidate-verification.json",
    "deliverables/verification/t19_streamlit_walkthrough_20260924.json",
}


class PackagingError(ValueError):
    """Raised when a release input violates the public packaging contract."""


_ABSOLUTE_MACHINE_PATH = re.compile(
    rb"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/]|\\\\[A-Za-z0-9_.-]+[\\/]|/(?:Users|home|private|tmp|var/folders|workspace|workspaces)(?:/|$))"
)


def contains_absolute_machine_path_marker(data: bytes | str) -> bool:
    """Detect common local-machine path markers without exposing file contents."""

    payload = data.encode("utf-8", errors="ignore") if isinstance(data, str) else data
    return _ABSOLUTE_MACHINE_PATH.search(payload) is not None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _normalise_rel_path(rel_path: str) -> str:
    value = str(rel_path).replace("\\", "/")
    windows = PureWindowsPath(value)
    if not value or value.startswith(("/", "//")) or windows.drive:
        raise PackagingError(f"absolute or drive path is not allowed: {rel_path!r}")
    parts = tuple(part for part in value.split("/") if part)
    if not parts or ".." in parts or "." in parts:
        raise PackagingError(f"traversal or empty path is not allowed: {rel_path!r}")
    return "/".join(parts)


def _deny_reason(rel_path: str) -> str | None:
    parts = rel_path.split("/")
    name = parts[-1].lower()
    if rel_path in DENIED_EXACT_PATHS:
        return "internal record or machine-specific verification"
    if any(rel_path.startswith(prefix) for prefix in DENIED_PATH_PREFIXES):
        return "superseded or local demo artifact"
    if any(part.lower() in DENIED_DIR_NAMES for part in parts):
        return "private/runtime/cache directory"
    if name in DENIED_FILE_NAMES or name.startswith(".env."):
        return "credential or local configuration file"
    if any(marker in name for marker in DENIED_NAME_PARTS):
        return "operational or scratch file"
    if Path(name).suffix in DENIED_SUFFIXES:
        return "cache or archive suffix"
    if rel_path == "docs/RELEASE_FILESET.json":
        return "historical self-manifest"
    return None


def is_included(rel_path: str) -> bool:
    """Return whether a normalized path is syntactically public-safe.

    This is a deny check only.  `collect_release_files` separately authorizes
    each path through Git or the exact extras manifest.
    """

    try:
        normalized = _normalise_rel_path(rel_path)
    except PackagingError:
        return False
    return _deny_reason(normalized) is None


def _assert_regular_inside(root: Path, rel_path: str) -> Path:
    normalized = _normalise_rel_path(rel_path)
    path = root / Path(*normalized.split("/"))
    if not path.exists() or not path.is_file():
        raise PackagingError(f"selected file is missing or not a file: {normalized}")
    if path.is_symlink() or getattr(path.stat(), "st_file_attributes", 0) & 0x400:
        raise PackagingError(f"symlink/reparse file is not allowed: {normalized}")
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as error:
        raise PackagingError(f"selected file escapes root: {normalized}") from error
    reason = _deny_reason(normalized)
    if reason:
        raise PackagingError(f"selected file denied ({reason}): {normalized}")
    return path


def _tracked_paths(root: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached"],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise PackagingError("Git is required to select tracked working-copy files") from error
    return [item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def _extra_paths(root: Path) -> list[str]:
    if not PUBLIC_EXTRA_MANIFEST.is_file():
        raise PackagingError(f"missing exact public extras manifest: {PUBLIC_EXTRA_MANIFEST}")
    try:
        payload = json.loads(PUBLIC_EXTRA_MANIFEST.read_text(encoding="utf-8"))
        paths = payload["files"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise PackagingError("public extras manifest is invalid") from error
    if not isinstance(paths, list) or not all(isinstance(item, str) for item in paths):
        raise PackagingError("public extras manifest files must be a list of strings")
    return paths


def _selected_paths(root: Path = ROOT) -> list[str]:
    selected = set()
    for rel_path in _tracked_paths(root):
        normalized = _normalise_rel_path(rel_path)
        if (root / Path(*normalized.split("/"))).is_file() and is_included(normalized):
            selected.add(normalized)
    for rel_path in _extra_paths(root):
        normalized = _normalise_rel_path(rel_path)
        _assert_regular_inside(root, normalized)
        selected.add(normalized)
    if not selected:
        raise PackagingError("exact public selection is empty")
    return sorted(selected, key=lambda item: item.casefold())


def _validate_selection(root: Path, paths: list[str]) -> list[dict[str, str | int]]:
    records = []
    seen: set[str] = set()
    for rel_path in paths:
        normalized = _normalise_rel_path(rel_path)
        collision_key = normalized.casefold()
        if collision_key in seen:
            raise PackagingError(f"case-insensitive archive collision: {normalized}")
        seen.add(collision_key)
        path = _assert_regular_inside(root, normalized)
        records.append(
            {
                "path": normalized,
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    # Scan selected machine-readable evidence without echoing its contents.
    # Source/tests may intentionally contain example path strings and are not
    # evidence records, so they are excluded from this content scan by type.
    for record in records:
        rel_path = str(record["path"])
        if Path(rel_path).suffix.lower() != ".json":
            continue
        data = (root / Path(*rel_path.split("/"))).read_bytes()
        if contains_absolute_machine_path_marker(data):
            raise PackagingError(
                f"selected JSON contains an absolute machine path: {rel_path}"
            )
    return records


def collect_release_files(root: Path = ROOT) -> list[dict[str, str | int]]:
    return _validate_selection(root, _selected_paths(root))


def _manifest_records(manifest_path: Path, root: Path) -> list[dict[str, str | int]]:
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        records = payload["files"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise PackagingError("release manifest is invalid") from error
    if not isinstance(records, list):
        raise PackagingError("release manifest files must be a list")
    if payload.get("file_count", len(records)) != len(records):
        raise PackagingError("release manifest file_count does not match files")
    normalized_records: list[dict[str, str | int]] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise PackagingError("release manifest contains an invalid file record")
        normalized = _normalise_rel_path(str(record["path"]))
        if normalized.casefold() in seen:
            raise PackagingError(f"case-insensitive archive collision: {normalized}")
        seen.add(normalized.casefold())
        digest = record.get("sha256")
        size = record.get("size_bytes")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
        ):
            raise PackagingError(f"release manifest has invalid metadata: {normalized}")
        _assert_regular_inside(root, normalized)
        normalized_records.append(
            {"path": normalized, "sha256": digest, "size_bytes": size}
        )
    return normalized_records


def _read_manifest_bytes(
    root: Path, records: list[dict[str, str | int]]
) -> list[tuple[str, bytes]]:
    """Read each selected file once and verify the bytes named by the manifest."""

    entries: list[tuple[str, bytes]] = []
    for record in records:
        rel_path = str(record["path"])
        path = _assert_regular_inside(root, rel_path)
        data = path.read_bytes()
        expected_size = int(record["size_bytes"])
        expected_hash = str(record["sha256"])
        actual_hash = hashlib.sha256(data).hexdigest()
        if len(data) != expected_size or actual_hash != expected_hash:
            raise PackagingError(f"selected file changed since the manifest was written: {rel_path}")
        entries.append((rel_path, data))
    return entries


def write_fileset_manifest(
    output_path: Path = ROOT / "docs/RELEASE_FILESET_R3.json",
    *,
    root: Path = ROOT,
) -> dict:
    if output_path.exists():
        raise PackagingError(f"refusing to overwrite existing manifest: {output_path}")
    files = collect_release_files(root)
    data = {"schema_version": "1.0", "release_id": "EVIDENCE-BI-RELEASE-R3", "file_count": len(files), "files": files}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return data


def create_release_zip(
    zip_path: Path = ROOT / "deliverables/evidence-bi-release-r3.zip",
    *,
    root: Path = ROOT,
    manifest_path: Path | None = None,
) -> str:
    if zip_path.exists() or zip_path.is_symlink():
        raise PackagingError(f"refusing to overwrite existing archive: {zip_path}")
    if manifest_path is None:
        raise PackagingError("an exact release manifest is required to create an archive")
    files = _manifest_records(manifest_path, root)
    entries = _read_manifest_bytes(root, files)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    created_output = False
    try:
        with zipfile.ZipFile(zip_path, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            created_output = True
            for rel_path, data in entries:
                archive.writestr(rel_path, data)
    except Exception:
        if created_output and zip_path.exists():
            zip_path.unlink()
        raise
    return sha256_file(zip_path)


if __name__ == "__main__":
    raise SystemExit("Use write_fileset_manifest/create_release_zip from a reviewed R3 task; no implicit workspace scan.")
