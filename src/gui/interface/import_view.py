
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
        self.parseBtn = PrimaryPushButton("PDF 파싱 시작", self)
        # self.parseBtn.setEnabled(False) 
        self.parseBtn.clicked.connect(self.start_parsing)
        
        self.saveBtn = PrimaryPushButton("DB 저장", self)
        self.saveBtn.setEnabled(False)
        self.saveBtn.clicked.connect(self.save_to_db)
        
        self.actionLayout.addWidget(self.parseBtn)
        self.actionLayout.addWidget(self.saveBtn)
        self.actionLayout.addStretch(1)
        self.vBoxLayout.addLayout(self.actionLayout)

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
        fname, _ = QFileDialog.getOpenFileName(self, '문제지 PDF 선택', '', 'PDF/ZIP Files (*.pdf *.zip)')
        if fname:
            self.qPathLabel.setText(fname)
            self.log(f"문제지 선택됨: {fname}")

    def select_answer_pdf(self):
        fname, _ = QFileDialog.getOpenFileName(self, '정답지 PDF 선택', '', 'PDF/ZIP Files (*.pdf *.zip)')
        if fname:
            self.aPathLabel.setText(fname)
            self.log(f"정답지 선택됨: {fname}")

    def start_parsing(self):
        q_path = self.qPathLabel.text()
        a_path = self.aPathLabel.text()
        
        if "선택된 파일 없음" in [q_path, a_path]:
            InfoBar.error(
                title='오류',
                content="문제지와 정답지 파일을 모두 선택해주세요.",
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
        
        if result['validation'].errors:
            for err in result['validation'].errors:
                self.log(f"Error: {err}", color='red')

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
            self.log(f"DB 저장 완료: {count}개 문제 저장됨", color='green')
            InfoBar.success(
                title='성공',
                content=f"{count}개 문제가 데이터베이스에 저장되었습니다.",
                parent=self
            )
            self.saveBtn.setEnabled(False)
        except Exception as e:
            self.log(f"DB 저장 실패: {str(e)}", color='red')
            InfoBar.error(
                title='저장 실패',
                content=str(e),
                parent=self
            )

    def log(self, message, color=None):
        if color:
            self.logView.append(f'<span style="color:{color}">{message}</span>')
        else:
            self.logView.append(message)
