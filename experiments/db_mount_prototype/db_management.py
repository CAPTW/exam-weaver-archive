from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import gc
import re
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Dict, Iterable
from zipfile import ZIP_DEFLATED, ZipFile, is_zipfile

from .exam_move import ExamCopyResult, apply_exam_copy
from .mount_repo import MountedDatabase, load_manifest


DB_PACKAGE_FORMAT = "exam-generator-db-package"
DB_PACKAGE_VERSION = 1
PACKAGE_DB_NAME = "exam_bank.db"
PACKAGE_MANIFEST_NAME = "manifest.json"
PACKAGE_IMAGE_DIR = "images"
IMAGE_REFS = (
    ("questions", "image_path"),
    ("question_choices", "choice_image_path"),
    ("question_groups", "shared_image_path"),
)

WINDOWS_RESERVED_FILENAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


@dataclass(frozen=True)
class DatabasePackageExportResult:
    path: Path
    database_name: str
    updated_image_refs: int
    copied_images: int
    missing_images: list[dict[str, object]]


@dataclass(frozen=True)
class DatabaseImportResult:
    mount: MountedDatabase
    source_path: Path
    imported_db_path: Path
    package: bool
    copied_images: int = 0
    updated_image_refs: int = 0


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

    source_conn = None
    target_conn = None
    try:
        source_conn = sqlite3.connect(str(source_path))
        target_conn = sqlite3.connect(str(target_path))
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
    finally:
        if target_conn is not None:
            target_conn.close()
        if source_conn is not None:
            source_conn.close()

    _remove_sqlite_sidecars(target_path)
    return target_path


def export_database_package(
    source_path: str | Path,
    package_path: str | Path,
    *,
    repo_root: str | Path | None = None,
    allow_missing_images: bool = True,
) -> DatabasePackageExportResult:
    """Export a SQLite DB and its resolvable image files as one zip package."""
    source_path = Path(source_path).expanduser().resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"source database not found: {source_path}")

    package_path = Path(package_path).expanduser().resolve()
    if package_path.exists() and package_path.is_dir():
        raise IsADirectoryError(f"package path is a directory: {package_path}")
    package_path.parent.mkdir(parents=True, exist_ok=True)
    if package_path.exists():
        package_path.unlink()

    repo_root_path = Path(repo_root).resolve() if repo_root else None

    with tempfile.TemporaryDirectory(prefix="examdb_export_") as tmp_name:
        tmp_dir = Path(tmp_name)
        package_db = tmp_dir / PACKAGE_DB_NAME
        image_dir = tmp_dir / PACKAGE_IMAGE_DIR
        image_dir.mkdir(parents=True, exist_ok=True)
        export_sqlite_database(source_path, package_db)

        copied_images: dict[str, str] = {}
        missing_images: list[dict[str, object]] = []
        updated_refs = 0

        conn = sqlite3.connect(package_db)
        try:
            cursor = conn.cursor()
            for table, column, row_id, original_value in _iter_image_rows(conn):
                resolved = _resolve_image_path(original_value, source_path, repo_root_path)
                if resolved is None:
                    missing_images.append({
                        "table": table,
                        "column": column,
                        "id": row_id,
                        "path": original_value,
                    })
                    continue

                resolved_key = str(resolved)
                if resolved_key not in copied_images:
                    target_image = image_dir / _hashed_image_name(resolved)
                    if not target_image.exists():
                        shutil.copy2(resolved, target_image)
                    copied_images[resolved_key] = f"{PACKAGE_IMAGE_DIR}/{target_image.name}"

                cursor.execute(
                    f"UPDATE {table} SET {column} = ? WHERE id = ?",
                    (copied_images[resolved_key], row_id),
                )
                updated_refs += 1

            if missing_images and not allow_missing_images:
                raise RuntimeError(f"Missing {len(missing_images)} image file(s)")
            conn.commit()
        finally:
            conn.close()

        manifest = {
            "format": DB_PACKAGE_FORMAT,
            "version": DB_PACKAGE_VERSION,
            "database": PACKAGE_DB_NAME,
            "images_dir": PACKAGE_IMAGE_DIR,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "source_db": str(source_path),
            "updated_image_refs": updated_refs,
            "copied_images": len(set(copied_images.values())),
            "missing_images": missing_images,
        }
        (tmp_dir / PACKAGE_MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        with ZipFile(package_path, "w", ZIP_DEFLATED) as archive:
            archive.write(package_db, PACKAGE_DB_NAME)
            archive.write(tmp_dir / PACKAGE_MANIFEST_NAME, PACKAGE_MANIFEST_NAME)
            for image_path in sorted(image_dir.rglob("*")):
                if image_path.is_file():
                    archive.write(
                        image_path,
                        image_path.relative_to(tmp_dir).as_posix(),
                    )

    return DatabasePackageExportResult(
        path=package_path,
        database_name=PACKAGE_DB_NAME,
        updated_image_refs=updated_refs,
        copied_images=len(set(copied_images.values())),
        missing_images=missing_images,
    )


def export_mount_database_package(
    manifest_path: str | Path,
    *,
    mount_id: str,
    package_path: str | Path,
    repo_root: str | Path | None = None,
    allow_missing_images: bool = True,
) -> DatabasePackageExportResult:
    manifest = Path(manifest_path).resolve()
    payload = _read_manifest_payload(manifest)
    source_mount = MountedDatabase.from_manifest_row(
        _find_manifest_row(payload, mount_id),
        manifest.parent,
    )
    return export_database_package(
        source_mount.path,
        package_path,
        repo_root=repo_root,
        allow_missing_images=allow_missing_images,
    )


def import_database_to_mount(
    manifest_path: str | Path,
    import_path: str | Path,
    *,
    mount_id: str,
    label: str,
    base_dir: str | Path | None = None,
) -> DatabaseImportResult:
    """Import a standalone .db or packaged .zip into domain_dbs and register it."""
    manifest = Path(manifest_path).resolve()
    manifest.parent.mkdir(parents=True, exist_ok=True)
    payload = _read_manifest_payload_or_default(manifest)

    clean_mount_id = _clean_mount_id(mount_id)
    if any(row.get("id") == clean_mount_id for row in payload.get("mounts", [])):
        raise ValueError(f"mount id already exists: {clean_mount_id}")

    clean_label = _clean_label(label)
    db_path = manifest.parent / _database_filename_from_label(clean_label)
    if db_path.exists():
        raise FileExistsError(f"database already exists: {db_path}")

    import_path = Path(import_path).expanduser().resolve()
    if not import_path.exists():
        raise FileNotFoundError(f"import file not found: {import_path}")

    package = is_zipfile(import_path)
    copied_images = 0
    updated_image_refs = 0
    created_image_dir: Path | None = None

    try:
        if package:
            image_dir = manifest.parent / f"{clean_mount_id}_images"
            if image_dir.exists():
                raise FileExistsError(f"image directory already exists: {image_dir}")
            created_image_dir = image_dir
            package_result = _import_database_package(
                import_path,
                db_path,
                image_dir=image_dir,
                base_dir=Path(base_dir).resolve() if base_dir else None,
            )
            copied_images = package_result["copied_images"]
            updated_image_refs = package_result["updated_image_refs"]
        else:
            export_sqlite_database(import_path, db_path)

        row = {
            "id": clean_mount_id,
            "label": clean_label,
            "domain": "imported",
            "path": _manifest_path_text(db_path, manifest.parent),
            "enabled": True,
            "read_only": False,
        }
        payload.setdefault("mounts", []).append(row)
        _write_manifest_payload(manifest, payload)
    except Exception:
        if db_path.exists():
            db_path.unlink()
        _remove_sqlite_sidecars(db_path)
        if created_image_dir and created_image_dir.exists():
            shutil.rmtree(created_image_dir)
        raise

    mount = MountedDatabase.from_manifest_row(row, manifest.parent)
    return DatabaseImportResult(
        mount=mount,
        source_path=import_path,
        imported_db_path=db_path,
        package=package,
        copied_images=copied_images,
        updated_image_refs=updated_image_refs,
    )


def _create_schema_only_database(db_path: Path) -> None:
    schema_path = Path(__file__).resolve().parents[2] / "src" / "database" / "schema.sql"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(schema_path.read_text(encoding="utf-8"))
        conn.commit()
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise sqlite3.IntegrityError(f"integrity_check failed: {integrity}")
    finally:
        conn.close()
    db_path.chmod(0o666)


def _read_manifest_payload(manifest_path: Path) -> Dict:
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _read_manifest_payload_or_default(manifest_path: Path) -> Dict:
    if not manifest_path.exists():
        return {
            "version": 1,
            "metadata": {"created_by": "db_mount_import"},
            "mounts": [],
        }
    return _read_manifest_payload(manifest_path)


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


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    try:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    except sqlite3.OperationalError:
        return set()
    return {row[1] for row in rows}


def _iter_image_rows(conn: sqlite3.Connection) -> Iterable[tuple[str, str, int, str]]:
    for table, column in IMAGE_REFS:
        if column not in _table_columns(conn, table):
            continue
        cursor = conn.execute(
            f"""
            SELECT id, {column}
            FROM {table}
            WHERE COALESCE({column}, '') <> ''
            """
        )
        for row_id, value in cursor.fetchall():
            yield table, column, row_id, value


def _resolve_image_path(
    value: str,
    source_db: Path,
    repo_root: Path | None = None,
) -> Path | None:
    raw = Path(str(value))
    candidates = [raw] if raw.is_absolute() else []
    if repo_root:
        candidates.append(repo_root / raw)
    candidates.extend([
        source_db.parent / raw,
        Path.cwd() / raw,
    ])
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()
    return None


def _hashed_image_name(source_path: Path) -> str:
    digest = hashlib.sha256(source_path.read_bytes()).hexdigest()[:20]
    suffix = source_path.suffix.lower() or ".img"
    return f"{digest}{suffix}"


def _import_database_package(
    package_path: Path,
    target_db: Path,
    *,
    image_dir: Path,
    base_dir: Path | None,
) -> dict[str, int]:
    with tempfile.TemporaryDirectory(prefix="examdb_import_") as tmp_name:
        tmp_dir = Path(tmp_name)
        _extract_zip_safely(package_path, tmp_dir)

        manifest_path = tmp_dir / PACKAGE_MANIFEST_NAME
        package_manifest = {}
        if manifest_path.exists():
            package_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if package_manifest.get("format") != DB_PACKAGE_FORMAT:
                raise ValueError("unsupported database package format")

        package_db = _safe_package_path(
            tmp_dir,
            str(package_manifest.get("database") or PACKAGE_DB_NAME),
        )
        if not package_db.exists():
            raise FileNotFoundError(f"package database not found: {PACKAGE_DB_NAME}")

        export_sqlite_database(package_db, target_db)

        images_source = _safe_package_path(
            tmp_dir,
            str(package_manifest.get("images_dir") or PACKAGE_IMAGE_DIR),
        )
        copied_images = 0
        if images_source.exists():
            image_dir.mkdir(parents=True, exist_ok=True)
            for source_image in sorted(images_source.rglob("*")):
                if not source_image.is_file():
                    continue
                relative = source_image.relative_to(images_source)
                target_image = image_dir / relative
                target_image.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_image, target_image)
                copied_images += 1

        image_ref_prefix = _image_ref_prefix(image_dir, base_dir)
        updated_refs = 0
        conn = sqlite3.connect(target_db)
        try:
            cursor = conn.cursor()
            for table, column, row_id, original_value in _iter_image_rows(conn):
                normalized = str(original_value).replace("\\", "/")
                if normalized == PACKAGE_IMAGE_DIR or not normalized.startswith(f"{PACKAGE_IMAGE_DIR}/"):
                    continue
                relative_image = normalized[len(PACKAGE_IMAGE_DIR) + 1:]
                new_ref = f"{image_ref_prefix}/{relative_image}"
                cursor.execute(
                    f"UPDATE {table} SET {column} = ? WHERE id = ?",
                    (new_ref, row_id),
                )
                updated_refs += 1
            conn.commit()
        finally:
            conn.close()

    return {
        "copied_images": copied_images,
        "updated_image_refs": updated_refs,
    }


def _extract_zip_safely(package_path: Path, target_dir: Path) -> None:
    with ZipFile(package_path) as archive:
        for info in archive.infolist():
            name = info.filename.replace("\\", "/")
            if not name or name.startswith("/") or ":" in Path(name).parts[0]:
                raise ValueError(f"unsafe package entry: {info.filename}")
            parts = [part for part in name.split("/") if part]
            if any(part == ".." for part in parts):
                raise ValueError(f"unsafe package entry: {info.filename}")
            if not parts or info.is_dir():
                continue
            target_path = target_dir.joinpath(*parts)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target_path.open("wb") as target:
                shutil.copyfileobj(source, target)


def _safe_package_path(root: Path, relative_path: str) -> Path:
    text = relative_path.replace("\\", "/")
    if not text or text.startswith("/"):
        raise ValueError(f"unsafe package path: {relative_path}")
    parts = [part for part in text.split("/") if part]
    if any(part == ".." for part in parts):
        raise ValueError(f"unsafe package path: {relative_path}")
    target = root.joinpath(*parts).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        raise ValueError(f"unsafe package path: {relative_path}")
    return target


def _image_ref_prefix(image_dir: Path, base_dir: Path | None) -> str:
    if base_dir:
        try:
            return image_dir.resolve().relative_to(base_dir.resolve()).as_posix()
        except ValueError:
            pass
    return str(image_dir.resolve())


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
