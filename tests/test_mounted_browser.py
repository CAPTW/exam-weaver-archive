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
from src.gui.interface import browser as browser_module
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


def _mounted_fixture_with_user_workspace(tmp_path):
    source_db = tmp_path / "source.db"
    workspace_db = tmp_path / "workspace.db"
    _make_db(source_db, "기출시험", "기출과목", "기출 문제")
    ExamRepository(str(workspace_db)).init_database()
    manifest = tmp_path / "mounts.json"
    write_manifest(
        manifest,
        [
            MountedDatabase(
                id="source",
                label="Source DB",
                domain="source",
                path=source_db,
                read_only=False,
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
    return MountedExamRepository(manifest), workspace_db


class _AutoAcceptManualEditor:
    def __init__(
        self,
        _parent,
        question_data,
        subject_options=None,
        create_mode=False,
        choice_marker_style=None,
    ):
        self.question_data = dict(question_data)
        self.subject_options = list(subject_options or [])
        self.create_mode = create_mode

    def exec(self):
        return True

    def get_data(self):
        data = dict(self.question_data)
        data['question_text'] = (
            'Mounted 서술형 추가'
            if data.get('question_type') == 'descriptive'
            else 'Mounted 객관식 추가'
        )
        if data.get('question_type') == 'descriptive':
            data['model_answer'] = 'Mounted 모범답안'
        else:
            data['correct_answer'] = 1
            data['choices'] = [
                {'choice_number': 1, 'choice_symbol': '㉮', 'choice_text': '정답'},
                {'choice_number': 2, 'choice_symbol': '㉯', 'choice_text': '오답 1'},
                {'choice_number': 3, 'choice_symbol': '㉴', 'choice_text': '오답 2'},
                {'choice_number': 4, 'choice_symbol': '㉵', 'choice_text': '오답 3'},
            ]
        return data


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


def test_browser_manual_add_uses_mounted_user_workspace(tmp_path, monkeypatch):
    repository, workspace_db = _mounted_fixture_with_user_workspace(tmp_path)
    monkeypatch.setattr(browser_module, 'QuestionEditor', _AutoAcceptManualEditor)
    monkeypatch.setattr(browser_module.InfoBar, 'success', lambda **_kwargs: None)
    widget = BrowserInterface(repository=repository)

    widget.add_manual_question()

    stored = ExamRepository(str(workspace_db)).get_questions_with_choices(
        exam_code='personal_questions',
        limit=None,
    )
    assert [question['question_text'] for question in stored] == ['Mounted 객관식 추가']
    assert widget.examFilter.currentData() == 'user_workspace::personal_questions'
    widget.deleteLater()
    APP.processEvents()


def test_browser_descriptive_add_uses_mounted_user_workspace(tmp_path, monkeypatch):
    repository, workspace_db = _mounted_fixture_with_user_workspace(tmp_path)
    monkeypatch.setattr(browser_module, 'QuestionEditor', _AutoAcceptManualEditor)
    monkeypatch.setattr(browser_module.InfoBar, 'success', lambda **_kwargs: None)
    widget = BrowserInterface(repository=repository)

    widget.add_descriptive_question()

    stored = ExamRepository(str(workspace_db)).get_questions_with_choices(
        exam_code='personal_questions',
        limit=None,
    )
    assert [question['question_text'] for question in stored] == ['Mounted 서술형 추가']
    assert stored[0]['model_answer'] == 'Mounted 모범답안'
    assert widget.examFilter.currentData() == 'user_workspace::personal_questions'
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
