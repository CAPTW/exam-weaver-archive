from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from experiments.db_mount_prototype.mount_repo import MountedDatabase, load_manifest, write_manifest
from src.database.repository import ExamRepository
from src.gui.interface.db_mount import DbMountInterface
from src.parser.question import Choice, Question


APP = QApplication.instance() or QApplication([])


def _create_db(path, exam_type, subject_name, question_text):
    repo = ExamRepository(str(path))
    repo.init_database()
    metadata = SimpleNamespace(year=2024, session=1, exam_type=exam_type)
    repo.save_questions([
        Question(
            number=1,
            text=question_text,
            choices=[
                Choice(number=1, symbol="㉮", text="가"),
                Choice(number=2, symbol="㉯", text="나"),
                Choice(number=3, symbol="㉴", text="사"),
                Choice(number=4, symbol="㉵", text="아"),
            ],
            correct_answer=1,
            subject_name=subject_name,
            year=2024,
            session=1,
            exam_type=exam_type,
        )
    ], metadata)


def _make_mount_interface(tmp_path):
    base = tmp_path
    domain_dir = base / "data" / "domain_dbs"
    domain_dir.mkdir(parents=True)
    first_db = domain_dir / "first.db"
    second_db = domain_dir / "second.db"
    third_db = domain_dir / "third.db"
    _create_db(first_db, "첫시험", "첫과목", "첫 문제")
    _create_db(second_db, "둘시험", "둘과목", "둘 문제")
    _create_db(third_db, "셋시험", "셋과목", "셋 문제")
    write_manifest(
        domain_dir / "mount_manifest.json",
        [
            MountedDatabase(id="first", label="First DB", domain="first", path=first_db, enabled=True, read_only=False),
            MountedDatabase(id="second", label="Second DB", domain="second", path=second_db, enabled=True, read_only=False),
            MountedDatabase(id="third", label="Third DB", domain="third", path=third_db, enabled=False, read_only=False),
        ],
    )
    widget = DbMountInterface(base)
    return widget, domain_dir / "mount_manifest.json"


def test_db_mount_interface_populates_active_source_target_and_exam_dropdowns(tmp_path):
    widget, _manifest = _make_mount_interface(tmp_path)

    assert widget.mountList.count() == 3
    assert widget.sourceDbCombo.count() == 2
    assert widget.targetDbCombo.count() == 2
    assert widget._current_source_mount().id == "first"
    assert widget._current_target_mount().id == "second"
    assert widget.examCombo.count() == 1
    assert widget._current_exam_code() == "첫시험"

    widget.sourceDbCombo.setCurrentIndex(1)
    APP.processEvents()

    assert widget._current_source_mount().id == "second"
    assert widget.examCombo.count() == 1
    assert widget._current_exam_code() == "둘시험"
    widget.deleteLater()
    APP.processEvents()


def test_db_mount_interface_can_enable_disable_mounts_and_save_manifest(tmp_path):
    widget, manifest = _make_mount_interface(tmp_path)

    first_item = widget.mountList.item(0)
    third_item = widget.mountList.item(2)
    first_item.setCheckState(Qt.Unchecked)
    third_item.setCheckState(Qt.Checked)
    APP.processEvents()

    assert [mount.id for mount in widget.active_mounts] == ["second", "third"]
    assert widget.sourceDbCombo.count() == 2
    assert widget._current_source_mount().id == "second"

    widget.save_mount_selection()
    saved = {mount.id: mount.enabled for mount in load_manifest(manifest)}

    assert saved == {"first": False, "second": True, "third": True}
    widget.deleteLater()
    APP.processEvents()


def test_db_mount_interface_renames_creates_and_copies_to_user_db(tmp_path):
    widget, manifest = _make_mount_interface(tmp_path)

    old_first_path = widget._mount_by_id("first").path
    widget._rename_mount("first", "내 첫 DB")
    assert load_manifest(manifest)[0].label == "내 첫 DB"
    renamed_first = widget._mount_by_id("first")
    assert renamed_first.path.name == "exam_bank.내_첫_DB.db"
    assert renamed_first.path.exists()
    assert not old_first_path.exists()

    created = widget._create_user_database("user_custom", "내 전용 DB")
    assert created.id == "user_custom"
    assert created.path.name == "exam_bank.내_전용_DB.db"
    assert created.path.exists()
    assert "user_custom" in [mount.id for mount in widget.mounts]

    widget.sourceDbCombo.setCurrentIndex(
        [mount.id for mount in widget.active_mounts].index("first")
    )
    widget.targetDbCombo.setCurrentIndex(
        [mount.id for mount in widget.active_mounts].index("user_custom")
    )
    APP.processEvents()
    result = widget._copy_current_exam_to_target(backup=False)

    assert result.copied is True
    target_repo = ExamRepository(str(created.path))
    copied = target_repo.get_questions_with_choices(exam_code="첫시험", limit=None)
    assert [row["question_text"] for row in copied] == ["첫 문제"]
    source_repo = ExamRepository(str(widget._mount_by_id("first").path))
    assert source_repo.get_questions_with_choices(exam_code="첫시험", limit=None)
    widget.deleteLater()
    APP.processEvents()


def test_db_mount_interface_exports_selected_source_db_to_single_file(tmp_path):
    widget, _manifest = _make_mount_interface(tmp_path)
    output_path = tmp_path / "exports" / "selected-source.db"

    exported = widget._export_current_source_db(output_path)

    assert exported == output_path.resolve()
    assert exported.exists()
    exported_repo = ExamRepository(str(exported))
    copied = exported_repo.get_questions_with_choices(exam_code="첫시험", limit=None)
    assert [row["question_text"] for row in copied] == ["첫 문제"]
    widget.deleteLater()
    APP.processEvents()


def test_db_mount_interface_exports_app_db_when_manifest_is_missing(tmp_path):
    app_db = tmp_path / "data" / "exam_bank.db"
    app_db.parent.mkdir(parents=True)
    _create_db(app_db, "앱시험", "앱과목", "앱 DB 문제")

    widget = DbMountInterface(tmp_path, db_path=app_db)
    output_path = tmp_path / "exports" / "app-export.db"

    assert widget.sourceDbCombo.count() == 1
    assert widget._current_source_mount().id == "app"
    exported = widget._export_current_source_db(output_path)

    exported_repo = ExamRepository(str(exported))
    copied = exported_repo.get_questions_with_choices(exam_code="앱시험", limit=None)
    assert [row["question_text"] for row in copied] == ["앱 DB 문제"]
    widget.deleteLater()
    APP.processEvents()


def test_db_mount_interface_exports_package_and_imports_as_mount(tmp_path):
    widget, manifest = _make_mount_interface(tmp_path)
    package_path = tmp_path / "exports" / "first.examdb.zip"

    package_result = widget._export_current_source_package(package_path)
    imported = widget._import_database(package_result.path, "imported_first", "Imported First")

    assert package_result.path.exists()
    assert imported.mount.id == "imported_first"
    assert imported.mount.path.exists()
    saved = {mount.id for mount in load_manifest(manifest)}
    assert "imported_first" in saved
    imported_repo = ExamRepository(str(imported.mount.path))
    copied = imported_repo.get_questions_with_choices(exam_code="첫시험", limit=None)
    assert [row["question_text"] for row in copied] == ["첫 문제"]
    widget.deleteLater()
    APP.processEvents()
