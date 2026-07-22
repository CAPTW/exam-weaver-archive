import os
import sqlite3

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from src.database.validator import QuestionValidator
from src.gui.interface.browser import BrowserInterface
from src.parser.question import Choice, Question


APP = QApplication.instance() or QApplication([])


def _question(number, subject_name, text="필터 테스트 문제", correct_answer=1):
    return Question(
        number=number,
        text=text,
        choices=[
            Choice(number=1, symbol='㉮', text='가'),
            Choice(number=2, symbol='㉯', text='나'),
            Choice(number=3, symbol='㉴', text='사'),
            Choice(number=4, symbol='㉵', text='아'),
        ],
        correct_answer=correct_answer,
        subject_name=subject_name,
        year=2024,
        session=1,
        exam_type='3급기관사',
    )


def test_browser_filters_questions_by_exam_and_subject(repo, sample_metadata):
    repo.save_questions([
        _question(1, '기관1', '기관1 전용 문제'),
        _question(2, '기관2', '기관2 전용 문제'),
    ], sample_metadata)
    widget = BrowserInterface(repo.db_path)

    assert widget.examFilterLabel.text() == '시험 종류'
    assert widget.subjectFilterLabel.text() == '과목'
    assert widget.searchBox.placeholderText() == '해시태그 또는 문제 내용 검색'
    assert widget.vBoxLayout.indexOf(widget.searchRowWidget) >= 0
    assert widget.btnAddDescriptive.text() == '서술형 문제 추가'
    assert widget.btnDeleteSelected.text() == '선택 문제 삭제'
    assert '문제은행' in widget.repositoryStatusLabel.text()
    assert widget.repositoryStatusLabel.wordWrap() is True
    assert widget.repositoryStatusLabel.maximumWidth() > 1000
    assert widget.minimumSizeHint().width() <= 1050

    exam_index = widget.examFilter.findData('3급기관사')
    assert exam_index >= 0
    widget.examFilter.setCurrentIndex(exam_index)

    subject_index = widget.subjectFilter.findData('engine2')
    assert subject_index >= 0
    widget.subjectFilter.setCurrentIndex(subject_index)
    APP.processEvents()

    assert widget.table.rowCount() == 1
    assert '기관2' in widget.table.item(0, 2).text()
    assert '기관2 전용 문제' in widget.table.item(0, 3).text()

    widget.deleteLater()
    APP.processEvents()


def test_exam_filter_keeps_full_exam_names_accessible(repo):
    widget = BrowserInterface(repo.db_path)
    long_label = "Maritime 전체 문제은행 · 네트워크관리사 2급 필기시험 (exam_bank_network_manager_level_2)"
    widget.examFilter.addItem(long_label, "long_exam")
    widget._update_combo_text_visibility(widget.examFilter)

    expected_popup_width = min(
        widget.examFilter.fontMetrics().horizontalAdvance(long_label) + 48,
        720,
    )

    assert widget.examFilter.minimumWidth() >= 300
    assert widget.examFilter.maximumWidth() >= 400
    assert widget.examFilter.view().minimumWidth() >= expected_popup_width
    assert widget.examFilter.itemData(
        widget.examFilter.count() - 1,
        Qt.ItemDataRole.ToolTipRole,
    ) == long_label

    widget.deleteLater()
    APP.processEvents()


def test_exam_filter_label_is_not_clipped_when_filter_is_wide(repo):
    widget = BrowserInterface(repo.db_path)
    widget.resize(1040, 800)
    widget.show()
    APP.processEvents()

    label_text_width = widget.examFilterLabel.fontMetrics().horizontalAdvance(
        widget.examFilterLabel.text()
    )

    assert widget.examFilterLabel.width() >= label_text_width

    widget.close()
    widget.deleteLater()
    APP.processEvents()


def test_exam_and_subject_filters_are_stacked_with_equal_widths(repo):
    widget = BrowserInterface(repo.db_path)
    widget.resize(1035, 800)
    widget.show()
    APP.processEvents()

    exam_geometry = widget.examFilter.geometry()
    subject_geometry = widget.subjectFilter.geometry()

    assert subject_geometry.y() > exam_geometry.y()
    assert subject_geometry.x() == exam_geometry.x()
    assert subject_geometry.width() == exam_geometry.width()
    assert widget.subjectFilter.minimumWidth() == widget.examFilter.minimumWidth()
    assert widget.subjectFilter.maximumWidth() == widget.examFilter.maximumWidth()

    widget.close()
    widget.deleteLater()
    APP.processEvents()


def test_browser_can_delegate_explanation_panel_to_shared_main_sidecar(repo):
    widget = BrowserInterface(
        repo.db_path,
        external_explanation_host=True,
    )
    requests = []
    widget.explanation_panel_requested.connect(requests.append)

    assert widget.rootLayout.indexOf(widget.explanationDock) == -1
    panel = widget.take_explanation_panel()
    assert panel is widget.explanationSidecar

    widget.set_explanation_sidecar_expanded(True)
    APP.processEvents()
    assert requests == [True]
    assert widget.explanation_sidecar_expanded is True

    panel.deleteLater()
    widget.deleteLater()
    APP.processEvents()


def test_validator_scan_accepts_subject_filter(repo, sample_metadata):
    repo.save_questions([
        _question(1, '기관1', '정상 문제'),
        _question(2, '기관2', '정답 번호가 잘못된 문제'),
    ], sample_metadata)
    with sqlite3.connect(repo.db_path) as conn:
        conn.execute("UPDATE questions SET correct_answer = 5 WHERE question_number = 2")

    findings = QuestionValidator(repo).scan(
        exam_code='3급기관사',
        subject_code='engine2',
    )

    assert len(findings) == 1
    assert findings[0]['question']['subject_name'] == '기관2'
