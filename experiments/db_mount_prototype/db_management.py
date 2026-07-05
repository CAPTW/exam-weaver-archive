from __future__ import annotations

import json
import gc
import re
import sqlite3
import time
from pathlib import Path
from typing import Dict

from .exam_move import ExamCopyResult, apply_exam_copy
from .mount_repo import MountedDatabase, load_manifest


WINDOWS_RESERVED_FILENAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def rename_mount_label(manifest_path: str | Path, mount_id: str, label: str) -> None:
    manifest = Path(manifest_path).resolve()
    payload = _read_manifest_payload(manifest)
    updated = False
    for row in payload.get("mounts", []):
        if row.get("id") == mount_id:
            row["label"] = _clean_label(label)
            updated = True
            break
    if not updated:
        raise ValueError(f"mount id not found: {mount_id}")
    _write_manifest_payload(manifest, payload)


def rename_mount_database(manifest_path: str | Path, mount_id: str, label: str) -> MountedDatabase:
    """Rename a writable mounted DB's user-facing label and backing .db file together."""
    manifest = Path(manifest_path).resolve()
    payload = _read_manifest_payload(manifest)
    row = _find_manifest_row(payload, mount_id)
    old_mount = MountedDatabase.from_manifest_row(row, manifest.parent)
    if old_mount.read_only:
        raise PermissionError(f"read-only mount cannot be renamed with file move: {mount_id}")
    if not old_mount.path.exists():
        raise FileNotFoundError(f"mounted database not found: {old_mount.path}")

    new_label = _clean_label(label)
    new_path = old_mount.path.with_name(_database_filename_from_label(new_label))
    old_label = row.get("label")
    old_path_text = row.get("path")
    moved = False

    if new_path.resolve() != old_mount.path.resolve():
        if new_path.exists():
            raise FileExistsError(f"database already exists: {new_path}")
        _rename_path_with_retry(old_mount.path, new_path)
        moved = True

    row["label"] = new_label
    row["path"] = _manifest_path_text(new_path, manifest.parent)
    try:
        _write_manifest_payload(manifest, payload)
    except Exception:
        row["label"] = old_label
        row["path"] = old_path_text
        if moved:
            _rename_path_with_retry(new_path, old_mount.path)
        raise

    return MountedDatabase.from_manifest_row(row, manifest.parent)


def create_empty_mount_database(
    manifest_path: str | Path,
    *,
    mount_id: str,
    label: str,
    filename: str | None = None,
) -> MountedDatabase:
    manifest = Path(manifest_path).resolve()
    payload = _read_manifest_payload(manifest)
    mount_id = _clean_mount_id(mount_id)
    if any(row.get("id") == mount_id for row in payload.get("mounts", [])):
        raise ValueError(f"mount id already exists: {mount_id}")

    clean_label = _clean_label(label)
    db_filename = filename or _database_filename_from_label(clean_label)
    if Path(db_filename).is_absolute() or Path(db_filename).name != db_filename:
        raise ValueError("filename must be a simple file name")
    db_path = manifest.parent / db_filename
    if db_path.exists():
        raise FileExistsError(f"database already exists: {db_path}")

    _create_schema_only_database(db_path)
    row = {
        "id": mount_id,
        "label": clean_label,
        "domain": "user",
        "path": db_filename,
        "enabled": True,
        "read_only": False,
    }
    payload.setdefault("mounts", []).append(row)
    _write_manifest_payload(manifest, payload)
    return MountedDatabase.from_manifest_row(row, manifest.parent)


def copy_exam_to_mount(
    manifest_path: str | Path,
    *,
    source_mount_id: str,
    target_mount_id: str,
    exam_code: str,
    backup: bool = True,
) -> ExamCopyResult:
    mounts = {mount.id: mount for mount in load_manifest(manifest_path)}
    if source_mount_id not in mounts:
        raise ValueError(f"source mount not found: {source_mount_id}")
    if target_mount_id not in mounts:
        raise ValueError(f"target mount not found: {target_mount_id}")
    source = mounts[source_mount_id]
    target = mounts[target_mount_id]
    if target.read_only:
        raise ValueError(f"target mount is read-only: {target_mount_id}")
    return apply_exam_copy(source.path, target.path, exam_code, backup=backup)


def export_mount_database(
    manifest_path: str | Path,
    *,
    mount_id: str,
    output_path: str | Path,
) -> Path:
    """Export one mounted SQLite DB into a single standalone .db file."""
    manifest = Path(manifest_path).resolve()
    payload = _read_manifest_payload(manifest)
    source_mount = MountedDatabase.from_manifest_row(
        _find_manifest_row(payload, mount_id),
        manifest.parent,
    )
    source_path = source_mount.path.resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"mounted database not found: {source_path}")

    return export_sqlite_database(source_path, output_path)


def export_sqlite_database(source_path: str | Path, output_path: str | Path) -> Path:
    """Copy a SQLite database through the backup API into one standalone file."""
    source_path = Path(source_path).expanduser().resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"source database not found: {source_path}")

    target_path = Path(output_path).expanduser().resolve()
    if source_path == target_path:
        raise ValueError("export path must be different from the source database")
    if target_path.exists() and target_path.is_dir():
        raise IsADirectoryError(f"export path is a directory: {target_path}")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    _remove_sqlite_sidecars(target_path)
    if target_path.exists():
        target_path.unlink()

    try:
        with sqlite3.connect(str(source_path)) as source_conn:
            with sqlite3.connect(str(target_path)) as target_conn:
                source_conn.backup(target_conn)
                target_conn.commit()
                integrity = target_conn.execute("PRAGMA integrity_check").fetchone()[0]
                if integrity != "ok":
                    raise sqlite3.IntegrityError(f"integrity_check failed: {integrity}")
    except Exception:
        if target_path.exists():
            target_path.unlink()
        _remove_sqlite_sidecars(target_path)
        raise

    _remove_sqlite_sidecars(target_path)
    return target_path


def _create_schema_only_database(db_path: Path) -> None:
    schema_path = Path(__file__).resolve().parents[2] / "src" / "database" / "schema.sql"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema_path.read_text(encoding="utf-8"))
        conn.commit()
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise sqlite3.IntegrityError(f"integrity_check failed: {integrity}")
    db_path.chmod(0o666)


def _read_manifest_payload(manifest_path: Path) -> Dict:
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _write_manifest_payload(manifest_path: Path, payload: Dict) -> None:
    manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _find_manifest_row(payload: Dict, mount_id: str) -> Dict:
    for row in payload.get("mounts", []):
        if row.get("id") == mount_id:
            return row
    raise ValueError(f"mount id not found: {mount_id}")


def _manifest_path_text(db_path: Path, manifest_dir: Path) -> str:
    try:
        return db_path.resolve().relative_to(manifest_dir.resolve()).as_posix()
    except ValueError:
        return str(db_path.resolve())


def _rename_path_with_retry(source: Path, target: Path, attempts: int = 8) -> None:
    last_error = None
    for attempt in range(attempts):
        gc.collect()
        try:
            source.rename(target)
            return
        except PermissionError as exc:
            last_error = exc
            if attempt == attempts - 1:
                break
            time.sleep(0.15)
    if last_error:
        raise last_error


def _remove_sqlite_sidecars(db_path: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = db_path.with_name(f"{db_path.name}{suffix}")
        if sidecar.exists():
            sidecar.unlink()


def _database_filename_from_label(label: str) -> str:
    safe = re.sub(r"\s+", "_", _clean_label(label))
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", safe)
    safe = re.sub(r"_+", "_", safe).strip(" ._")
    if not safe:
        safe = "database"
    if safe.upper() in WINDOWS_RESERVED_FILENAMES:
        safe = f"{safe}_db"
    safe = safe[:80].strip(" ._") or "database"
    return f"exam_bank.{safe}.db"


def _clean_mount_id(value: str) -> str:
    mount_id = re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", str(value or "").strip()).strip("_")
    if not mount_id:
        raise ValueError("mount id is required")
    if "::" in mount_id:
        raise ValueError("mount id cannot contain namespace separator")
    return mount_id


def _clean_label(value: str) -> str:
    label = str(value or "").strip()
    if not label:
        raise ValueError("label is required")
    return label
