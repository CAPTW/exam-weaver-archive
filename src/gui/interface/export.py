import random

import re
from datetime import date

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QScrollArea, QFrame, QVBoxLayout, QFileDialog, QComboBox, QHBoxLayout, QCheckBox, QSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QButtonGroup, QRadioButton
)
from qfluentwidgets import SubtitleLabel, PrimaryPushButton, InfoBar, BodyLabel, PushButton, LineEdit

from ...database.repository import ExamRepository
from ...database.selection import (
    count_group_aware_questions,
    dedupe_group_aware_questions_by_content,
    filter_group_aware_random_eligible_questions,
    selection_content_keys,
    select_group_aware_questions,
)
from ...database.validator import QuestionValidator
from ...exporter.docx import DocxExporter


class ExportInterface(QScrollArea):
    def __init__(self, db_path=None, parent=None, repository=None):
        super().__init__(parent)
        if repository is None:
            if db_path is None:
                raise ValueError("db_path or repository is required")
            repository = ExamRepository(db_path)
        self.repo = repository
        self.validator = QuestionValidator(self.repo)
        self.exporter = DocxExporter()
        self.setObjectName("ExportInterface")

        self.setFrameShape(QFrame.NoFrame)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.contentWidget = QWidget(self)
        self.vBoxLayout = QVBoxLayout(self.contentWidget)
        self.init_ui()
        self.setWidget(self.contentWidget)
        self.load_options()

    def set_repository(self, repository):
        self.repo = repository
        self.validator = QuestionValidator(repository)
        self.load_options()

    def init_ui(self):
        self.vBoxLayout.setContentsMargins(30, 30, 30, 30)
        self.vBoxLayout.setSpacing(10)

        self.titleLabel = SubtitleLabel("모의고사 출력 (DOCX)", self)
        self.vBoxLayout.addWidget(self.titleLabel)

        self.descLabel = BodyLabel(
            "출제 조건과 과목별 문항 수를 선택해 하나의 DOCX 시험지를 만듭니다.", self
        )
        self.vBoxLayout.addWidget(self.descLabel)
        self.repositoryStatusLabel = BodyLabel("현재 문제은행: 확인 중", self)
        self.vBoxLayout.addWidget(self.repositoryStatusLabel)

        # Exam
        self.examLabel = BodyLabel("시험 종류", self)
        self.examFilter = QComboBox()
        self.examFilter.setPlaceholderText("시험 종류 선택")
        self.examFilter.currentIndexChanged.connect(self.on_exam_changed)
        self.vBoxLayout.addWidget(self.examLabel)
        self.vBoxLayout.addWidget(self.examFilter)

        # Year range
        self.yearRangeLabel = BodyLabel("출제 연도 범위", self)
        self.yearRangeLayout = QHBoxLayout()
        self.yearFromFilter = QComboBox()
        self.yearFromFilter.setPlaceholderText("시작 연도")
        self.yearToFilter = QComboBox()
        self.yearToFilter.setPlaceholderText("종료 연도")
        self.yearRangeLayout.addWidget(self.yearFromFilter)
        self.yearRangeLayout.addWidget(self.yearToFilter)
        self.vBoxLayout.addWidget(self.yearRangeLabel)
        self.vBoxLayout.addLayout(self.yearRangeLayout)

        # Subject
        self.subjectLabel = BodyLabel("과목", self)
        self.subjectFilter = QComboBox()
        self.subjectFilter.setPlaceholderText("전체 과목")
        self.vBoxLayout.addWidget(self.subjectLabel)
        self.vBoxLayout.addWidget(self.subjectFilter)

        # Hashtag
        self.tagLabel = BodyLabel("해시태그", self)
        self.tagFilter = LineEdit(self)
        self.tagFilter.setPlaceholderText("#계산, #SOLAS")
        self._apply_input_height(self.tagFilter)
        self.vBoxLayout.addWidget(self.tagLabel)
        self.vBoxLayout.addWidget(self.tagFilter)

        # Random selection count
        self.randomCountLabel = BodyLabel("무작위 추출 문항 수 (0 = 전체)", self)
        self.randomCountSpin = QSpinBox(self)
        self.randomCountSpin.setRange(0, 1000)
        self.randomCountSpin.setValue(0)
        self.vBoxLayout.addWidget(self.randomCountLabel)
        self.vBoxLayout.addWidget(self.randomCountSpin)

        self.compositionModeLabel = BodyLabel("구성 방식", self)
        self.compositionModeWidget = QWidget(self)
        self.compositionModeLayout = QHBoxLayout(self.compositionModeWidget)
        self.compositionModeLayout.setContentsMargins(0, 0, 0, 0)
        self.compositionModeLayout.setSpacing(18)
        self.compositionModeGroup = QButtonGroup(self)
        self.singleExamModeCheck = QRadioButton("한 시험에서 구성", self)
        self.multiExamModeCheck = QRadioButton("여러 시험의 과목을 조합", self)
        self.compositionModeGroup.addButton(self.singleExamModeCheck)
        self.compositionModeGroup.addButton(self.multiExamModeCheck)
        self.singleExamModeCheck.setChecked(True)
        self.compositionModeLayout.addWidget(self.singleExamModeCheck)
        self.compositionModeLayout.addWidget(self.multiExamModeCheck)
        self.compositionModeLayout.addStretch(1)
        self.multiExamModeCheck.toggled.connect(
            self._on_multi_exam_mode_changed
        )
        self.randomSubjectLabel = BodyLabel("과목별 무작위 출제", self)
        self.randomSubjectBulkWidget = QWidget(self)
        self.randomSubjectBulkLayout = QHBoxLayout(self.randomSubjectBulkWidget)
        self.randomSubjectBulkLayout.setContentsMargins(0, 0, 0, 0)
        self.randomSubjectBulkLayout.setSpacing(8)
        self.allSubjectCountLabel = BodyLabel("과목당 문항 수", self)
        self.allSubjectCountSpin = QSpinBox(self)
        self.allSubjectCountSpin.setRange(1, 1000)
        self.allSubjectCountSpin.setValue(25)
        self._apply_input_height(self.allSubjectCountSpin)
        self.btnApplyAllSubjects = PushButton("전체 과목에 적용", self)
        self._apply_input_height(self.btnApplyAllSubjects)
        self.btnApplyAllSubjects.setFixedWidth(170)
        self.btnApplyAllSubjects.clicked.connect(self._apply_all_subject_count)
        self.randomSubjectBulkLayout.addWidget(self.allSubjectCountLabel)
        self.randomSubjectBulkLayout.addWidget(self.allSubjectCountSpin)
        self.randomSubjectBulkLayout.addWidget(self.btnApplyAllSubjects)
        self.randomSubjectBulkLayout.addStretch(1)
        self.subjectSelectionTable = QTableWidget(0, 3, self)
        self.subjectSelectionTable.setHorizontalHeaderLabels(["사용", "과목", "문항 수"])
        self.subjectSelectionTable.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.subjectSelectionTable.setColumnWidth(0, 70)
        self.subjectSelectionTable.setColumnWidth(2, 120)
        self.subjectSelectionTable.setMinimumHeight(176)
        self.subjectSelectionTable.setMaximumHeight(220)
        self.subjectSelectionTable.verticalHeader().hide()
        self.subjectSelectionTable.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.subjectSelectionTable.setSelectionMode(QAbstractItemView.NoSelection)
        self.subjectSelectionRows = []
        self.vBoxLayout.addWidget(self.compositionModeLabel)
        self.vBoxLayout.addWidget(self.compositionModeWidget)
        self.vBoxLayout.addWidget(self.randomSubjectLabel)
        self.vBoxLayout.addWidget(self.randomSubjectBulkWidget)
        self.vBoxLayout.addWidget(self.subjectSelectionTable)
        self.selectionSummaryLabel = BodyLabel("선택 0과목 · 예상 0문항", self)
        self.vBoxLayout.addWidget(self.selectionSummaryLabel)

        # Choice shuffle
        self.shuffleChoices = QCheckBox("4지선다 선지 순서 섞기", self)
        self.vBoxLayout.addWidget(self.shuffleChoices)

        self.vBoxLayout.addStretch(1)

        # Export Button
        self.btnExport = PrimaryPushButton("DOCX로 내보내기", self)
        self.btnExport.clicked.connect(self.export_docx)
        self.vBoxLayout.addWidget(self.btnExport)

        for combo in (self.examFilter, self.yearFromFilter, self.yearToFilter, self.subjectFilter):
            self._apply_combo_item_height(combo)

    def _apply_combo_item_height(self, combo, height=44):
        view = combo.view()
        view.setStyleSheet(f"QListView::item {{ height: {height}px; }}")

    def _apply_input_height(self, widget, height=38):
        widget.setMinimumHeight(height)
        if hasattr(widget, "setFixedHeight"):
            widget.setFixedHeight(height)

    def load_options(self):
        options = self.repo.get_filter_options()
        self._update_repository_status(options)
        self.examOptions = [dict(exam) for exam in options.get('exams', [])]
        self.examOptionsByCode = {
            exam['code']: exam
            for exam in self.examOptions
        }

        # Exams
        self.examFilter.blockSignals(True)
        self.examFilter.clear()
        for exam in self.examOptions:
            self.examFilter.addItem(self._exam_label(exam), exam['code'])
        if self.examFilter.count() > 0:
            self.examFilter.setCurrentIndex(0)
        self.examFilter.blockSignals(False)

        # Years
        years = sorted(options.get('years', []))
        self.yearFromFilter.clear()
        self.yearToFilter.clear()
        for year in years:
            self.yearFromFilter.addItem(str(year), year)
            self.yearToFilter.addItem(str(year), year)
        if years:
            self.yearFromFilter.setCurrentIndex(0)
            self.yearToFilter.setCurrentIndex(len(years) - 1)

        # Subjects (based on selected exam)
        self.on_exam_changed()

    def _update_repository_status(self, options):
        labels = []
        for exam in options.get('exams', []):
            label = str(exam.get('mount_label') or '').strip()
            if label and label not in labels:
                labels.append(label)
        if labels:
            self.repositoryStatusLabel.setText(
                f"연결된 문제은행: {', '.join(labels)}"
            )
        else:
            self.repositoryStatusLabel.setText("현재 문제은행: 기본 문제은행")

    def on_exam_changed(self):
        exam_code = self.examFilter.currentData()
        self.subjectFilter.clear()
        self.subjectFilter.addItem("전체 과목", None)
        subjects = self.repo.get_subject_options(exam_code)
        for subject in subjects:
            self.subjectFilter.addItem(
                self._subject_label(subject),
                subject['code']
            )
        self._rebuild_subject_selection_rows(subjects)

    def _is_multi_exam_mode(self):
        checkbox = self.__dict__.get('multiExamModeCheck')
        return bool(checkbox and checkbox.isChecked())

    def _on_multi_exam_mode_changed(self, checked):
        multi_exam = bool(checked)
        self.examFilter.setEnabled(not multi_exam)
        self.subjectFilter.setEnabled(not multi_exam)
        self.randomCountSpin.setEnabled(not multi_exam)
        disabled_reason = (
            "여러 시험 조합에서는 아래 표에서 시험과 과목을 선택합니다."
            if multi_exam else ""
        )
        for widget in (self.examFilter, self.subjectFilter, self.randomCountSpin):
            widget.setToolTip(disabled_reason)
        self._rebuild_subject_selection_rows()

    def _configure_subject_selection_table(self, multi_exam):
        self.subjectSelectionTable.clear()
        headers = (
            ["사용", "문제은행", "시험 종류", "과목", "문항 수"]
            if multi_exam
            else ["사용", "과목", "문항 수"]
        )
        self.subjectSelectionTable.setColumnCount(len(headers))
        self.subjectSelectionTable.setHorizontalHeaderLabels(headers)
        self.subjectSelectionTable.setColumnWidth(0, 70)
        self.subjectSelectionTable.setColumnWidth(len(headers) - 1, 120)
        stretch_columns = (2, 3) if multi_exam else (1,)
        for column in stretch_columns:
            self.subjectSelectionTable.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.Stretch
            )

    def _rebuild_subject_selection_rows(self, selected_exam_subjects=None):
        if not hasattr(self, 'subjectSelectionTable'):
            return
        multi_exam = self._is_multi_exam_mode()
        self.subjectSelectionTable.setRowCount(0)
        self.subjectSelectionRows = []
        self._configure_subject_selection_table(multi_exam)

        if multi_exam:
            for exam in self.__dict__.get('examOptions', []):
                for subject in self.repo.get_subject_options(exam['code']):
                    self._add_subject_selection_row(subject, exam, True)
            self._update_selection_summary()
            return

        exam_code = self.examFilter.currentData()
        exam = self.__dict__.get('examOptionsByCode', {}).get(exam_code)
        subjects = selected_exam_subjects
        if subjects is None:
            subjects = self.repo.get_subject_options(exam_code)
        for subject in subjects:
            self._add_subject_selection_row(subject, exam, False)
        self._update_selection_summary()

    def _add_subject_selection_row(self, subject, exam=None, multi_exam=False):
        row = self.subjectSelectionTable.rowCount()
        self.subjectSelectionTable.insertRow(row)

        checkbox = QCheckBox(self.subjectSelectionTable)
        count_spin = QSpinBox(self.subjectSelectionTable)
        count_spin.setRange(0, 1000)
        count_spin.setValue(0)

        self.subjectSelectionTable.setCellWidget(row, 0, checkbox)
        if multi_exam:
            self.subjectSelectionTable.setItem(
                row,
                1,
                QTableWidgetItem(
                    (exam or {}).get('mount_label')
                    or subject.get('mount_label')
                    or ''
                ),
            )
            self.subjectSelectionTable.setItem(
                row, 2, QTableWidgetItem(self._plain_exam_label(exam or {}))
            )
            self.subjectSelectionTable.setItem(
                row, 3, QTableWidgetItem(self._plain_subject_label(subject))
            )
            self.subjectSelectionTable.setCellWidget(row, 4, count_spin)
        else:
            self.subjectSelectionTable.setItem(
                row, 1, QTableWidgetItem(self._subject_label(subject))
            )
            self.subjectSelectionTable.setCellWidget(row, 2, count_spin)

        subject_name = subject.get('name_ko') or subject['code']
        self.subjectSelectionRows.append({
            'exam_code': (exam or {}).get('code'),
            'exam_name': (exam or {}).get('name') or '',
            'subject_code': subject['code'],
            'code': subject['code'],
            'subject_name': subject_name,
            'name': subject_name,
            'mount_label': (
                (exam or {}).get('mount_label')
                or subject.get('mount_label')
                or ''
            ),
            'multi_exam': multi_exam,
            'checkbox': checkbox,
            'count_spin': count_spin,
        })
        checkbox.toggled.connect(self._update_selection_summary)
        count_spin.valueChanged.connect(self._update_selection_summary)

    def _update_selection_summary(self, *_args):
        label = self.__dict__.get('selectionSummaryLabel')
        if label is None:
            return
        selected = 0
        total = 0
        for row in self.__dict__.get('subjectSelectionRows', []):
            checkbox = row.get('checkbox')
            count_spin = row.get('count_spin')
            if checkbox and checkbox.isChecked():
                selected += 1
                total += int(count_spin.value()) if count_spin else 0
        label.setText(
            f"선택 {selected}과목 · 예상 {total}문항"
        )

    @staticmethod
    def _plain_exam_label(exam):
        name = exam.get('name') or exam.get('code') or ''
        code = exam.get('local_code') or exam.get('code') or ''
        if not code or code == name:
            return name
        return f"{name} ({code})"

    @staticmethod
    def _exam_label(exam):
        prefix = f"{exam['mount_label']} · " if exam.get('mount_label') else ""
        return f"{prefix}{ExportInterface._plain_exam_label(exam)}"

    @staticmethod
    def _plain_subject_label(subject):
        name = subject.get('name_ko') or subject.get('code') or ''
        code = subject.get('local_code') or subject.get('code') or ''
        if not code or code.startswith(('custom_', 'auto_')) or code == name:
            return name
        return f"{name} ({code})"

    @staticmethod
    def _subject_label(subject):
        prefix = f"{subject['mount_label']} · " if subject.get('mount_label') else ""
        return f"{prefix}{ExportInterface._plain_subject_label(subject)}"

    def _build_title(self, exam_text, year_from, year_to, subject_text, random_count):
        year_part = str(year_from) if year_from == year_to else f"{year_from}-{year_to}"
        exam_name = self._strip_combo_code(exam_text)
        parts = [f"{year_part} {exam_name}"]
        if subject_text:
            parts.append(self._strip_combo_code(subject_text))
        return "\n".join(parts)

    def _strip_combo_code(self, text):
        return re.sub(r"\s*\([^)]*\)\s*$", "", text or "").strip()

    def _build_filename(self, exam_code, year_from, year_to, subject_code, random_count):
        year_part = str(year_from) if year_from == year_to else f"{year_from}-{year_to}"
        filename = f"{self._local_filter_code(exam_code)}_{year_part}"
        if subject_code:
            filename += f"_{self._local_filter_code(subject_code)}"
        if random_count:
            filename += f"_rand{random_count}"
        return filename + ".docx"

    @staticmethod
    def _local_filter_code(code):
        return str(code or '').split('::', 1)[-1]

    def _build_multi_subject_title(self, exam_text, year_from, year_to, subject_requests):
        title = self._build_title(exam_text, year_from, year_to, None, None)
        subject_lines = [
            f"{request['name']} {request['count']}문제"
            for request in subject_requests
        ]
        return "\n".join([title, *subject_lines])

    def _build_mock_exam_title(self, exam_text, today=None):
        today = today or date.today()
        exam_name = self._format_exam_name_for_title(
            self._strip_combo_code(exam_text)
        )
        return f"{today:%Y.%m.%d} {exam_name} 모의고사"

    def _build_multi_exam_title(self, today=None):
        today = today or date.today()
        return f"{today:%Y.%m.%d} 여러 시험 통합 모의고사"

    def _build_multi_exam_filename(self, year_from, year_to, total_count):
        year_part = (
            str(year_from)
            if year_from == year_to
            else f"{year_from}-{year_to}"
        )
        return f"multi_exam_{year_part}_rand{total_count}.docx"

    def _format_exam_name_for_title(self, exam_name):
        return re.sub(r"(?<=\d급)(?=\S)", " ", exam_name or "", count=1)

    @staticmethod
    def _selection_section_title(mount_label, exam_name, subject_name):
        parts = [
            str(value or '').strip()
            for value in (mount_label, exam_name, subject_name)
        ]
        return " · ".join(part for part in parts if part)

    def _selected_random_subject_requests(self):
        requests = []
        invalid = []
        for row in self.__dict__.get('subjectSelectionRows', []):
            checkbox = row.get('checkbox')
            count_spin = row.get('count_spin')
            if not checkbox or not checkbox.isChecked():
                continue
            count = int(count_spin.value()) if count_spin else 0
            section_title = self._selection_section_title(
                row.get('mount_label'),
                row.get('exam_name'),
                row.get('subject_name'),
            )
            if count <= 0:
                invalid.append(
                    section_title
                    if row.get('multi_exam')
                    else row.get('name') or row.get('code')
                )
                continue
            if row.get('multi_exam'):
                requests.append({
                    'exam_code': row['exam_code'],
                    'code': row['subject_code'],
                    'name': row['subject_name'],
                    'section_title': section_title,
                    'count': count,
                })
            else:
                requests.append({
                    'code': row['code'],
                    'name': row['name'],
                    'count': count,
                })
        return requests, invalid

    def _apply_all_subject_count(self, count=None):
        if count is None or isinstance(count, bool):
            count = int(self.allSubjectCountSpin.value())
        for row in self.__dict__.get('subjectSelectionRows', []):
            checkbox = row.get('checkbox')
            count_spin = row.get('count_spin')
            if checkbox:
                checkbox.setChecked(True)
            if count_spin:
                count_spin.setValue(count)
        self._update_selection_summary()

    def _get_filtered_unique_questions(
        self,
        exam_code,
        subject_code,
        year_from,
        year_to,
        dedupe=True,
        tag_query=None,
    ):
        questions = self.repo.get_questions_with_choices(
            exam_code=exam_code,
            subject_code=subject_code,
            year_from=year_from,
            year_to=year_to,
            tag_query=tag_query,
            limit=None
        )
        questions = self._filter_questions_by_year_range(questions, year_from, year_to)
        if not dedupe:
            return questions
        return dedupe_group_aware_questions_by_content(questions)

    def _sample_questions(self, questions, count):
        return select_group_aware_questions(questions, count, rng=random)

    def export_docx(self):
        exam_code = self.examFilter.currentData()
        year_from = self.yearFromFilter.currentData()
        year_to = self.yearToFilter.currentData()
        subject_code = self.subjectFilter.currentData()
        tag_query = self._current_tag_query()
        random_count = self.randomCountSpin.value()
        subject_requests, invalid_subjects = self._selected_random_subject_requests()
        multi_exam_mode = self._is_multi_exam_mode()

        if (
            year_from is None
            or year_to is None
            or (not multi_exam_mode and not exam_code)
        ):
            InfoBar.error(
                title="출제 조건 확인 필요",
                content="시험 종류와 출제 연도 범위를 선택해 주세요.",
                parent=self
            )
            return

        if year_from > year_to:
            InfoBar.error(
                title="출제 연도 입력 오류",
                content="시작 연도는 종료 연도보다 작거나 같아야 합니다.",
                parent=self
            )
            return

        if invalid_subjects:
            InfoBar.error(
                title="문항 수 입력 오류",
                content=f"다음 과목의 문항 수를 1 이상으로 지정해 주세요: {', '.join(invalid_subjects)}",
                parent=self
            )
            return

        if multi_exam_mode and not subject_requests:
            InfoBar.error(
                title="과목 선택 필요",
                content="시험지에 포함할 과목을 하나 이상 선택하고 문항 수를 지정해 주세요.",
                parent=self,
            )
            return

        sections = None
        if subject_requests:
            questions = []
            sections = []
            selected_keys = set()
            for request in subject_requests:
                request_exam_code = (
                    request['exam_code']
                    if multi_exam_mode
                    else exam_code
                )
                request_label = request.get('section_title') or request['name']
                subject_questions = self._get_filtered_unique_questions(
                    request_exam_code,
                    request['code'],
                    year_from,
                    year_to,
                    dedupe=False,
                    tag_query=tag_query,
                )
                subject_questions = filter_group_aware_random_eligible_questions(
                    subject_questions,
                    self.validator
                )
                subject_questions = dedupe_group_aware_questions_by_content(
                    subject_questions
                )
                available_count = count_group_aware_questions(
                    subject_questions,
                    excluded_keys=selected_keys,
                )
                if request['count'] > available_count:
                    InfoBar.error(
                        title="출제 가능 문항 부족",
                        content=(
                            f"{request_label}: 요청 {request['count']}문항 / "
                            f"사용 가능 {available_count}문항입니다. 조건이나 문항 수를 조정해 주세요."
                        ),
                        parent=self
                    )
                    return
                try:
                    selected_questions = select_group_aware_questions(
                        subject_questions,
                        request['count'],
                        rng=random,
                        excluded_keys=selected_keys,
                    )
                except ValueError:
                    InfoBar.error(
                        title="출제 가능 문항 부족",
                        content=(
                            f"{request_label}: 묶음 문항을 유지하면 요청 {request['count']}문항을 "
                            f"구성할 수 없습니다. 사용 가능 문항은 {available_count}개입니다."
                        ),
                        parent=self
                    )
                    return
                questions.extend(selected_questions)
                selected_keys.update(selection_content_keys(selected_questions))
                sections.append({
                    'title': request_label,
                    'questions': selected_questions,
                })
        elif random_count > 0 and not subject_code:
            InfoBar.error(
                title="과목 선택 필요",
                content="무작위 추출에 사용할 과목을 선택해 주세요.",
                parent=self
            )
            return
        else:
            questions = self._get_filtered_unique_questions(
                exam_code,
                subject_code,
                year_from,
                year_to,
                dedupe=random_count <= 0,
                tag_query=tag_query,
            )

            if random_count > 0:
                questions = filter_group_aware_random_eligible_questions(questions, self.validator)
                questions = dedupe_group_aware_questions_by_content(questions)
                available_count = count_group_aware_questions(questions)
                if random_count > available_count:
                    InfoBar.error(
                        title="출제 가능 문항 부족",
                        content=(
                            f"요청 {random_count}문항 / 사용 가능 {available_count}문항입니다. "
                            "조건이나 문항 수를 조정해 주세요."
                        ),
                        parent=self
                    )
                    return
                try:
                    questions = self._sample_questions(questions, random_count)
                except ValueError:
                    InfoBar.error(
                        title="출제 가능 문항 부족",
                        content=(
                            f"묶음 문항을 유지하면 요청 {random_count}문항을 구성할 수 없습니다. "
                            f"사용 가능 문항은 {available_count}개입니다."
                        ),
                        parent=self
                    )
                    return

        if not questions:
            InfoBar.warning(
                title="조건에 맞는 문제 없음",
                content="출제 연도 범위, 과목 또는 해시태그 조건을 조정해 주세요.",
                parent=self
            )
            return

        if multi_exam_mode:
            filename = self._build_multi_exam_filename(
                year_from,
                year_to,
                sum(request['count'] for request in subject_requests),
            )
        elif subject_requests:
            filename = self._build_filename(
                exam_code,
                year_from,
                year_to,
                "multi",
                sum(request['count'] for request in subject_requests)
            )
        else:
            filename = self._build_filename(
                exam_code, year_from, year_to, subject_code, random_count
            )
        file_path, _ = QFileDialog.getSaveFileName(
            self, "DOCX 시험지 저장", filename, "DOCX 문서 (*.docx)"
        )

        if file_path:
            try:
                if multi_exam_mode:
                    title = self._build_multi_exam_title()
                elif subject_requests:
                    title = self._build_mock_exam_title(
                        self.examFilter.currentText()
                    )
                else:
                    title = self._build_title(
                        self.examFilter.currentText(),
                        year_from,
                        year_to,
                        self.subjectFilter.currentText() if subject_code else None,
                        random_count
                    )
                self.exporter.export(
                    title,
                    questions,
                    file_path,
                    shuffle_choices=self.shuffleChoices.isChecked(),
                    sections=sections
                )

                InfoBar.success(
                    title="내보내기 완료",
                    content=f"DOCX 시험지를 저장했습니다: {file_path}",
                    parent=self,
                    duration=3000
                )
            except Exception as e:
                InfoBar.error(
                    title="내보내기 실패",
                    content=f"DOCX 시험지를 저장하지 못했습니다. {e}",
                    parent=self
                )

    def _filter_questions_by_year_range(self, questions, year_from, year_to):
        filtered = []
        for question in questions or []:
            try:
                year = int(question.get('year'))
            except (TypeError, ValueError, AttributeError):
                continue
            if int(year_from) <= year <= int(year_to):
                filtered.append(question)
        return filtered

    def _current_tag_query(self):
        tag_filter = self.__dict__.get('tagFilter')
        if tag_filter is None or not hasattr(tag_filter, 'text'):
            return None
        text = str(tag_filter.text() or '').strip()
        return text or None
