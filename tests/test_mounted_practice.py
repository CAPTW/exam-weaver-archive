from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication
import pytest

from experiments.db_mount_prototype.mount_repo import (
    MountedDatabase,
    MountedExamRepository,
    write_manifest,
)
from src.database.repository import ExamRepository
from src.gui.interface import practice as practice_module
from src.gui.interface.practice import PracticeInterface
from src.parser.question import Choice, Question


APP = QApplication.instance() or QApplication([])


def _make_db(path, exam_type, subject_name, question_text):
    repo = ExamRepository(str(path))
    repo.init_database()
    metadata = SimpleNamespace(year=2024, session=1, exam_type=exam_type)
    repo.save_questions(
        [
            Question(
                number=1,
                text=question_text,
                choices=[
                    Choice(number=1, symbol="㉮", text="가"),
                    Choice(number=2, symbol="㉯", text="나"),
                    Choice(number=3, symbol="㉴", text="사"),
                    Choice(number=4, symbol="㉵", text="아"),
                ],
                correct_answer=2,
                subject_name=subject_name,
                year=2024,
                session=1,
                exam_type=exam_type,
            )
        ],
        metadata,
    )
    return repo


def _mounted_practice_fixture(tmp_path, *, prefix="first"):
    root = tmp_path / prefix
    root.mkdir()
    source_db = root / "source.db"
    workspace_db = root / "user_workspace.db"
    _make_db(source_db, "3급기관사", "기관1", f"{prefix} 문제")
    ExamRepository(str(workspace_db)).init_database()
    manifest = root / "mounts.json"
    write_manifest(
        manifest,
        [
            MountedDatabase(
                id="maritime_all",
                label="Maritime",
                domain="maritime",
                path=source_db,
                read_only=True,
            ),
            MountedDatabase(
                id="user_workspace",
                label="사용자 작업 DB",
                domain="user",
                path=workspace_db,
                read_only=False,
            ),
        ],
    )
    return MountedExamRepository(manifest), source_db, workspace_db


def _select_subject(widget, subject_code, count=1):
    for row in widget.subjectSelectionRows:
        if row["code"] == subject_code:
            row["checkbox"].setChecked(True)
            row["count_spin"].setValue(count)
            return
    raise AssertionError(f"subject not found: {subject_code}")


class _FailingCompleteRepository:
    def __init__(self, delegate):
        self.delegate = delegate

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    def complete_practice_attempt(self, *_args, **_kwargs):
        raise RuntimeError("workspace write failed")


def test_practice_interface_lists_namespaced_mounted_exams(tmp_path):
    repository, _source_db, _workspace_db = _mounted_practice_fixture(tmp_path)

    widget = PracticeInterface(repository=repository)

    labels = [widget.examFilter.itemText(index) for index in range(widget.examFilter.count())]
    values = [widget.examFilter.itemData(index) for index in range(widget.examFilter.count())]
    assert "Maritime · 3급 기관사 (3급기관사)" in labels
    assert "maritime_all::3급기관사" in values

    widget.deleteLater()
    APP.processEvents()


def test_practice_interface_defers_repository_swap_during_active_quiz(tmp_path):
    first, _first_source, _first_workspace = _mounted_practice_fixture(
        tmp_path,
        prefix="first",
    )
    second, _second_source, _second_workspace = _mounted_practice_fixture(
        tmp_path,
        prefix="second",
    )
    widget = PracticeInterface(repository=first)
    widget.questions = [{"id": "maritime_all::1"}]

    widget.set_repository(second)

    assert widget.repo is first
    assert widget.pending_repository is second

    widget.reset_to_setup()

    assert widget.repo is second
    assert widget.pending_repository is None

    widget.deleteLater()
    APP.processEvents()


def test_practice_interface_completes_mounted_attempt_in_workspace(tmp_path):
    repository, source_db, workspace_db = _mounted_practice_fixture(tmp_path)
    widget = PracticeInterface(repository=repository)
    _select_subject(widget, "maritime_all::engine1")
    source_before = source_db.read_bytes()

    widget.start_quiz()
    widget.select_answer(2)
    widget.submit_exam()

    assert widget.stack.currentWidget() == widget.resultPage
    assert source_db.read_bytes() == source_before
    with sqlite3.connect(workspace_db) as connection:
        assert connection.execute(
            "SELECT source_exam_code, source_exam_name, status "
            "FROM practice_attempts"
        ).fetchone() == ("maritime_all::3급기관사", "3급 기관사", "completed")
        assert connection.execute(
            "SELECT source_subject_id FROM practice_attempt_subject_results"
        ).fetchone()[0] == "maritime_all::engine1"

    widget.deleteLater()
    APP.processEvents()


def test_practice_interface_keeps_quiz_state_when_result_save_fails(tmp_path, monkeypatch):
    repository, _source_db, _workspace_db = _mounted_practice_fixture(tmp_path)
    widget = PracticeInterface(repository=_FailingCompleteRepository(repository))
    _select_subject(widget, "maritime_all::engine1")
    widget.start_quiz()
    widget.select_answer(2)
    answers_before = dict(widget.answers)
    errors = []
    monkeypatch.setattr(
        practice_module.InfoBar,
        "error",
        lambda **kwargs: errors.append(kwargs),
    )

    widget.submit_exam()

    assert widget.stack.currentWidget() == widget.quizPage
    assert widget.results_revealed is False
    assert widget.answers == answers_before
    assert "workspace write failed" in errors[0]["content"]

    widget.deleteLater()
    APP.processEvents()


def test_actual_manifest_exams_are_visible_in_practice_dropdown():
    manifest = Path(__file__).resolve().parents[1] / "data" / "domain_dbs" / "mount_manifest.json"
    if not manifest.is_file():
        pytest.skip("source checkout has no mounted DB manifest")
    repository = MountedExamRepository(manifest)
    try:
        expected_codes = {
            exam["code"]
            for exam in repository.get_filter_options().get("exams", [])
        }
    except (FileNotFoundError, OSError):
        pytest.skip("mounted DB files are not available in this checkout")

    widget = PracticeInterface(repository=repository)
    actual_codes = {
        widget.examFilter.itemData(index)
        for index in range(widget.examFilter.count())
    }

    assert expected_codes
    assert actual_codes == expected_codes
    assert any(code.startswith("Maritime::") for code in actual_codes)

    widget.deleteLater()
    APP.processEvents()
