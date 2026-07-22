import random
import time
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
    QTextEdit,
)
from qfluentwidgets import (
    BodyLabel,
    ImageLabel,
    InfoBar,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
)

from ...database.repository import ExamRepository
from ...explanation_images import ExplanationImageStore
from ...database.selection import (
    count_group_aware_questions,
    dedupe_group_aware_questions_by_content,
    filter_group_aware_random_eligible_questions,
    selection_content_keys,
    select_group_aware_questions,
)
from ...database.validator import QuestionValidator
from ...choice_markers import (
    DEFAULT_CHOICE_MARKER_STYLE,
    choice_marker,
    normalize_choice_marker_style,
)
from ...parser.question import ALL_CHOICES_CORRECT


GRADING_MODE_EXAM_END = "exam-end"
GRADING_MODE_INSTANT = "instant"
CHOICE_BASE_STYLE = "text-align: left; padding-left: 12px; padding-right: 12px;"
CHOICE_SELECTED_STYLE = (
    CHOICE_BASE_STYLE
    + " border: 1px solid #3b82f6; background-color: #dbeafe;"
)
CHOICE_CORRECT_STYLE = (
    CHOICE_BASE_STYLE
    + " border: 1px solid #2e7d32; background-color: #dff6e7; font-weight: 600;"
)
CHOICE_WRONG_STYLE = (
    CHOICE_BASE_STYLE
    + " border: 1px solid #c62828; background-color: #fde7e9; font-weight: 600;"
)


def evaluate_answers(questions, answers):
    total = len(questions)
    correct_count = 0
    subject_stats = {}
    details = []

    for index, question in enumerate(questions, 1):
        question_id = question["id"]
        selected = answers.get(question_id)
        correct_answer = int(question.get("correct_answer") or 0)
        is_correct = selected is not None and (
            correct_answer == ALL_CHOICES_CORRECT or selected == correct_answer
        )
        if is_correct:
            correct_count += 1

        exam_subject_id = (
            question.get("mounted_subject_code")
            or question.get("exam_subject_id")
        )
        subject_stats.setdefault(
            exam_subject_id,
            {
                "subject": question.get("subject_name") or "",
                "total": 0,
                "correct": 0,
            },
        )
        subject_stats[exam_subject_id]["total"] += 1
        if is_correct:
            subject_stats[exam_subject_id]["correct"] += 1

        details.append(
            {
                "index": index,
                "question": question,
                "selected": selected,
                "correct_answer": correct_answer,
                "is_correct": is_correct,
            }
        )

    score = round((correct_count / total) * 100, 1) if total else 0.0
    return {
        "total": total,
        "correct": correct_count,
        "score": score,
        "subject_stats": subject_stats,
        "details": details,
    }


def save_practice_result(repo, mock_exam_id, questions, answers, duration_seconds):
    result = evaluate_answers(questions, answers)
    repo.complete_practice_attempt(
        mock_exam_id,
        result=result,
        duration_seconds=duration_seconds,
    )
    return result


class PracticeInterface(QWidget):
    def __init__(
        self,
        db_path=None,
        parent=None,
        repository=None,
        choice_marker_style=DEFAULT_CHOICE_MARKER_STYLE,
    ):
        super().__init__(parent)
        if repository is None and db_path is None:
            raise ValueError("db_path or repository is required")
        self.repo = repository or ExamRepository(db_path)
        self.explanation_image_store = (
            getattr(self.repo, "explanation_image_store", None)
            or ExplanationImageStore()
        )
        self.choice_marker_style = normalize_choice_marker_style(choice_marker_style)
        self.pending_repository = None
        self.validator = QuestionValidator(self.repo)
        self.questions = []
        self.answers = {}
        self.choice_orders = {}
        self.revealed_question_ids = set()
        self.expanded_explanation_question_ids = set()
        self.current_index = 0
        self.started_at = None
        self.mock_exam_id = None
        self.grading_mode = GRADING_MODE_EXAM_END
        self.results_revealed = False
        self.subjectSelectionRows = []
        self.setObjectName("PracticeInterface")

        self.rootLayout = QVBoxLayout(self)
        self.rootLayout.setContentsMargins(30, 30, 30, 30)
        self.rootLayout.setSpacing(12)
        self.init_ui()
        self.load_options()

    def set_repository(self, repository):
        if self.questions:
            self.pending_repository = repository
            return
        self._apply_repository(repository)

    def set_choice_marker_style(self, style):
        self.choice_marker_style = normalize_choice_marker_style(style)
        if self.questions:
            self.render_question()

    def _apply_repository(self, repository):
        self.repo = repository
        self.explanation_image_store = (
            getattr(repository, "explanation_image_store", None)
            or ExplanationImageStore()
        )
        self.pending_repository = None
        self.validator = QuestionValidator(repository)
        self.load_options()

    def init_ui(self):
        self.titleLabel = SubtitleLabel("문제 풀이", self)
        self.rootLayout.addWidget(self.titleLabel)

        self.stack = QStackedWidget(self)
        self.setupPage = self._build_setup_page()
        self.quizPage = self._build_quiz_page()
        self.resultPage = self._build_result_page()
        self.stack.addWidget(self.setupPage)
        self.stack.addWidget(self.quizPage)
        self.stack.addWidget(self.resultPage)
        self.rootLayout.addWidget(self.stack, 1)

    def _build_setup_page(self):
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        desc = BodyLabel(
            "조건을 선택하고 모의고사를 시작하면 한 문제씩 풀고 자동 채점합니다.",
            self,
        )
        layout.addWidget(desc)
        self.repositoryStatusLabel = BodyLabel("현재 문제은행: 확인 중", self)
        layout.addWidget(self.repositoryStatusLabel)

        self.examFilter = QComboBox(self)
        self.examFilter.currentIndexChanged.connect(self.on_exam_changed)
        self._apply_combo_item_height(self.examFilter)
        self.examLabel = BodyLabel("시험 종류", self)
        layout.addWidget(self.examLabel)
        layout.addWidget(self.examFilter)

        yearLayout = QHBoxLayout()
        self.yearFromFilter = QComboBox(self)
        self.yearToFilter = QComboBox(self)
        self._apply_combo_item_height(self.yearFromFilter)
        self._apply_combo_item_height(self.yearToFilter)
        yearLayout.addWidget(self.yearFromFilter)
        yearLayout.addWidget(self.yearToFilter)
        self.yearRangeLabel = BodyLabel("출제 연도 범위", self)
        layout.addWidget(self.yearRangeLabel)
        layout.addLayout(yearLayout)

        self.tagFilter = QComboBox(self)
        self.tagFilter.setEditable(True)
        self.tagFilter.setPlaceholderText("#계산, #SOLAS")
        self._apply_combo_item_height(self.tagFilter)
        self.tagFilterLabel = BodyLabel("해시태그 필터", self)
        layout.addWidget(self.tagFilterLabel)
        layout.addWidget(self.tagFilter)

        bulkWidget = QWidget(self)
        bulkLayout = QHBoxLayout(bulkWidget)
        bulkLayout.setContentsMargins(0, 0, 0, 0)
        bulkLayout.setSpacing(8)
        self.allSubjectCountSpin = QSpinBox(self)
        self.allSubjectCountSpin.setRange(1, 200)
        self.allSubjectCountSpin.setValue(25)
        self._apply_input_height(self.allSubjectCountSpin)
        self.btnApplyAllSubjects = PushButton("전 과목 적용", self)
        self._apply_input_height(self.btnApplyAllSubjects)
        self.btnApplyAllSubjects.clicked.connect(self._apply_all_subject_count)
        self.shuffleChoices = QCheckBox("선지 섞기", self)
        bulkLayout.addWidget(BodyLabel("과목당 문제 수", self))
        bulkLayout.addWidget(self.allSubjectCountSpin)
        bulkLayout.addWidget(self.btnApplyAllSubjects)
        bulkLayout.addWidget(self.shuffleChoices)
        bulkLayout.addStretch(1)
        layout.addWidget(BodyLabel("과목별 출제", self))
        layout.addWidget(bulkWidget)

        modeLayout = QHBoxLayout()
        self.gradingModeCombo = QComboBox(self)
        self.gradingModeCombo.addItem("모의고사 종료 후 채점", GRADING_MODE_EXAM_END)
        self.gradingModeCombo.addItem("한 문제마다 바로 정답 표시", GRADING_MODE_INSTANT)
        self._apply_combo_item_height(self.gradingModeCombo)
        modeLayout.addWidget(self.gradingModeCombo)
        modeLayout.addStretch(1)
        layout.addWidget(BodyLabel("채점 표시", self))
        layout.addLayout(modeLayout)

        self.subjectSelectionTable = QTableWidget(0, 3, self)
        self.subjectSelectionTable.setHorizontalHeaderLabels(["사용", "과목", "문항 수"])
        self.subjectSelectionTable.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.subjectSelectionTable.setColumnWidth(0, 70)
        self.subjectSelectionTable.setColumnWidth(2, 120)
        self.subjectSelectionTable.setMinimumHeight(210)
        self.subjectSelectionTable.verticalHeader().hide()
        self.subjectSelectionTable.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.subjectSelectionTable.setSelectionMode(QAbstractItemView.NoSelection)
        layout.addWidget(self.subjectSelectionTable)

        layout.addStretch(1)
        buttonRow = QHBoxLayout()
        self.startButton = PrimaryPushButton("시험 시작", self)
        self.startButton.clicked.connect(self.start_quiz)
        buttonRow.addStretch(1)
        buttonRow.addWidget(self.startButton)
        layout.addLayout(buttonRow)
        return page

    def _build_quiz_page(self):
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        topRow = QHBoxLayout()
        self.questionCounterLabel = SubtitleLabel("0/0", self)
        self.answerStateLabel = BodyLabel("미응답 0", self)
        topRow.addWidget(self.questionCounterLabel)
        topRow.addStretch(1)
        topRow.addWidget(self.answerStateLabel)
        layout.addLayout(topRow)

        self.quizScroll = QScrollArea(self)
        self.quizScroll.setWidgetResizable(True)
        self.quizScroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.quizContent = QWidget(self.quizScroll)
        self.quizContentLayout = QVBoxLayout(self.quizContent)
        self.quizContentLayout.setContentsMargins(0, 0, 8, 0)
        self.quizContentLayout.setSpacing(10)

        self.questionInfoLabel = BodyLabel("", self)
        self.questionInfoLabel.setWordWrap(True)
        self.quizContentLayout.addWidget(self.questionInfoLabel)

        self.sharedPassageBox = QTextEdit(self)
        self.sharedPassageBox.setReadOnly(True)
        self.sharedPassageBox.setMinimumHeight(86)
        self.sharedPassageBox.setMaximumHeight(140)
        self.quizContentLayout.addWidget(self.sharedPassageBox)

        self.questionTextBox = QTextEdit(self)
        self.questionTextBox.setReadOnly(True)
        self.questionTextBox.setMinimumHeight(120)
        self.quizContentLayout.addWidget(self.questionTextBox)

        self.questionImage = ImageLabel(self)
        self.questionImage.setScaledContents(True)
        self.questionImage.setBorderRadius(8, 8, 8, 8)
        self.quizContentLayout.addWidget(self.questionImage, 0, Qt.AlignmentFlag.AlignLeft)

        self.choiceGroup = QButtonGroup(self)
        self.choiceGroup.setExclusive(True)
        self.choiceContainer = QWidget(self)
        self.choiceLayout = QVBoxLayout(self.choiceContainer)
        self.choiceLayout.setContentsMargins(0, 0, 0, 0)
        self.choiceLayout.setSpacing(8)
        self.quizContentLayout.addWidget(self.choiceContainer)

        self.feedbackLabel = BodyLabel("", self)
        self.feedbackLabel.setWordWrap(True)
        self.feedbackLabel.setVisible(False)
        self.quizContentLayout.addWidget(self.feedbackLabel)

        self.explanationToggleButton = PushButton("해설 보기", self)
        self.explanationToggleButton.setVisible(False)
        self.explanationToggleButton.setFixedWidth(110)
        self.explanationToggleButton.clicked.connect(self.toggle_current_explanation)
        self.quizContentLayout.addWidget(
            self.explanationToggleButton,
            0,
            Qt.AlignmentFlag.AlignLeft,
        )

        self.explanationBox = QTextEdit(self)
        self.explanationBox.setReadOnly(True)
        self.explanationBox.setMinimumHeight(96)
        self.explanationBox.setMaximumHeight(180)
        self.explanationBox.setVisible(False)
        self.quizContentLayout.addWidget(self.explanationBox)

        self.explanationImage = ImageLabel(self)
        self.explanationImage.setScaledContents(True)
        self.explanationImage.setBorderRadius(8, 8, 8, 8)
        self.explanationImage.setVisible(False)
        self.explanationImage.setFixedSize(0, 0)
        self.quizContentLayout.addWidget(
            self.explanationImage,
            0,
            Qt.AlignmentFlag.AlignLeft,
        )

        self.explanationImageStatusLabel = BodyLabel("", self)
        self.explanationImageStatusLabel.setWordWrap(True)
        self.explanationImageStatusLabel.setVisible(False)
        self.quizContentLayout.addWidget(self.explanationImageStatusLabel)

        self.quizContentLayout.addStretch(1)

        self.quizScroll.setWidget(self.quizContent)
        layout.addWidget(self.quizScroll, 1)

        navRow = QHBoxLayout()
        self.prevButton = PushButton("이전", self)
        self.nextButton = PushButton("다음", self)
        self.submitButton = PrimaryPushButton("제출 및 채점", self)
        self.cancelButton = PushButton("중단", self)
        for button in (self.prevButton, self.nextButton, self.submitButton, self.cancelButton):
            self._apply_input_height(button, 38)
        self.prevButton.clicked.connect(self.previous_question)
        self.nextButton.clicked.connect(self.next_question)
        self.submitButton.clicked.connect(self.submit_exam)
        self.cancelButton.clicked.connect(self.cancel_quiz)
        navRow.addWidget(self.cancelButton)
        navRow.addStretch(1)
        navRow.addWidget(self.prevButton)
        navRow.addWidget(self.nextButton)
        navRow.addWidget(self.submitButton)
        layout.addLayout(navRow)
        return page

    def _build_result_page(self):
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.resultSummaryLabel = SubtitleLabel("결과", self)
        layout.addWidget(self.resultSummaryLabel)
        self.resultDetailLabel = BodyLabel("", self)
        layout.addWidget(self.resultDetailLabel)

        self.resultTable = QTableWidget(0, 6, self)
        self.resultTable.setHorizontalHeaderLabels(["번호", "과목", "선택", "정답", "결과", "문제"])
        self.resultTable.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.resultTable.setColumnWidth(0, 64)
        self.resultTable.setColumnWidth(1, 110)
        self.resultTable.setColumnWidth(2, 80)
        self.resultTable.setColumnWidth(3, 80)
        self.resultTable.setColumnWidth(4, 80)
        self.resultTable.verticalHeader().hide()
        self.resultTable.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.resultTable, 1)

        buttonRow = QHBoxLayout()
        self.reviewFirstWrongButton = PushButton("첫 오답 보기", self)
        self.reviewFirstWrongButton.clicked.connect(self.review_first_wrong)
        self.newExamButton = PrimaryPushButton("새 시험", self)
        self.newExamButton.clicked.connect(self.reset_to_setup)
        buttonRow.addStretch(1)
        buttonRow.addWidget(self.reviewFirstWrongButton)
        buttonRow.addWidget(self.newExamButton)
        layout.addLayout(buttonRow)
        return page

    def _apply_combo_item_height(self, combo, height=44):
        combo.view().setStyleSheet(f"QListView::item {{ height: {height}px; }}")

    def _apply_input_height(self, widget, height=38):
        widget.setMinimumHeight(height)
        if hasattr(widget, "setFixedHeight"):
            widget.setFixedHeight(height)

    def load_options(self):
        options = self.repo.get_filter_options()
        self._update_repository_status(options)

        self.examFilter.blockSignals(True)
        self.examFilter.clear()
        self.examOptionsByCode = {}
        for exam in options.get("exams", []):
            self.examOptionsByCode[exam["code"]] = dict(exam)
            self.examFilter.addItem(self._exam_label(exam), exam["code"])
        if self.examFilter.count() > 0:
            preferred_exam = self._first_exam_code_with_questions()
            preferred_index = self.examFilter.findData(preferred_exam)
            self.examFilter.setCurrentIndex(preferred_index if preferred_index >= 0 else 0)
        self.examFilter.blockSignals(False)

        years = sorted(options.get("years", []))
        self.yearFromFilter.clear()
        self.yearToFilter.clear()
        for year in years:
            self.yearFromFilter.addItem(str(year), year)
            self.yearToFilter.addItem(str(year), year)
        if years:
            self.yearFromFilter.setCurrentIndex(0)
            self.yearToFilter.setCurrentIndex(len(years) - 1)

        self.on_exam_changed()

    def _update_repository_status(self, options):
        labels = []
        for exam in options.get("exams", []):
            label = str(exam.get("mount_label") or "").strip()
            if label and label not in labels:
                labels.append(label)
        if labels:
            self.repositoryStatusLabel.setText(
                f"연결된 문제은행: {', '.join(labels)}"
            )
        else:
            self.repositoryStatusLabel.setText("현재 문제은행: 기본 문제은행")

    @staticmethod
    def _exam_label(exam):
        mount_label = str(exam.get("mount_label") or "").strip()
        exam_name = str(exam.get("name") or exam.get("code") or "")
        exam_code = str(exam.get("local_code") or exam.get("code") or "")
        prefix = f"{mount_label} · " if mount_label else ""
        return f"{prefix}{exam_name} ({exam_code})"

    def _first_exam_code_with_questions(self):
        return self.repo.first_exam_code_with_questions()

    def on_exam_changed(self):
        exam_code = self.examFilter.currentData()
        self.subjectSelectionTable.setRowCount(0)
        self.subjectSelectionRows = []
        for subject in self.repo.get_subject_options(exam_code):
            self._add_subject_selection_row(subject)

    def _add_subject_selection_row(self, subject):
        row = self.subjectSelectionTable.rowCount()
        self.subjectSelectionTable.insertRow(row)

        checkbox = QCheckBox(self.subjectSelectionTable)
        count_spin = QSpinBox(self.subjectSelectionTable)
        count_spin.setRange(0, 200)
        count_spin.setValue(0)
        self._apply_input_height(count_spin, 32)

        self.subjectSelectionTable.setCellWidget(row, 0, checkbox)
        self.subjectSelectionTable.setItem(row, 1, QTableWidgetItem(self._subject_label(subject)))
        self.subjectSelectionTable.setCellWidget(row, 2, count_spin)
        self.subjectSelectionRows.append(
            {
                "code": subject["code"],
                "name": subject.get("name_ko") or subject["code"],
                "checkbox": checkbox,
                "count_spin": count_spin,
            }
        )

    @staticmethod
    def _subject_label(subject):
        name = subject.get("name_ko") or subject.get("code") or ""
        code = subject.get("code") or ""
        if not code or code.startswith(("custom_", "auto_")) or code == name:
            return name
        return f"{name} ({code})"

    def _apply_all_subject_count(self, count=None):
        if count is None or isinstance(count, bool):
            count = int(self.allSubjectCountSpin.value())
        for row in self.subjectSelectionRows:
            row["checkbox"].setChecked(True)
            row["count_spin"].setValue(count)

    def _selected_subject_requests(self):
        requests = []
        invalid = []
        for row in self.subjectSelectionRows:
            if not row["checkbox"].isChecked():
                continue
            count = int(row["count_spin"].value())
            if count <= 0:
                invalid.append(row["name"])
                continue
            requests.append({"code": row["code"], "name": row["name"], "count": count})
        return requests, invalid

    def _current_tag_query(self):
        text = self.tagFilter.currentText().strip()
        return text or None

    def _selected_grading_mode(self):
        return self.gradingModeCombo.currentData() or GRADING_MODE_EXAM_END

    def start_quiz(self):
        try:
            questions = self._select_practice_questions()
            mock_exam_id = self._create_mock_exam_record(questions)
        except Exception as exc:  # noqa: BLE001 - surfaced to UI
            InfoBar.error(title="시험 시작 실패", content=str(exc), parent=self)
            return

        self.questions = questions
        self.answers = {}
        self.choice_orders = self._build_choice_orders(questions)
        self.revealed_question_ids = set()
        self.expanded_explanation_question_ids = set()
        self.current_index = 0
        self.started_at = time.time()
        self.mock_exam_id = mock_exam_id
        self.grading_mode = self._selected_grading_mode()
        self.results_revealed = False
        self.stack.setCurrentWidget(self.quizPage)
        self.render_question()

    def _select_practice_questions(self):
        exam_code = self.examFilter.currentData()
        year_from = self.yearFromFilter.currentData()
        year_to = self.yearToFilter.currentData()
        tag_query = self._current_tag_query()
        subject_requests, invalid_subjects = self._selected_subject_requests()

        if not exam_code:
            raise ValueError("시험을 선택하세요.")
        if year_from is None or year_to is None:
            raise ValueError("연도 범위를 선택하세요.")
        if year_from > year_to:
            raise ValueError("시작 연도는 종료 연도보다 작거나 같아야 합니다.")
        if invalid_subjects:
            raise ValueError(f"문항 수를 1 이상으로 지정하세요: {', '.join(invalid_subjects)}")
        if not subject_requests:
            raise ValueError("풀이할 과목을 하나 이상 선택하세요.")

        selected = []
        selected_keys = set()
        for request in subject_requests:
            subject_questions = self.repo.get_questions_with_choices(
                exam_code=exam_code,
                subject_code=request["code"],
                year_from=year_from,
                year_to=year_to,
                tag_query=tag_query,
                limit=None,
            )
            subject_questions = filter_group_aware_random_eligible_questions(
                subject_questions,
                self.validator,
            )
            subject_questions = dedupe_group_aware_questions_by_content(subject_questions)
            available_count = count_group_aware_questions(
                subject_questions,
                excluded_keys=selected_keys,
            )
            if request["count"] > available_count:
                raise ValueError(
                    f"{request['name']}: 요청 {request['count']}문항, "
                    f"사용 가능 {available_count}문항입니다."
                )
            selected_questions = select_group_aware_questions(
                subject_questions,
                request["count"],
                rng=random,
                excluded_keys=selected_keys,
            )
            selected.extend(selected_questions)
            selected_keys.update(selection_content_keys(selected_questions))

        if not selected:
            raise ValueError("선택 조건에 맞는 문제가 없습니다.")
        return selected

    def _create_mock_exam_record(self, questions):
        exam_code = self.examFilter.currentData()
        exam = self.examOptionsByCode.get(exam_code, {})
        exam_name = exam.get("name") or self._strip_combo_code(self.examFilter.currentText())
        return self.repo.create_practice_attempt(
            exam_code=exam_code,
            exam_name=exam_name,
            questions=questions,
        )

    def _build_choice_orders(self, questions):
        orders = {}
        for question in questions:
            choices = list(question.get("choices") or [])
            if self.shuffleChoices.isChecked():
                random.shuffle(choices)
            orders[question["id"]] = choices
        return orders

    @staticmethod
    def _strip_combo_code(text):
        if not text:
            return ""
        return text.rsplit(" (", 1)[0].strip()

    def render_question(self):
        if not self.questions:
            return
        question = self.questions[self.current_index]
        total = len(self.questions)
        answered = len(self.answers)
        unanswered = total - answered
        self.questionCounterLabel.setText(f"{self.current_index + 1}/{total}")
        self.answerStateLabel.setText(f"응답 {answered} / 미응답 {unanswered}")
        self.questionInfoLabel.setText(self._format_question_info(question))

        shared_passage = question.get("shared_passage") or question.get("group_shared_text")
        self.sharedPassageBox.setVisible(bool(shared_passage))
        if shared_passage:
            self.sharedPassageBox.setPlainText(f"[공통지문]\n{shared_passage}")

        self.questionTextBox.setPlainText(question.get("question_text") or "")
        self._set_image_preview(self.questionImage, question.get("image_path"), 320, 180)
        self._render_choices(question)
        self._render_feedback(question)
        self._render_explanation(question)
        self.prevButton.setEnabled(self.current_index > 0)
        self.nextButton.setEnabled(self.current_index < total - 1)
        self.quizScroll.verticalScrollBar().setValue(0)

    def _format_question_info(self, question):
        return (
            f"{question.get('year')}년 {question.get('session')}회 "
            f"{question.get('subject_name') or ''} {question.get('question_number')}번"
        )

    def _render_choices(self, question):
        self._clear_layout(self.choiceLayout)
        self.choiceGroup = QButtonGroup(self)
        self.choiceGroup.setExclusive(True)
        selected = self.answers.get(question["id"])
        correct_answer = int(question.get("correct_answer") or 0)
        reveal = self._should_show_feedback(question)

        for choice in self.choice_orders.get(question["id"], question.get("choices") or []):
            row = QWidget(self)
            row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            rowLayout = QHBoxLayout(row)
            rowLayout.setContentsMargins(0, 0, 0, 0)
            rowLayout.setSpacing(8)

            button = PushButton(self._format_choice_text(choice), self)
            button.setCheckable(True)
            button.setMinimumHeight(46)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            number = int(choice.get("number") or choice.get("choice_number") or 0)
            button.setChecked(selected == number)
            button.setStyleSheet(
                self._choice_button_style(
                    number,
                    selected,
                    correct_answer,
                    reveal,
                )
            )
            button.clicked.connect(lambda checked=False, n=number: self.select_answer(n))
            self.choiceGroup.addButton(button, number)
            rowLayout.addWidget(button, 1)

            image_path = choice.get("image_path") or choice.get("choice_image_path")
            image = ImageLabel(self)
            image.setScaledContents(True)
            image.setBorderRadius(6, 6, 6, 6)
            self._set_image_preview(image, image_path, 100, 64)
            rowLayout.addWidget(image)

            self.choiceLayout.addWidget(row)

    def _choice_button_style(self, number, selected, correct_answer, reveal):
        if reveal and (
            correct_answer == ALL_CHOICES_CORRECT or number == correct_answer
        ):
            return CHOICE_CORRECT_STYLE
        if (
            reveal
            and selected == number
            and correct_answer != ALL_CHOICES_CORRECT
            and selected != correct_answer
        ):
            return CHOICE_WRONG_STYLE
        if selected == number:
            return CHOICE_SELECTED_STYLE
        return CHOICE_BASE_STYLE

    def _should_show_feedback(self, question):
        return (
            self.results_revealed
            or question["id"] in self.revealed_question_ids
        )

    def _render_feedback(self, question):
        if not self._should_show_feedback(question):
            self.feedbackLabel.setText("")
            self.feedbackLabel.setVisible(False)
            return

        selected = self.answers.get(question["id"])
        correct_answer = int(question.get("correct_answer") or 0)
        correct_label = self._answer_label(question, correct_answer)
        if selected is not None and (
            correct_answer == ALL_CHOICES_CORRECT or selected == correct_answer
        ):
            message = f"정답입니다. 정답: {correct_label}"
            color = "#2e7d32"
        else:
            selected_label = self._answer_label(question, selected)
            message = f"오답입니다. 선택: {selected_label} / 정답: {correct_label}"
            color = "#c62828"
        self.feedbackLabel.setText(message)
        self.feedbackLabel.setStyleSheet(
            f"font-weight: 600; color: {color}; padding: 6px 2px;"
        )
        self.feedbackLabel.setVisible(True)

    def _render_explanation(self, question):
        explanation = str(question.get("explanation") or "").strip()
        attachments = question.get("explanation_images") or []
        attachment = attachments[0] if attachments else None
        if not self._should_show_feedback(question) or not (explanation or attachment):
            self.explanationToggleButton.setVisible(False)
            self.explanationBox.setVisible(False)
            self.explanationBox.clear()
            self._hide_explanation_image()
            self.explanationImageStatusLabel.clear()
            self.explanationImageStatusLabel.setVisible(False)
            return

        expanded = question["id"] in self.expanded_explanation_question_ids
        self.explanationToggleButton.setText("해설 접기" if expanded else "해설 보기")
        self.explanationToggleButton.setVisible(True)
        self.explanationBox.setPlainText(explanation)
        self.explanationBox.setVisible(expanded and bool(explanation))
        self._render_explanation_image(attachment, expanded)

    def _render_explanation_image(self, attachment, expanded):
        self._hide_explanation_image()
        self.explanationImageStatusLabel.clear()
        self.explanationImageStatusLabel.setVisible(False)
        if not expanded or not attachment:
            return

        path = self.explanation_image_store.resolve(attachment.get("image_path"))
        if not path.is_file():
            self.explanationImageStatusLabel.setText("해설 이미지 파일 없음")
            self.explanationImageStatusLabel.setVisible(True)
            return

        image = QImage(str(path))
        if image.isNull():
            self.explanationImageStatusLabel.setText("해설 이미지를 읽을 수 없음")
            self.explanationImageStatusLabel.setVisible(True)
            return

        size = image.size().scaled(
            420,
            260,
            Qt.AspectRatioMode.KeepAspectRatio,
        )
        self.explanationImage.setImage(str(path))
        self.explanationImage.setFixedSize(size)
        self.explanationImage.setVisible(True)

    def _hide_explanation_image(self):
        self.explanationImage.setVisible(False)
        self.explanationImage.setFixedSize(0, 0)

    def _format_choice_text(self, choice):
        number = choice.get("number") or choice.get("choice_number")
        stored_symbol = choice.get("symbol") or choice.get("choice_symbol") or ""
        symbol = choice_marker(
            number,
            self.choice_marker_style,
            fallback=stored_symbol,
        )
        text = choice.get("text") or choice.get("choice_text") or ""
        return f"{symbol} {text}".strip()

    def _set_image_preview(self, image_widget, image_path, width, height):
        if image_path and Path(image_path).exists():
            image_widget.setVisible(True)
            image_widget.setImage(str(image_path))
            image_widget.setFixedSize(width, height)
        else:
            image_widget.setVisible(False)
            image_widget.setFixedSize(0, 0)

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def select_answer(self, answer_number):
        if not self.questions:
            return
        question = self.questions[self.current_index]
        if self._answer_locked(question):
            return
        self.answers[question["id"]] = int(answer_number)
        if self.grading_mode == GRADING_MODE_INSTANT:
            self.revealed_question_ids.add(question["id"])
        self.render_question()

    def toggle_current_explanation(self):
        if not self.questions:
            return
        question_id = self.questions[self.current_index]["id"]
        if question_id in self.expanded_explanation_question_ids:
            self.expanded_explanation_question_ids.remove(question_id)
        else:
            self.expanded_explanation_question_ids.add(question_id)
        self.render_question()

    def _answer_locked(self, question):
        return (
            self.results_revealed
            or (
                self.grading_mode == GRADING_MODE_INSTANT
                and question["id"] in self.revealed_question_ids
            )
        )

    def previous_question(self):
        if self.current_index > 0:
            self.current_index -= 1
            self.render_question()

    def next_question(self):
        if self.current_index < len(self.questions) - 1:
            self.current_index += 1
            self.render_question()

    def cancel_quiz(self):
        answer = QMessageBox.question(
            self,
            "풀이 중단",
            "현재 풀이를 중단하고 설정 화면으로 돌아갈까요?",
        )
        if answer == QMessageBox.Yes:
            self.reset_to_setup()

    def submit_exam(self):
        unanswered = len(self.questions) - len(self.answers)
        if unanswered:
            answer = QMessageBox.question(
                self,
                "미응답 문항 있음",
                f"미응답 {unanswered}문항이 있습니다. 그대로 제출할까요?",
            )
            if answer != QMessageBox.Yes:
                return

        duration = int(time.time() - self.started_at) if self.started_at else 0
        try:
            result = save_practice_result(
                self.repo,
                self.mock_exam_id,
                self.questions,
                self.answers,
                duration,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to UI
            InfoBar.error(title="결과 저장 실패", content=str(exc), parent=self)
            return
        result["duration_seconds"] = duration
        self.results_revealed = True
        self.render_result(result)
        self.stack.setCurrentWidget(self.resultPage)

    def render_result(self, result):
        self.resultSummaryLabel.setText(
            f"{result['correct']} / {result['total']} 정답 ({result['score']}점)"
        )
        self.resultDetailLabel.setText(
            f"소요 시간: {result.get('duration_seconds', 0)}초"
        )
        self.resultTable.setRowCount(0)
        for detail in result["details"]:
            question = detail["question"]
            row = self.resultTable.rowCount()
            self.resultTable.insertRow(row)
            selected_label = self._answer_label(question, detail["selected"])
            correct_label = self._answer_label(question, detail["correct_answer"])
            self.resultTable.setItem(row, 0, QTableWidgetItem(str(detail["index"])))
            self.resultTable.setItem(row, 1, QTableWidgetItem(question.get("subject_name") or ""))
            self.resultTable.setItem(row, 2, QTableWidgetItem(selected_label))
            self.resultTable.setItem(row, 3, QTableWidgetItem(correct_label))
            self.resultTable.setItem(
                row,
                4,
                QTableWidgetItem("정답" if detail["is_correct"] else "오답"),
            )
            self.resultTable.setItem(
                row,
                5,
                QTableWidgetItem((question.get("question_text") or "")[:120]),
            )

    def _answer_label(self, question, answer_number):
        if answer_number is None:
            return "-"
        if int(answer_number) == ALL_CHOICES_CORRECT:
            return "전원 정답"
        for choice in question.get("choices") or []:
            number = int(choice.get("number") or choice.get("choice_number") or 0)
            if number == int(answer_number):
                stored_symbol = choice.get("symbol") or choice.get("choice_symbol") or ""
                return choice_marker(
                    answer_number,
                    self.choice_marker_style,
                    fallback=stored_symbol,
                )
        return choice_marker(
            answer_number,
            self.choice_marker_style,
            fallback=str(answer_number),
        )

    def review_first_wrong(self):
        result = evaluate_answers(self.questions, self.answers)
        wrong = next((d for d in result["details"] if not d["is_correct"]), None)
        if wrong is None:
            InfoBar.success(title="오답 없음", content="모든 문항을 맞혔습니다.", parent=self)
            return
        self.current_index = wrong["index"] - 1
        self.stack.setCurrentWidget(self.quizPage)
        self.render_question()

    def reset_to_setup(self):
        self.questions = []
        self.answers = {}
        self.choice_orders = {}
        self.revealed_question_ids = set()
        self.expanded_explanation_question_ids = set()
        self.current_index = 0
        self.started_at = None
        self.mock_exam_id = None
        self.grading_mode = GRADING_MODE_EXAM_END
        self.results_revealed = False
        self.stack.setCurrentWidget(self.setupPage)
        if self.pending_repository is not None:
            self._apply_repository(self.pending_repository)
