from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from zipfile import ZipFile

from experiments.db_mount_prototype.db_management import (
    copy_exam_to_mount,
    create_empty_mount_database,
    export_database_package,
    export_mount_database,
    import_database_to_mount,
    rename_mount_database,
    rename_mount_label,
)
from experiments.db_mount_prototype.mount_repo import MountedDatabase, load_manifest, write_manifest
from src.database.repository import ExamRepository
from src.parser.question import Choice, Question

PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe"
    b"\x02\xfeA\xe2U\xcd\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _create_source_db(path):
    repo = ExamRepository(str(path))
    repo.init_database()
    metadata = SimpleNamespace(year=2024, session=1, exam_type="복사시험")
    repo.save_questions([
        Question(
            number=1,
            text="복사할 문제",
            choices=[
                Choice(number=1, symbol="㉮", text="가"),
                Choice(number=2, symbol="㉯", text="나"),
                Choice(number=3, symbol="㉴", text="사"),
                Choice(number=4, symbol="㉵", text="아"),
            ],
            correct_answer=1,
            subject_name="복사과목",
            year=2024,
            session=1,
            exam_type="복사시험",
        )
    ], metadata)


def _write_manifest(tmp_path):
    domain_dir = tmp_path / "data" / "domain_dbs"
    domain_dir.mkdir(parents=True)
    source_db = domain_dir / "source.db"
    _create_source_db(source_db)
    manifest = domain_dir / "mount_manifest.json"
    write_manifest(
        manifest,
        [
            MountedDatabase(
                id="source",
                label="Original Source",
                domain="source",
                path=source_db,
                enabled=True,
                read_only=False,
            )
        ],
    )
    return manifest, source_db


def test_rename_mount_label_updates_manifest_without_touching_db(tmp_path):
    manifest, source_db = _write_manifest(tmp_path)

    rename_mount_label(manifest, "source", "내가 정한 이름")

    mounts = load_manifest(manifest)
    assert mounts[0].label == "내가 정한 이름"
    assert source_db.exists()


def test_rename_mount_database_updates_label_and_db_filename(tmp_path):
    manifest, source_db = _write_manifest(tmp_path)

    renamed = rename_mount_database(manifest, "source", "내가 정한 DB")

    assert renamed.label == "내가 정한 DB"
    assert renamed.path.name == "exam_bank.내가_정한_DB.db"
    assert renamed.path.exists()
    assert not source_db.exists()
    mounts = load_manifest(manifest)
    assert mounts[0].label == "내가 정한 DB"
    assert mounts[0].path == renamed.path
    with sqlite3.connect(renamed.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM exams WHERE code = '복사시험'").fetchone()[0] == 1


def test_rename_mount_database_blocks_existing_target_filename(tmp_path):
    manifest, source_db = _write_manifest(tmp_path)
    target_db = source_db.with_name("exam_bank.중복_DB.db")
    target_db.write_bytes(b"already here")

    try:
        rename_mount_database(manifest, "source", "중복 DB")
    except FileExistsError:
        pass
    else:
        raise AssertionError("expected FileExistsError")

    mounts = load_manifest(manifest)
    assert mounts[0].label == "Original Source"
    assert mounts[0].path == source_db
    assert source_db.exists()


def test_create_empty_mount_database_registers_writable_schema_only_db(tmp_path):
    manifest, _source_db = _write_manifest(tmp_path)

    created = create_empty_mount_database(
        manifest,
        mount_id="my_custom",
        label="내 전용 DB",
    )

    assert created.path.exists()
    assert created.enabled is True
    assert created.read_only is False
    mounts = {mount.id: mount for mount in load_manifest(manifest)}
    assert mounts["my_custom"].label == "내 전용 DB"
    with sqlite3.connect(created.path) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("SELECT COUNT(*) FROM exams").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == 0


def test_copy_exam_to_mount_builds_user_db_without_deleting_source(tmp_path):
    manifest, source_db = _write_manifest(tmp_path)
    target = create_empty_mount_database(manifest, mount_id="user_db", label="사용자 전용")

    result = copy_exam_to_mount(
        manifest,
        source_mount_id="source",
        target_mount_id="user_db",
        exam_code="복사시험",
        backup=False,
    )

    assert result.copied is True
    with sqlite3.connect(source_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM exams WHERE code = '복사시험'").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == 1
    with sqlite3.connect(target.path) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("SELECT COUNT(*) FROM exams WHERE code = '복사시험'").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM question_choices").fetchone()[0] == 4


def test_export_mount_database_writes_single_integrity_checked_db_file(tmp_path):
    manifest, source_db = _write_manifest(tmp_path)
    output_path = tmp_path / "exports" / "source-export.db"

    exported = export_mount_database(
        manifest,
        mount_id="source",
        output_path=output_path,
    )

    assert exported == output_path.resolve()
    assert exported.exists()
    assert not exported.with_name(f"{exported.name}-wal").exists()
    assert not exported.with_name(f"{exported.name}-shm").exists()
    assert source_db.exists()
    with sqlite3.connect(exported) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("SELECT COUNT(*) FROM exams WHERE code = '복사시험'").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM question_choices").fetchone()[0] == 4


def test_export_database_package_includes_images_and_rewrites_package_refs(tmp_path):
    manifest, source_db = _write_manifest(tmp_path)
    question_image = tmp_path / "question.png"
    choice_image = tmp_path / "choice.png"
    question_image.write_bytes(PNG_1X1)
    choice_image.write_bytes(PNG_1X1 + b"choice")
    with sqlite3.connect(source_db) as conn:
        question_id = conn.execute("SELECT id FROM questions LIMIT 1").fetchone()[0]
        conn.execute("UPDATE questions SET image_path = ?, has_image = 1 WHERE id = ?", (str(question_image), question_id))
        conn.execute(
            "UPDATE question_choices SET choice_image_path = ? WHERE question_id = ? AND choice_number = 1",
            (str(choice_image), question_id),
        )

    package_path = tmp_path / "exports" / "source.examdb.zip"
    result = export_database_package(source_db, package_path, repo_root=tmp_path)

    assert result.path == package_path.resolve()
    assert result.copied_images == 2
    assert result.updated_image_refs == 2
    with ZipFile(package_path) as archive:
        names = set(archive.namelist())
        assert "exam_bank.db" in names
        assert "manifest.json" in names
        assert len([name for name in names if name.startswith("images/")]) == 2
        archive.extract("exam_bank.db", tmp_path / "package")

    with sqlite3.connect(tmp_path / "package" / "exam_bank.db") as conn:
        exported_question_path = conn.execute("SELECT image_path FROM questions LIMIT 1").fetchone()[0]
        exported_choice_path = conn.execute(
            "SELECT choice_image_path FROM question_choices WHERE choice_number = 1 LIMIT 1"
        ).fetchone()[0]
    assert exported_question_path.startswith("images/")
    assert exported_choice_path.startswith("images/")


def test_import_database_to_mount_accepts_package_and_rewrites_image_refs(tmp_path):
    _manifest, source_db = _write_manifest(tmp_path)
    image_path = tmp_path / "question.png"
    image_path.write_bytes(PNG_1X1)
    with sqlite3.connect(source_db) as conn:
        conn.execute("UPDATE questions SET image_path = ?, has_image = 1", (str(image_path),))

    package_path = tmp_path / "source.examdb.zip"
    export_database_package(source_db, package_path, repo_root=tmp_path)

    app_base = tmp_path / "app"
    manifest = app_base / "data" / "domain_dbs" / "mount_manifest.json"
    result = import_database_to_mount(
        manifest,
        package_path,
        mount_id="imported",
        label="Imported DB",
        base_dir=app_base,
    )

    assert result.package is True
    assert result.copied_images == 1
    assert result.updated_image_refs == 1
    assert result.mount.id == "imported"
    assert result.imported_db_path.exists()
    with sqlite3.connect(result.imported_db_path) as conn:
        imported_image_path = conn.execute("SELECT image_path FROM questions LIMIT 1").fetchone()[0]
        assert imported_image_path.startswith("data/domain_dbs/imported_images/")
    assert (app_base / imported_image_path).exists()


def test_import_database_to_mount_accepts_standalone_db(tmp_path):
    _manifest, source_db = _write_manifest(tmp_path)
    app_base = tmp_path / "app"
    manifest = app_base / "data" / "domain_dbs" / "mount_manifest.json"

    result = import_database_to_mount(
        manifest,
        source_db,
        mount_id="standalone",
        label="Standalone DB",
        base_dir=app_base,
    )

    assert result.package is False
    with sqlite3.connect(result.imported_db_path) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == 1
