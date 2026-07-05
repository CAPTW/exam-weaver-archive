"""Create the external data folder for a portable build."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path
from typing import Iterable, Optional


FACTORY_DB_NAME = "seed_exam_bank.db"
USER_DB_NAME = "exam_bank.db"
PORTABLE_IMAGE_DIR = "portable_images"
IMAGE_REFS = (
    ("questions", "image_path"),
    ("question_choices", "choice_image_path"),
)


def _portable_ref(path: Path) -> str:
    return f"data/{PORTABLE_IMAGE_DIR}/{path.name}"


def _resolve_image_path(value: str, repo_root: Path, source_db: Path) -> Optional[Path]:
    raw = Path(value)
    candidates = [raw] if raw.is_absolute() else [
        repo_root / raw,
        source_db.parent / raw,
        Path.cwd() / raw,
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


def _hashed_image_name(source_path: Path) -> str:
    digest = hashlib.sha256(source_path.read_bytes()).hexdigest()[:20]
    suffix = source_path.suffix.lower() or ".img"
    return f"{digest}{suffix}"


def _iter_image_rows(conn: sqlite3.Connection) -> Iterable[tuple[str, str, int, str]]:
    cursor = conn.cursor()
    for table, column in IMAGE_REFS:
        cursor.execute(
            f"""
            SELECT id, {column}
            FROM {table}
            WHERE COALESCE({column}, '') <> ''
            """
        )
        for row_id, value in cursor.fetchall():
            yield table, column, row_id, value


def _count(conn: sqlite3.Connection, sql: str) -> int:
    return int(conn.execute(sql).fetchone()[0])


def prepare_portable_data(
    source_db: str | Path,
    target_data_dir: str | Path,
    repo_root: str | Path,
    allow_missing_images: bool = False,
) -> dict:
    source_db = Path(source_db).resolve()
    target_data_dir = Path(target_data_dir).resolve()
    repo_root = Path(repo_root).resolve()

    if not source_db.exists():
        raise FileNotFoundError(f"Source DB not found: {source_db}")

    target_data_dir.mkdir(parents=True, exist_ok=True)
    image_dir = target_data_dir / PORTABLE_IMAGE_DIR
    image_dir.mkdir(parents=True, exist_ok=True)
    (target_data_dir / "clipboard_images").mkdir(parents=True, exist_ok=True)
    (target_data_dir / "exports").mkdir(parents=True, exist_ok=True)

    factory_db = target_data_dir / FACTORY_DB_NAME
    user_db = target_data_dir / USER_DB_NAME
    shutil.copy2(source_db, factory_db)

    copied_images: dict[str, str] = {}
    missing_images: list[dict[str, object]] = []
    updated_refs = 0

    with sqlite3.connect(factory_db) as conn:
        cursor = conn.cursor()
        for table, column, row_id, original_value in _iter_image_rows(conn):
            resolved = _resolve_image_path(original_value, repo_root, source_db)
            if resolved is None:
                missing_images.append({
                    "table": table,
                    "column": column,
                    "id": row_id,
                    "path": original_value,
                })
                continue

            if str(resolved) not in copied_images:
                target_image = image_dir / _hashed_image_name(resolved)
                if not target_image.exists():
                    shutil.copy2(resolved, target_image)
                copied_images[str(resolved)] = _portable_ref(target_image)

            cursor.execute(
                f"UPDATE {table} SET {column} = ? WHERE id = ?",
                (copied_images[str(resolved)], row_id),
            )
            updated_refs += 1

        if missing_images and not allow_missing_images:
            raise RuntimeError(
                f"Missing {len(missing_images)} image file(s). "
                "Portable data was not finalized."
            )

        manifest = {
            "source_db": str(source_db),
            "factory_db": str(factory_db),
            "user_db": str(user_db),
            "questions": _count(conn, "SELECT COUNT(*) FROM questions"),
            "choices": _count(conn, "SELECT COUNT(*) FROM question_choices"),
            "question_image_refs": _count(
                conn,
                "SELECT COUNT(*) FROM questions WHERE COALESCE(image_path, '') <> ''",
            ),
            "choice_image_refs": _count(
                conn,
                "SELECT COUNT(*) FROM question_choices WHERE COALESCE(choice_image_path, '') <> ''",
            ),
            "updated_image_refs": updated_refs,
            "copied_images": len(set(copied_images.values())),
            "missing_images": missing_images,
        }
        conn.commit()

    shutil.copy2(factory_db, user_db)
    manifest["factory_db_size"] = factory_db.stat().st_size
    manifest["user_db_size"] = user_db.stat().st_size

    manifest_path = target_data_dir / "PORTABLE_DATA_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["manifest_path"] = str(manifest_path)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare portable ExamGenerator data.")
    parser.add_argument("--source-db", required=True)
    parser.add_argument("--target-data-dir", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--allow-missing-images", action="store_true")
    args = parser.parse_args()

    manifest = prepare_portable_data(
        source_db=args.source_db,
        target_data_dir=args.target_data_dir,
        repo_root=args.repo_root,
        allow_missing_images=args.allow_missing_images,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
