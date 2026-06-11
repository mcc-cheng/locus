"""Source-file preservation (Phase 1.2).

Byte-exact copies of every uploaded CSV, hashed at copy time and re-verified on
launch. See docs/specs/phase-1.2-source-preservation.md.
"""

from __future__ import annotations

import hashlib
import shutil
import stat
from pathlib import Path

from .models import CheckResult

_CHUNK = 1 << 20  # 1 MiB


def sha256_file(path: str | Path) -> str:
    """SHA-256 hex digest of a file, read in chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def preserve_source(source_root: Path, section: str, csv_path: Path) -> tuple[Path, str]:
    """Copy ``csv_path`` verbatim into ``source_root/<section>/`` and hash it.

    Returns ``(dest_path, sha256)``. Raises ``OSError`` if the copy is corrupt
    (its hash differs from the original's).
    """
    original_hash = sha256_file(csv_path)
    dest_dir = source_root / section
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / csv_path.name
    # copy2 preserves metadata; we then strip write permissions.
    shutil.copy2(csv_path, dest)

    copy_hash = sha256_file(dest)
    if copy_hash != original_hash:
        # Copy was corrupted in transit; do not proceed.
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise OSError(
            f"source copy corrupted: {csv_path.name} hash {original_hash} != copy {copy_hash}"
        )

    _make_read_only(dest)
    return dest, copy_hash


def discard_staged_source(source_root: Path, section: str) -> None:
    """Remove a section's staged source dir (used when an ingest is rejected)."""
    # Read-only files must be made writable before removal on some platforms.
    shutil.rmtree(source_root / section, ignore_errors=True, onerror=_force_remove)


def verify_source(dest: Path, expected_sha256: str, *, section: str) -> CheckResult:
    """Re-hash a preserved source file and compare to the recorded hash."""
    if not dest.exists():
        return CheckResult(
            name="source_sha256",
            column=section,
            passed=False,
            expected=expected_sha256,
            actual=None,
            detail=f"preserved source missing: {dest}",
        )
    actual = sha256_file(dest)
    passed = actual == expected_sha256
    return CheckResult(
        name="source_sha256",
        column=section,
        passed=passed,
        expected=expected_sha256,
        actual=actual,
        detail="source intact" if passed else "source hash mismatch (corrupted or tampered)",
    )


def _make_read_only(path: Path) -> None:
    path.chmod(path.stat().st_mode & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH)


def _force_remove(func, path, _exc) -> None:
    import os

    os.chmod(path, stat.S_IWUSR | stat.S_IRUSR)
    func(path)
