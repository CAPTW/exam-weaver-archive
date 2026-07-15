import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from src.gui.interface.import_view import ImportInterface


APP = QApplication.instance() or QApplication([])


def test_import_interface_shows_three_step_problem_bank_workflow(tmp_path):
    widget = ImportInterface(str(tmp_path / "exam_bank.db"))

    assert widget.stepLabel.text() == (
        "1. 파일 선택  →  2. 분석 및 검수  →  3. 문제은행에 저장"
    )
    assert widget.parseBtn.text() == "분석 및 검수 시작"
    assert widget.saveBtn.text() == "문제은행에 저장"
    assert widget.qualitySummaryLabel.text() == "분석 전"

    widget.deleteLater()
    APP.processEvents()

