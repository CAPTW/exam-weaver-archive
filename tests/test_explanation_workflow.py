import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import QApplication

from src.database.repository import ExamRepository
from src.explanation_images import ExplanationImageStore
from src.gui.interface.browser import BrowserInterface
from src.gui.interface.editor import QuestionEditor
from src.gui.interface.practice import GRADING_MODE_INSTANT, PracticeInterface


APP = QApplication.instance() or QApplication([])


def _write_image(path, color=0x336699):
    image = QImage(24, 16, QImage.Format.Format_RGB32)
    image.fill(color)
    assert image.save(str(path), "PNG")
    return path


def _select_subject(widget, subject_code, count):
    for row in widget.subjectSelectionRows:
        if row["code"] == subject_code:
            row["checkbox"].setChecked(True)
            row["count_spin"].setValue(count)
            return
    raise AssertionError(f"subject not found: {subject_code}")


def test_browser_explanation_sidecar_saves_question_explanation(
    repo,
    sample_metadata,
    sample_question,
):
    repo.save_questions([sample_question], sample_metadata)
    question = repo.get_questions_with_choices(limit=1)[0]
    widget = BrowserInterface(repo.db_path)

    widget.open_explanation(question["id"])
    assert widget.explanation_sidecar_expanded is True
    assert widget.current_explanation_question_id == question["id"]

    widget.explanationEditor.setPlainText("상세 해설 본문")
    widget.save_current_explanation()

    assert repo.get_question(question["id"])["explanation"] == "상세 해설 본문"

    widget.deleteLater()
    APP.processEvents()


def test_browser_explanation_sidecar_saves_and_reloads_image(
    repo,
    sample_metadata,
    sample_question,
    tmp_path,
):
    repo.save_questions([sample_question], sample_metadata)
    store = ExplanationImageStore(tmp_path / "app")
    repository = ExamRepository(repo.db_path, explanation_image_store=store)
    question = repository.get_questions_with_choices(limit=1)[0]
    source = _write_image(tmp_path / "explanation.png")
    widget = BrowserInterface(repository=repository)

    widget.open_explanation(question["id"])
    widget.explanationImageEditor.set_candidate(source)
    widget.save_current_explanation()

    loaded = repository.get_question(question["id"])
    assert len(loaded["explanation_images"]) == 1
    assert store.resolve(loaded["explanation_images"][0]["image_path"]).is_file()
    assert widget.explanationImageEditor.image_change().action == "keep"

    widget.clear_current_explanation()
    assert widget.explanationImageEditor.image_change().action == "keep"
    widget.save_current_explanation()
    assert len(repository.get_question(question["id"])["explanation_images"]) == 1

    widget.deleteLater()
    APP.processEvents()


def test_browser_explanation_save_failure_keeps_selected_image_candidate(
    repo,
    sample_metadata,
    sample_question,
    tmp_path,
    monkeypatch,
):
    repo.save_questions([sample_question], sample_metadata)
    store = ExplanationImageStore(tmp_path / "app")
    repository = ExamRepository(repo.db_path, explanation_image_store=store)
    question = repository.get_questions_with_choices(limit=1)[0]
    source = _write_image(tmp_path / "candidate.png")
    widget = BrowserInterface(repository=repository)
    widget.open_explanation(question["id"])
    widget.explanationImageEditor.set_candidate(source)
    monkeypatch.setattr(
        repository,
        "update_question_explanation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("실패")),
    )
    monkeypatch.setattr(widget, "_show_write_error", lambda *_args: None)

    widget.save_current_explanation()

    change = widget.explanationImageEditor.image_change()
    assert change.action == "replace"
    assert change.source_path == str(source.resolve())

    widget.deleteLater()
    APP.processEvents()


def test_browser_repository_switch_discards_temp_candidate_and_rebinds_store(
    repo,
    tmp_path,
):
    first_store = ExplanationImageStore(tmp_path / "first_app")
    second_store = ExplanationImageStore(tmp_path / "second_app")
    first = ExamRepository(repo.db_path, explanation_image_store=first_store)
    second = ExamRepository(repo.db_path, explanation_image_store=second_store)
    widget = BrowserInterface(repository=first)
    candidate = first_store.save_clipboard_candidate(
        QImage(8, 8, QImage.Format.Format_RGB32)
    )
    widget.explanationImageEditor.set_candidate(candidate, temporary=True)

    widget.set_repository(second)

    assert not os.path.exists(candidate)
    assert widget.explanationImageEditor.store is second_store
    assert widget.explanationImageEditor.image_change().action == "keep"

    widget.deleteLater()
    APP.processEvents()


def test_question_editor_returns_keep_or_copy_change_for_existing_image(tmp_path):
    store = ExplanationImageStore(tmp_path / "app")
    source = _write_image(tmp_path / "existing.png")
    stored_path = store.import_file(source)
    question_data = {
        "year": 2024,
        "session": 1,
        "question_number": 1,
        "subject_code": "engine1",
        "exam_code": "3급기관사",
        "question_text": "해설 이미지 편집 문제",
        "correct_answer": 1,
        "explanation_images": [{"image_path": stored_path}],
        "choices": [
            {"choice_number": number, "choice_text": str(number)}
            for number in range(1, 5)
        ],
    }
    editor = QuestionEditor(
        question_data=question_data,
        subject_options=[{"code": "engine1", "name_ko": "기관1"}],
        explanation_image_store=store,
    )
    clone_editor = QuestionEditor(
        question_data=question_data,
        subject_options=[{"code": "engine1", "name_ko": "기관1"}],
        create_mode=True,
        explanation_image_store=store,
    )

    assert editor.explanationImageEditor.image_change().action == "keep"
    clone_change = clone_editor.get_data()["explanation_image_change"]
    assert clone_change.action == "replace"
    assert clone_change.source_path == str(store.resolve(stored_path))

    editor.deleteLater()
    clone_editor.deleteLater()
    APP.processEvents()


def test_question_editor_reject_discards_temporary_explanation_candidate(tmp_path):
    store = ExplanationImageStore(tmp_path / "app")
    editor = QuestionEditor(
        question_data={
            "year": 2024,
            "session": 1,
            "question_number": 1,
            "subject_code": "engine1",
            "exam_code": "3급기관사",
            "question_text": "취소할 문제",
            "correct_answer": 1,
            "choices": [
                {"choice_number": number, "choice_text": str(number)}
                for number in range(1, 5)
            ],
        },
        subject_options=[{"code": "engine1", "name_ko": "기관1"}],
        explanation_image_store=store,
    )
    candidate = store.save_clipboard_candidate(
        QImage(8, 8, QImage.Format.Format_RGB32)
    )
    editor.explanationImageEditor.set_candidate(candidate, temporary=True)

    editor.reject()

    assert not os.path.exists(candidate)

    editor.deleteLater()
    APP.processEvents()


def test_practice_revealed_answer_can_expand_saved_explanation(
    repo,
    sample_metadata,
    sample_question,
):
    repo.save_questions([sample_question], sample_metadata)
    question = repo.get_questions_with_choices(limit=1)[0]
    repo.update_question_explanation(question["id"], "정답은 출력 계산식으로 확인한다.")
    widget = PracticeInterface(repo.db_path)
    _select_subject(widget, "engine1", 1)
    widget.gradingModeCombo.setCurrentIndex(
        widget.gradingModeCombo.findData(GRADING_MODE_INSTANT)
    )

    widget.start_quiz()
    widget.select_answer(2)

    assert widget.explanationToggleButton.isHidden() is False
    assert widget.explanationBox.isHidden() is True

    widget.toggle_current_explanation()

    assert widget.explanationBox.isHidden() is False
    assert "출력 계산식" in widget.explanationBox.toPlainText()

    widget.deleteLater()
    APP.processEvents()
