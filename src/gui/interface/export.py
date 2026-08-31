import random
import re
from datetime import date
from pathlib import Path

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
from ...exporter.builder import ExamDocumentBuilder
from ...choice_markers import (
    DEFAULT_CHOICE_MARKER_STYLE,
    normalize_choice_marker_style,
)
from ..export_formats import (
    DEFAULT_FORMAT,
    FORMAT_DOCX,
    FORMAT_HWPX,
    button_text,
    default_suffix,
    dialog_filter,
    dialog_title,
    error_message,
    normalize_save_path,
    warning_summary,
)


class ExportInterface(QScrollArea):
    def __init__(
        self,
        db_path=None,
        parent=None,
        repository=None,
        choice_marker_style=DEFAULT_CHOICE_MARKER_STYLE,
        hwpx_compiler_factory=None,
    ):
        super().__init__(parent)
        if repository is None:
            if db_path is None:
                raise ValueError("db_path or repository is required")
            repository = ExamRepository(db_path)
        self.repo = repository
        self.validator = QuestionValidator(self.repo)
        self.choice_marker_style = normalize_choice_marker_style(choice_marker_style)
        self.exporter = DocxExporter(choice_marker_style=self.choice_marker_style)
        self.document_builder = ExamDocumentBuilder()
        self.hwpx_compiler_factory = hwpx_compiler_factory
        self._hwpx_compiler = None
        self._export_state = {"format": DEFAULT_FORMAT}
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

    def set_choice_marker_style(self, style):
        self.choice_marker_style = normalize_choice_marker_style(style)
        self.exporter.set_choice_marker_style(self.choice_marker_style)
        self._hwpx_compiler = None

    def init_ui(self):
        self.vBoxLayout.setContentsMargins(30, 30, 30, 30)
        self.vBoxLayout.setSpacing(10)

        self.titleLabel = SubtitleLabel("시험지 내보내기", self)
        self.vBoxLayout.addWidget(self.titleLabel)

        self.descLabel = BodyLabel(
            "출제 조건과 과목별 문항 수를 선택해 DOCX 또는 HWPX 시험지를 만듭니다.", self
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
        self.btnApplySelectedSubjects = PushButton("선택한 과목에만 적용", self)
        self._apply_input_height(self.btnApplySelectedSubjects)
        self.btnApplySelectedSubjects.setFixedWidth(190)
        self.btnApplySelectedSubjects.setEnabled(False)
        self.btnApplySelectedSubjects.clicked.connect(
            self._apply_selected_subject_count
        )
        self.randomSubjectBulkLayout.addWidget(self.allSubjectCountLabel)
        self.randomSubjectBulkLayout.addWidget(self.allSubjectCountSpin)
        self.randomSubjectBulkLayout.addWidget(self.btnApplyAllSubjects)
        self.randomSubjectBulkLayout.addWidget(self.btnApplySelectedSubjects)
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

        self.tableRenderModeLabel = BodyLabel("표 출력 방식", self)
        self.tableRenderModeFilter = QComboBox(self)
        self.tableRenderModeFilter.addItem("자동", "auto")
        self.tableRenderModeFilter.addItem("원본 이미지", "image")
        self.tableRenderModeFilter.addItem("편집 가능한 표", "native")
        self.tableRenderModeFilter.setToolTip(
            "자동은 신뢰도 0.90 이상의 단순 표를 Word 표로 만들고, "
            "그 외 표는 저장된 원본 이미지를 사용합니다."
        )
        self.tableRenderModeFilter.currentIndexChanged.connect(
            self._on_table_render_mode_changed
        )
        self.vBoxLayout.addWidget(self.tableRenderModeLabel)
        self.vBoxLayout.addWidget(self.tableRenderModeFilter)

        self.formatLabel = BodyLabel("출력 형식", self)
        self.outputFormatFilter = QComboBox(self)
        self.outputFormatFilter.addItem("DOCX · Word 문서", FORMAT_DOCX)
        self.outputFormatFilter.addItem("HWPX · 한글 표준 문서", FORMAT_HWPX)
        self.outputFormatFilter.setCurrentIndex(0)
        self.outputFormatFilter.setToolTip("저장할 시험지 파일 형식을 선택합니다. 선택은 이 세션에서만 유지됩니다.")
        self.outputFormatFilter.currentIndexChanged.connect(self._on_output_format_changed)
        self.vBoxLayout.addWidget(self.formatLabel)
        self.vBoxLayout.addWidget(self.outputFormatFilter)

        self.vBoxLayout.addStretch(1)

        self.btnExport = PrimaryPushButton(button_text(DEFAULT_FORMAT), self)
        self.btnExport.clicked.connect(self.export_exam)
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

    def _selected_table_render_mode(self):
        combo = self.__dict__.get('tableRenderModeFilter')
        if combo is None:
            return 'auto'
        mode = combo.currentData()
        return mode if mode in {'auto', 'image', 'native'} else 'auto'

    def _on_table_render_mode_changed(self, *_args):
        self.exporter.set_table_render_mode(self._selected_table_render_mode())

    def _safe_attr(self, name, default=None):
        try:
            return object.__getattribute__(self, name)
        except Exception:
            return default

    def _selected_output_format(self):
        state = self._safe_attr("_export_state")
        if isinstance(state, dict) and state.get("format") in {FORMAT_DOCX, FORMAT_HWPX}:
            return state["format"]
        combo = self._safe_attr("outputFormatFilter")
        if combo is None:
            return DEFAULT_FORMAT
        value = combo.currentData()
        return value if value in {FORMAT_DOCX, FORMAT_HWPX} else DEFAULT_FORMAT

    def _on_output_format_changed(self, *_args):
        combo = self._safe_attr("outputFormatFilter")
        state = self._safe_attr("_export_state")
        if combo is not None and isinstance(state, dict):
            value = combo.currentData()
            if value in {FORMAT_DOCX, FORMAT_HWPX}:
                state["format"] = value
        button = self._safe_attr("btnExport")
        if button is not None:
            button.setText(button_text(self._selected_output_format()))

    def _get_hwpx_compiler(self):
        existing = self._safe_attr("_hwpx_compiler")
        if existing is not None:
            return existing
        factory = self._safe_attr("hwpx_compiler_factory")
        if factory is None:
            from ...exporter.hwpx import HwpxCompiler

            factory = lambda: HwpxCompiler(choice_marker_style=self.choice_marker_style)
        compiler = factory()
        self._hwpx_compiler = compiler
        return compiler

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
        button = self.__dict__.get('btnApplySelectedSubjects')
        if button is not None:
            button.setEnabled(selected > 0)

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
        return filename + default_suffix(self._selected_output_format())

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
        return f"multi_exam_{year_part}_rand{total_count}{default_suffix(self._selected_output_format())}"

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

    def _apply_selected_subject_count(self, count=None):
        if count is None or isinstance(count, bool):
            count = int(self.allSubjectCountSpin.value())
        applied = 0
        for row in self.__dict__.get('subjectSelectionRows', []):
            checkbox = row.get('checkbox')
            count_spin = row.get('count_spin')
            if not checkbox or not checkbox.isChecked() or count_spin is None:
                continue
            count_spin.setValue(count)
            applied += 1
        self._update_selection_summary()
        return applied

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

    def _render_selected(self, document, file_path, output_format):
        if output_format == FORMAT_HWPX:
            result = self._get_hwpx_compiler().export_document(document, file_path)
            if result.warnings:
                InfoBar.warning(
                    title="HWPX 내보내기 완료 · 경고 포함",
                    content=(
                        f"{Path(file_path).name} · 경고 {len(result.warnings)}건 · "
                        f"{warning_summary(result.warnings, result.fallback_count)}"
                    ),
                    parent=self,
                    duration=5000,
                )
            else:
                InfoBar.success(
                    title="HWPX 내보내기 완료",
                    content=Path(file_path).name,
                    parent=self,
                    duration=3000,
                )
            return
        exporter = self.exporter
        if hasattr(exporter, "warnings"):
            exporter.warnings = []
        exporter.export_document(document, file_path)
        export_warnings = getattr(exporter, "warnings", [])
        if export_warnings:
            InfoBar.warning(
                title="내보내기 완료 · 표 폴백 적용",
                content=(
                    f"DOCX를 저장했으며 {len(export_warnings)}개 표에 "
                    "대체 출력 방식을 적용했습니다."
                ),
                parent=self,
                duration=5000,
            )
        else:
            InfoBar.success(
                title="내보내기 완료",
                content=f"DOCX 시험지를 저장했습니다: {file_path}",
                parent=self,
                duration=3000,
            )

    def export_docx(self):
        return self.export_exam()

    def export_exam(self):
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
        output_format = self._selected_output_format()
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            dialog_title(output_format),
            filename,
            dialog_filter(output_format),
        )
        if not file_path:
            return
        normalized, path_error = normalize_save_path(file_path, output_format)
        if path_error:
            InfoBar.warning(
                title="확장자 확인 필요",
                content=error_message(path_error),
                parent=self,
            )
            return
        file_path = normalized
        button = self.__dict__.get("btnExport")
        if button is not None:
            button.setEnabled(False)
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
            builder = self.__dict__.get("document_builder") or ExamDocumentBuilder()
            document = builder.build(
                    title=title,
                    questions=questions,
                    sections=sections,
                    shuffle_choices=self.shuffleChoices.isChecked(),
                    include_answer_key=False,
                )
            self._render_selected(document, file_path, output_format)
        except Exception as exc:
            from ...exporter.hwpx import HwpxCompileError

            if isinstance(exc, HwpxCompileError):
                InfoBar.error(
                    title="HWPX 내보내기 실패",
                    content=error_message(exc.code),
                    parent=self,
                )
            else:
                InfoBar.error(
                    title="내보내기 실패",
                    content="시험지를 저장하지 못했습니다.",
                    parent=self
                )
        finally:
            if button is not None:
                button.setEnabled(True)

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
