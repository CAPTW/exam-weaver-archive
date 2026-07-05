import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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

    assert widget.examFilterLabel.text() == 'EXAM'
    assert widget.subjectFilterLabel.text() == 'SUBJECT'

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


def test_validator_scan_accepts_subject_filter(repo, sample_metadata):
    repo.save_questions([
        _question(1, '기관1', '정상 문제'),
        _question(2, '기관2', '정답 번호가 잘못된 문제', correct_answer=5),
    ], sample_metadata)

    findings = QuestionValidator(repo).scan(
        exam_code='3급기관사',
        subject_code='engine2',
    )

    assert len(findings) == 1
    assert findings[0]['question']['subject_name'] == '기관2'
