
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QTextEdit
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from qfluentwidgets import (
    SubtitleLabel, PrimaryPushButton, CardWidget, BodyLabel,
    InfoBar, InfoBarPosition, IndeterminateProgressBar
)
from ...parser.main import ExamPDFParser
from ...database.repository import ExamRepository

class ParsingWorker(QThread):
    # Avoid shadowing QThread.finished (no-arg) which can cause crashes on emit.
    result = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, question_path, answer_path):
        super().__init__()
        self.question_path = question_path
        self.answer_path = answer_path

    def run(self):
        try:
            parser = ExamPDFParser()
            result = parser.parse(self.question_path, self.answer_path)
            self.result.emit(result)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error.emit(str(e))

class ImportInterface(QWidget):
    def __init__(self, db_path, parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self.parsed_data = None
        self.setObjectName("ImportInterface")
        
        self.vBoxLayout = QVBoxLayout(self)
        self.init_ui()

    def init_ui(self):
        self.vBoxLayout.setContentsMargins(30, 30, 30, 30)
        self.vBoxLayout.setSpacing(20)

        # Header
        self.titleLabel = SubtitleLabel("문제 가져오기", self)
        self.vBoxLayout.addWidget(self.titleLabel)
        self.stepLabel = BodyLabel(
            "1. 파일 선택  →  2. 분석 및 검수  →  3. 문제은행에 저장",
            self,
        )
        self.vBoxLayout.addWidget(self.stepLabel)

        # File Selection Area
        self.fileLayout = QHBoxLayout()
        
        # Question PDF Selection
        self.qCard = CardWidget(self)
        qLayout = QVBoxLayout(self.qCard)
        self.qLabel = BodyLabel("문제지 PDF 선택", self)
        self.qBtn = PrimaryPushButton("파일 선택", self)
        self.qBtn.clicked.connect(self.select_question_pdf)
        self.qPathLabel = BodyLabel("선택된 파일 없음", self)
        self.qPathLabel.setTextColor(Qt.darkGray, Qt.white)
        qLayout.addWidget(self.qLabel)
        qLayout.addWidget(self.qBtn)
        qLayout.addWidget(self.qPathLabel)
        
        # Answer PDF Selection
        self.aCard = CardWidget(self)
        aLayout = QVBoxLayout(self.aCard)
        self.aLabel = BodyLabel("정답지 PDF 선택", self)
        self.aBtn = PrimaryPushButton("파일 선택", self)
        self.aBtn.clicked.connect(self.select_answer_pdf)
        self.aPathLabel = BodyLabel("선택된 파일 없음", self)
        self.aPathLabel.setTextColor(Qt.darkGray, Qt.white)
        aLayout.addWidget(self.aLabel)
        aLayout.addWidget(self.aBtn)
        aLayout.addWidget(self.aPathLabel)

        self.fileLayout.addWidget(self.qCard)
        self.fileLayout.addWidget(self.aCard)
        self.vBoxLayout.addLayout(self.fileLayout)

        # Action Area
        self.actionLayout = QHBoxLayout()
        self.parseBtn = PrimaryPushButton("분석 및 검수 시작", self)
        # self.parseBtn.setEnabled(False) 
        self.parseBtn.clicked.connect(self.start_parsing)
        
        self.saveBtn = PrimaryPushButton("문제은행에 저장", self)
        self.saveBtn.setEnabled(False)
        self.saveBtn.clicked.connect(self.save_to_db)
        
        self.actionLayout.addWidget(self.parseBtn)
        self.actionLayout.addWidget(self.saveBtn)
        self.actionLayout.addStretch(1)
        self.vBoxLayout.addLayout(self.actionLayout)
        self.qualitySummaryLabel = BodyLabel("분석 전", self)
        self.vBoxLayout.addWidget(self.qualitySummaryLabel)

        # Progress Bar
        self.progressBar = IndeterminateProgressBar(self, start=False)
        self.progressBar.hide()
        self.vBoxLayout.addWidget(self.progressBar)

        # Log Area
        self.logView = QTextEdit(self)
        self.logView.setReadOnly(True)
        self.logView.setPlaceholderText("진행 상황 및 결과가 여기에 표시됩니다.")
        self.vBoxLayout.addWidget(self.logView)

    def select_question_pdf(self):
        fname, _ = QFileDialog.getOpenFileName(self, '문제지 PDF 선택', '', 'PDF/ZIP 파일 (*.pdf *.zip)')
        if fname:
            self.qPathLabel.setText(fname)
            self.log(f"문제지 선택됨: {fname}")

    def select_answer_pdf(self):
        fname, _ = QFileDialog.getOpenFileName(self, '정답지 PDF 선택', '', 'PDF/ZIP 파일 (*.pdf *.zip)')
        if fname:
            self.aPathLabel.setText(fname)
            self.log(f"정답지 선택됨: {fname}")

    def start_parsing(self):
        q_path = self.qPathLabel.text()
        a_path = self.aPathLabel.text()
        
        if "선택된 파일 없음" in [q_path, a_path]:
            InfoBar.error(
                title='입력 오류',
                content="문제지와 정답지 파일을 모두 선택해 주세요.",
                parent=self
            )
            return

        self.parseBtn.setEnabled(False)
        self.progressBar.show()
        self.progressBar.start()
        self.log("파싱 시작...", color='blue')
        
        self.worker = ParsingWorker(q_path, a_path)
        self.worker.result.connect(self.on_parsing_finished)
        self.worker.error.connect(self.on_parsing_error)
        self.worker.start()

    def on_parsing_finished(self, result):
        self.parseBtn.setEnabled(True)
        self.progressBar.stop()
        self.progressBar.hide()
        self.parsed_data = result
        
        metadata = result['metadata']
        stats = result['stats']
        validation_errors = list(result['validation'].errors)
        total_questions = int(stats.get('total_questions') or 0)
        quality_summary = result.get('quality_summary') or {}
        review_count = int(
            quality_summary.get('review_required', len(validation_errors)) or 0
        )
        review_count = min(max(review_count, 0), total_questions)
        corrected_count = int(quality_summary.get('auto_corrected', 0) or 0)
        normal_count = max(total_questions - review_count, 0)
        summary_parts = [
            f"전체 {total_questions}문항",
            f"정상 {normal_count}문항",
        ]
        if corrected_count:
            summary_parts.append(f"자동 교정 {corrected_count}문항")
        summary_parts.append(f"검토 필요 {review_count}문항")
        self.qualitySummaryLabel.setText(" · ".join(summary_parts))
        
        msg = f"""
===== 파싱 완료 =====
시험: {metadata.year}년 제{metadata.session}회 {metadata.exam_type}
총 문제 수: {stats['total_questions']}
이미지 포함: {stats['with_images']}
정답 포함: {stats['with_answers']}
==================
"""
        self.log(msg, color='green')
        self.saveBtn.setEnabled(True)
        
        if validation_errors:
            for err in validation_errors:
                self.log(f"검토 필요: {err}", color='red')

    def on_parsing_error(self, error_msg):
        self.parseBtn.setEnabled(True)
        self.progressBar.stop()
        self.progressBar.hide()
        self.log(f"파싱 실패: {error_msg}", color='red')
        InfoBar.error(
            title='파싱 실패',
            content=error_msg,
            parent=self
        )

    def save_to_db(self):
        if not self.parsed_data:
            return
            
        repo = ExamRepository(self.db_path)
        try:
            count = repo.save_questions(
                self.parsed_data['questions'],
                self.parsed_data['metadata']
            )
            self.log(f"문제은행 저장 완료: {count}개 문제 저장됨", color='green')
            InfoBar.success(
                title='저장 완료',
                content=f"{count}개 문제를 문제은행에 저장했습니다.",
                parent=self
            )
            self.saveBtn.setEnabled(False)
        except Exception as e:
            self.log(f"문제은행 저장 실패: {str(e)}", color='red')
            InfoBar.error(
                title='처리 실패',
                content=f"문제은행에 저장하지 못했습니다. {e}",
                parent=self
            )

    def log(self, message, color=None):
        if color:
            self.logView.append(f'<span style="color:{color}">{message}</span>')
        else:
            self.logView.append(message)
