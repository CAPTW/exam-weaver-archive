from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QCheckBox

from experiments.db_mount_prototype.mount_repo import (
    MountedDatabase,
    MountedExamRepository,
    write_manifest,
)
from src.database.repository import ExamRepository
from src.gui.interface.browser import BrowserInterface
from src.gui.main import build_question_repository
from src.parser.question import Choice, Question


APP = QApplication.instance() or QApplication([])


def _make_db(path, exam_type, subject_name, text):
    repo = ExamRepository(str(path))
    repo.init_database()
    repo.save_questions(
        [
            Question(
                number=1,
                text=text,
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
        ],
        SimpleNamespace(year=2024, session=1, exam_type=exam_type),
    )
    return repo


def _mounted_fixture(tmp_path):
    first_db = tmp_path / "first.db"
    second_db = tmp_path / "second.db"
    _make_db(first_db, "첫시험", "첫과목", "첫 문제")
    _make_db(second_db, "둘시험", "둘과목", "둘 문제")
    manifest = tmp_path / "mounts.json"
    write_manifest(
        manifest,
        [
            MountedDatabase(id="first", label="First DB", path=first_db),
            MountedDatabase(id="second", label="Second DB", path=second_db),
        ],
    )
    return MountedExamRepository(manifest), first_db, second_db


def test_browser_aggregates_mounted_rows_and_preserves_namespaced_ids(tmp_path):
    repository, _first_db, _second_db = _mounted_fixture(tmp_path)

    widget = BrowserInterface(repository=repository)

    assert widget.table.rowCount() == 2
    assert {widget.table.item(row, 3).text() for row in range(2)} == {"첫 문제", "둘 문제"}
    assert {widget.table.item(row, 2).text().split(" · ")[0] for row in range(2)} == {
        "First DB",
        "Second DB",
    }
    assert {widget.examFilter.itemData(index) for index in range(1, widget.examFilter.count())} == {
        "first::첫시험",
        "second::둘시험",
    }

    checkbox = widget.table.cellWidget(0, 0).findChild(QCheckBox)
    checkbox.setChecked(True)
    assert widget.selected_question_ids()[0] in {"first::1", "second::1"}

    widget.deleteLater()
    APP.processEvents()


def test_browser_saves_explanation_to_owning_mount(tmp_path):
    repository, first_db, second_db = _mounted_fixture(tmp_path)
    widget = BrowserInterface(repository=repository)

    widget.open_explanation("second::1")
    widget.explanationEditor.setPlainText("마운트 사용자 해설")
    widget.save_current_explanation()

    assert ExamRepository(str(second_db)).get_question(1)["explanation"] == "마운트 사용자 해설"
    assert ExamRepository(str(first_db)).get_question(1)["explanation"] is None

    widget.deleteLater()
    APP.processEvents()


def test_question_repository_builder_uses_mounts_and_falls_back_safely(tmp_path):
    mounted, first_db, _second_db = _mounted_fixture(tmp_path)
    manifest = mounted.manifest_path

    repository, error = build_question_repository(first_db, manifest)
    assert isinstance(repository, MountedExamRepository)
    assert error is None

    manifest.write_text("{broken", encoding="utf-8")
    repository, error = build_question_repository(first_db, manifest)
    assert isinstance(repository, ExamRepository)
    assert error
    assert repository.search_questions(limit=None)

    manifest.unlink()
    repository, error = build_question_repository(first_db, manifest)
    assert isinstance(repository, ExamRepository)
    assert error is None
