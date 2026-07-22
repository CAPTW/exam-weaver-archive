import sqlite3

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QHeaderView, QTableWidgetItem,
    QAbstractItemView, QCheckBox, QComboBox, QMessageBox, QTextEdit, QSizePolicy
)
from PyQt5.QtCore import Qt, pyqtSignal
from qfluentwidgets import (
    TableWidget, PrimaryPushButton, PushButton, LineEdit,
    SubtitleLabel, BodyLabel, InfoBar, InfoBarPosition
)
from ...database.repository import ExamRepository
from ...database.validator import QuestionValidator
from ...choice_markers import (
    DEFAULT_CHOICE_MARKER_STYLE,
    normalize_choice_marker_style,
)
from ..explanation_image_editor import ExplanationImageEditor
from .editor import QuestionEditor

class BrowserInterface(QWidget):
    explanation_panel_requested = pyqtSignal(bool)

    def __init__(
        self,
        db_path=None,
        parent=None,
        repository=None,
        choice_marker_style=DEFAULT_CHOICE_MARKER_STYLE,
        external_explanation_host=False,
    ):
        super().__init__(parent)
        if repository is None:
            if db_path is None:
                raise ValueError("db_path or repository is required")
            repository = ExamRepository(db_path)
        self.repo = repository
        self.choice_marker_style = normalize_choice_marker_style(choice_marker_style)
        self.validator = QuestionValidator(self.repo)
        self.validation_mode = False
        self.current_explanation_question_id = None
        self.explanation_sidecar_expanded = False
        self.external_explanation_host = bool(external_explanation_host)
        self._open_editors = {}
        self.setObjectName("BrowserInterface")

        self.rootLayout = QHBoxLayout(self)
        self.rootLayout.setContentsMargins(0, 0, 0, 0)
        self.rootLayout.setSpacing(0)
        self.contentWidget = QWidget(self)
        self.vBoxLayout = QVBoxLayout(self.contentWidget)
        self.init_ui()
        self.rootLayout.addWidget(self.contentWidget, 1)
        self._init_explanation_sidecar()
        if not self.external_explanation_host:
            self.rootLayout.addWidget(self.explanationDock, 0)
        self.load_data()

    def set_repository(self, repository):
        self.explanationImageEditor.set_image_store(
            getattr(repository, "explanation_image_store", None)
        )
        self.repo = repository
        self.validator = QuestionValidator(repository)
        self.validation_mode = False
        self.current_explanation_question_id = None
        self.explanationEditor.clear()
        self.explanationInfoLabel.clear()
        self.examFilter.clear()
        self.subjectFilter.clear()
        self.load_data()

    def set_choice_marker_style(self, style):
        self.choice_marker_style = normalize_choice_marker_style(style)
        for editor in tuple(self._open_editors.values()):
            editor.set_choice_marker_style(self.choice_marker_style)

    def init_ui(self):
        # Header
        self.headerLayout = QHBoxLayout()
        self.searchRowWidget = QWidget(self)
        self.searchLayout = QHBoxLayout(self.searchRowWidget)
        self.searchLayout.setContentsMargins(0, 0, 0, 0)
        self.titleLabel = SubtitleLabel("문제 관리", self)
        self.repositoryStatusLabel = BodyLabel("현재 문제은행: 확인 중", self)
        self.repositoryStatusLabel.setWordWrap(True)
        self.repositoryStatusLabel.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self.titleBlockLayout = QVBoxLayout()
        self.titleBlockLayout.setContentsMargins(0, 0, 0, 0)
        self.titleBlockLayout.setSpacing(0)
        self.titleBlockLayout.addWidget(self.titleLabel)
        self.titleBlockLayout.addWidget(self.repositoryStatusLabel)
        
        # Filters
        self.examFilterLabel = BodyLabel("시험 종류", self)
        self.examFilterLabel.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.examFilterLabel.setMinimumWidth(
            self.examFilterLabel.fontMetrics().horizontalAdvance(
                self.examFilterLabel.text()
            ) + 8
        )

        self.examFilter = QComboBox()
        self.examFilter.setPlaceholderText("시험 선택")
        self.examFilter.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.examFilter.setMinimumContentsLength(12)
        self.examFilter.setMinimumWidth(320)
        self.examFilter.setMaximumWidth(480)
        self._apply_combo_item_height(self.examFilter)
        self.examFilter.currentTextChanged.connect(self.examFilter.setToolTip)

        self.subjectFilterLabel = BodyLabel("과목", self)
        self.subjectFilterLabel.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.subjectFilterLabel.setMinimumWidth(64)

        self.subjectFilter = QComboBox()
        self.subjectFilter.setPlaceholderText("과목 선택")
        self.subjectFilter.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.subjectFilter.setMinimumContentsLength(10)
        self.subjectFilter.setMinimumWidth(320)
        self.subjectFilter.setMaximumWidth(480)
        self._apply_combo_item_height(self.subjectFilter)

        self.examFilter.currentIndexChanged.connect(lambda *_: self._on_exam_filter_changed())
        self.subjectFilter.currentIndexChanged.connect(lambda *_: self.load_data())
        
        self.searchBox = LineEdit()
        self.searchBox.setPlaceholderText("해시태그 또는 문제 내용 검색")
        self.searchBox.setMinimumWidth(320)
        self.searchBox.returnPressed.connect(self.load_data)
        
        self.btnRefresh = PrimaryPushButton("조회", self)
        self.btnRefresh.clicked.connect(self.load_data)

        self.btnAddManual = PrimaryPushButton("문제 추가", self)
        self.btnAddManual.setToolTip("개인이 만든 문제를 수동으로 추가")
        self.btnAddManual.clicked.connect(self.add_manual_question)

        self.btnAddDescriptive = PushButton("서술형 문제 추가", self)
        self.btnAddDescriptive.setToolTip("문제와 모범답안으로 구성된 서술형 문제 추가")
        self.btnAddDescriptive.clicked.connect(self.add_descriptive_question)

        self.btnValidate = PrimaryPushButton("오류 검사", self)
        self.btnValidate.clicked.connect(self.load_validation_results)

        self.btnDeleteSelected = PushButton("선택 문제 삭제", self)
        self.btnDeleteSelected.clicked.connect(self.delete_selected_questions)

        self.actionLayout = QGridLayout()
        self.actionLayout.setContentsMargins(0, 0, 0, 0)
        self.actionLayout.setHorizontalSpacing(6)
        self.actionLayout.setVerticalSpacing(4)
        self.actionLayout.addWidget(self.btnAddManual, 0, 0)
        self.actionLayout.addWidget(self.btnAddDescriptive, 0, 1)
        self.actionLayout.addWidget(self.btnValidate, 1, 0)
        self.actionLayout.addWidget(self.btnDeleteSelected, 1, 1)

        self.filterLayout = QGridLayout()
        self.filterLayout.setContentsMargins(0, 0, 0, 0)
        self.filterLayout.setHorizontalSpacing(6)
        self.filterLayout.setVerticalSpacing(4)
        self.filterLayout.addWidget(self.examFilterLabel, 0, 0)
        self.filterLayout.addWidget(self.examFilter, 0, 1)
        self.filterLayout.addWidget(self.subjectFilterLabel, 1, 0)
        self.filterLayout.addWidget(self.subjectFilter, 1, 1)

        self.headerLayout.addLayout(self.titleBlockLayout)
        self.headerLayout.addStretch(1)
        self.headerLayout.addLayout(self.filterLayout)
        self.headerLayout.addLayout(self.actionLayout)

        self.searchLayout.addWidget(self.searchBox, 1)
        self.searchLayout.addWidget(self.btnRefresh)

        # Table
        self.table = TableWidget(self)
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["선택", "ID", "정보", "문제", "해시태그", "관리"])
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 54)
        self.table.setColumnWidth(1, 70)
        self.table.setColumnWidth(4, 180)
        self.table.setColumnWidth(5, 284)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        # Layout
        self.vBoxLayout.addLayout(self.headerLayout)
        self.vBoxLayout.addWidget(self.searchRowWidget)
        self.vBoxLayout.addWidget(self.table)

    def _init_explanation_sidecar(self):
        self.explanationDock = QWidget(self)
        self.explanationDockLayout = QHBoxLayout(self.explanationDock)
        self.explanationDockLayout.setContentsMargins(0, 0, 0, 0)
        self.explanationDockLayout.setSpacing(4)

        self.explanationToggleButton = PushButton("<", self.explanationDock)
        self.explanationToggleButton.setFixedSize(30, 86)
        self.explanationToggleButton.setToolTip("해설 패널 펼치기")
        self.explanationToggleButton.clicked.connect(self.toggle_explanation_sidecar)

        self.explanationSidecar = QWidget(self.explanationDock)
        self.explanationSidecar.setObjectName("ExplanationSidecar")
        self.explanationSidecar.setMinimumWidth(360)
        self.explanationSidecar.setMaximumWidth(430)
        self.explanationSidecar.setStyleSheet(
            "#ExplanationSidecar { border-left: 1px solid rgba(0, 0, 0, 24); }"
        )
        sideLayout = QVBoxLayout(self.explanationSidecar)
        sideLayout.setContentsMargins(14, 14, 14, 14)
        sideLayout.setSpacing(10)

        headerLayout = QHBoxLayout()
        self.explanationTitleLabel = SubtitleLabel("문제 해설", self.explanationSidecar)
        self.explanationCollapseButton = PushButton("접기", self.explanationSidecar)
        self.explanationCollapseButton.setFixedSize(54, 30)
        self.explanationCollapseButton.clicked.connect(
            lambda: self.set_explanation_sidecar_expanded(False)
        )
        headerLayout.addWidget(self.explanationTitleLabel)
        headerLayout.addStretch(1)
        headerLayout.addWidget(self.explanationCollapseButton)
        sideLayout.addLayout(headerLayout)

        self.explanationInfoLabel = LineEdit(self.explanationSidecar)
        self.explanationInfoLabel.setReadOnly(True)
        self.explanationInfoLabel.setPlaceholderText("해설을 편집할 문제를 선택하세요.")
        sideLayout.addWidget(self.explanationInfoLabel)

        self.explanationEditor = QTextEdit(self.explanationSidecar)
        self.explanationEditor.setPlaceholderText("사용자 해설을 입력하세요.")
        self.explanationEditor.setMinimumHeight(280)
        sideLayout.addWidget(self.explanationEditor, 1)

        self.explanationImageEditor = ExplanationImageEditor(
            self.explanationSidecar,
            image_store=getattr(self.repo, "explanation_image_store", None),
        )
        sideLayout.addWidget(self.explanationImageEditor, 0)

        buttonLayout = QHBoxLayout()
        self.saveExplanationButton = PrimaryPushButton("저장", self.explanationSidecar)
        self.clearExplanationButton = PushButton("비우기", self.explanationSidecar)
        self.saveExplanationButton.clicked.connect(self.save_current_explanation)
        self.clearExplanationButton.clicked.connect(self.clear_current_explanation)
        buttonLayout.addWidget(self.clearExplanationButton)
        buttonLayout.addStretch(1)
        buttonLayout.addWidget(self.saveExplanationButton)
        sideLayout.addLayout(buttonLayout)

        self.explanationDockLayout.addWidget(
            self.explanationToggleButton,
            0,
            Qt.AlignmentFlag.AlignTop,
        )
        self.explanationDockLayout.addWidget(self.explanationSidecar)
        self.set_explanation_sidecar_expanded(False)

    def take_explanation_panel(self):
        """Detach the explanation editor for the main window's shared sidecar."""
        self.explanationDockLayout.removeWidget(self.explanationSidecar)
        self.explanationSidecar.setParent(None)
        self.explanationSidecar.setMinimumWidth(340)
        self.explanationSidecar.setMaximumWidth(430)
        self.explanationEditor.setMinimumHeight(140)
        return self.explanationSidecar

    def _apply_combo_item_height(self, combo, height=44):
        view = combo.view()
        view.setStyleSheet(f"QListView::item {{ height: {height}px; }}")

    def _update_combo_text_visibility(self, combo, max_popup_width=720):
        item_texts = [combo.itemText(index) for index in range(combo.count())]
        for index, item_text in enumerate(item_texts):
            combo.setItemData(index, item_text, Qt.ItemDataRole.ToolTipRole)

        longest_width = max(
            (combo.fontMetrics().horizontalAdvance(text) for text in item_texts),
            default=0,
        )
        combo.view().setMinimumWidth(
            min(max(combo.minimumWidth(), longest_width + 48), max_popup_width)
        )
        combo.setToolTip(combo.currentText())

    def toggle_explanation_sidecar(self):
        self.set_explanation_sidecar_expanded(not self.explanation_sidecar_expanded)

    def set_explanation_sidecar_expanded(self, expanded: bool):
        self.explanation_sidecar_expanded = bool(expanded)
        if self.external_explanation_host:
            self.explanation_panel_requested.emit(self.explanation_sidecar_expanded)
            return
        self.explanationSidecar.setVisible(self.explanation_sidecar_expanded)
        self.explanationToggleButton.setText(">" if self.explanation_sidecar_expanded else "<")
        self.explanationToggleButton.setToolTip(
            "해설 패널 접기" if self.explanation_sidecar_expanded else "해설 패널 펼치기"
        )
        self.explanationDock.setMaximumWidth(464 if self.explanation_sidecar_expanded else 34)

    def _load_exam_filters(self):
        current_code = self.examFilter.currentData()
        options = self.repo.get_filter_options()
        self._update_repository_status(options)
        self.examFilter.blockSignals(True)
        self.examFilter.clear()
        self.examFilter.addItem("전체 시험", None)
        for exam in options.get('exams', []):
            prefix = f"{exam['mount_label']} · " if exam.get('mount_label') else ""
            self.examFilter.addItem(
                f"{prefix}{exam['name']} ({exam.get('local_code') or exam['code']})",
                exam['code']
            )

        if current_code is not None:
            index = self.examFilter.findData(current_code)
            if index >= 0:
                self.examFilter.setCurrentIndex(index)
        self._update_combo_text_visibility(self.examFilter)
        self.examFilter.blockSignals(False)

    def _update_repository_status(self, options):
        labels = []
        for exam in options.get('exams', []):
            label = str(exam.get('mount_label') or '').strip()
            if label and label not in labels:
                labels.append(label)
        if labels:
            status = f"연결된 문제은행: {', '.join(labels)}"
        else:
            status = "현재 문제은행: 기본 문제은행"
        self.repositoryStatusLabel.setText(status)
        self.repositoryStatusLabel.setToolTip(status)

    def _load_subject_filters(self):
        current_code = self.subjectFilter.currentData()
        exam_code = self.examFilter.currentData()
        self.subjectFilter.blockSignals(True)
        self.subjectFilter.clear()
        self.subjectFilter.addItem("전체 과목", None)
        for subject in self.repo.get_subject_options(exam_code):
            self.subjectFilter.addItem(
                self._subject_label(subject),
                subject['code']
            )

        if current_code is not None:
            index = self.subjectFilter.findData(current_code)
            if index >= 0:
                self.subjectFilter.setCurrentIndex(index)
        self.subjectFilter.blockSignals(False)

    def _on_exam_filter_changed(self):
        self._load_subject_filters()
        self.load_data()

    @staticmethod
    def _subject_label(subject):
        name = subject.get('name_ko') or subject.get('code') or ''
        code = subject.get('local_code') or subject.get('code') or ''
        prefix = f"{subject['mount_label']} · " if subject.get('mount_label') else ""
        if not code or code.startswith(('custom_', 'auto_')) or code == name:
            return f"{prefix}{name}"
        return f"{prefix}{name} ({code})"
        
    def load_data(self):
        self.validation_mode = False
        self.table.setHorizontalHeaderLabels(["선택", "ID", "정보", "문제", "해시태그", "관리"])
        if self.examFilter.count() == 0:
            self._load_exam_filters()
        if self.subjectFilter.count() == 0:
            self._load_subject_filters()

        exam_code = self.examFilter.currentData()
        subject_code = self.subjectFilter.currentData()
            
        search_text = self.searchBox.text().strip()
        questions = self.repo.search_questions(
            exam_code=exam_code,
            subject_code=subject_code,
            search_text=search_text if search_text else None,
            limit=50
        )
        
        self.table.setRowCount(0)
        for q in questions:
            row = self.table.rowCount()
            self.table.insertRow(row)
            
            self.table.setCellWidget(row, 0, self._make_select_checkbox(q['id']))
            self.table.setItem(row, 1, QTableWidgetItem(str(q['id'])))
            
            # Info
            self.table.setItem(row, 2, QTableWidgetItem(self._format_info(q)))
            
            # Text
            self.table.setItem(row, 3, QTableWidgetItem(self._format_question_preview(q)))
            
            # Tags
            self.table.setItem(row, 4, QTableWidgetItem(str(q.get('tags') or '')))
            
            self.table.setCellWidget(row, 5, self._make_action_widget(q['id']))

    def load_validation_results(self):
        self.validation_mode = True
        if self.examFilter.count() == 0:
            self._load_exam_filters()
        if self.subjectFilter.count() == 0:
            self._load_subject_filters()

        exam_code = self.examFilter.currentData()
        subject_code = self.subjectFilter.currentData()
        search_text = self.searchBox.text().strip()
        findings = self.validator.scan(
            exam_code=exam_code,
            subject_code=subject_code,
            search_text=search_text if search_text else None,
            limit=None
        )

        self.table.setHorizontalHeaderLabels(["선택", "ID", "정보", "문제", "오류", "관리"])
        self.table.setRowCount(0)
        for finding in findings:
            q = finding['question']
            row = self.table.rowCount()
            self.table.insertRow(row)

            self.table.setCellWidget(row, 0, self._make_select_checkbox(q['id']))
            self.table.setItem(row, 1, QTableWidgetItem(str(q['id'])))

            self.table.setItem(row, 2, QTableWidgetItem(self._format_info(q)))

            self.table.setItem(row, 3, QTableWidgetItem(self._format_question_preview(q)))

            self.table.setItem(row, 4, QTableWidgetItem(finding['summary']))

            self.table.setCellWidget(row, 5, self._make_action_widget(q['id']))

        if not findings:
            InfoBar.success(
                title='검사 완료',
                content="검출된 오류가 없습니다.",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP_RIGHT,
                duration=2000,
                parent=self
            )
        else:
            InfoBar.warning(
                title='검사 완료',
                content=f"{len(findings)}개 문제에서 오류/주의 항목을 찾았습니다.",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP_RIGHT,
                duration=3000,
                parent=self
            )

    def open_editor(self, question_id):
        existing = self._open_editors.get(question_id)
        if existing is not None:
            self._activate_editor(existing)
            return existing

        repository = self.repo
        q = repository.get_question(question_id)
        if not q:
            return None

        editor_question = dict(q)
        editor_question['exam_code'] = q.get('mounted_exam_code') or q.get('exam_code')
        editor_question['subject_code'] = q.get('mounted_subject_code') or q.get('subject_code')

        dialog = QuestionEditor(
            self.window(),
            editor_question,
            subject_options=repository.get_subject_options(editor_question.get('exam_code')),
            choice_marker_style=self.choice_marker_style,
        )
        if hasattr(dialog, "set_explanation_image_store"):
            dialog.set_explanation_image_store(
                getattr(repository, "explanation_image_store", None)
            )
        dialog.setModal(False)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._open_editors[question_id] = dialog
        dialog.accepted.connect(
            lambda qid=question_id, editor=dialog, repo=repository:
            self._save_open_editor(qid, editor, repo)
        )
        dialog.finished.connect(
            lambda _result, qid=question_id, editor=dialog:
            self._release_editor(qid, editor)
        )
        dialog.show()
        return dialog

    def _activate_editor(self, dialog):
        if dialog.isMinimized():
            dialog.showNormal()
        else:
            dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _save_open_editor(self, question_id, dialog, repository):
        new_data = dialog.get_data()
        try:
            updated = repository.update_question(question_id, new_data)
        except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
            self._show_write_error("수정", exc)
            return
        if not updated:
            InfoBar.error(
                title='오류',
                content="문제은행에서 문제를 수정하지 못했습니다.",
                parent=self
            )
            return

        saved_question = repository.get_question(question_id)
        if saved_question and hasattr(dialog, "explanationImageEditor"):
            attachments = saved_question.get('explanation_images') or []
            dialog.explanationImageEditor.set_attachment(
                attachments[0] if attachments else None
            )

        InfoBar.success(
            title='수정 완료',
            content="문제가 성공적으로 수정되었습니다.",
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP_RIGHT,
            duration=2000,
            parent=self
        )
        if self.validation_mode:
            self.load_validation_results()
        else:
            self.load_data()

    def _release_editor(self, question_id, dialog):
        if self._open_editors.get(question_id) is dialog:
            self._open_editors.pop(question_id, None)

    def add_manual_question(self):
        dialog = QuestionEditor(
            self.window(),
            self.repo.get_manual_question_template(),
            subject_options=self.repo.get_manual_subject_options(),
            create_mode=True,
            choice_marker_style=self.choice_marker_style,
        )
        if hasattr(dialog, "set_explanation_image_store"):
            dialog.set_explanation_image_store(
                getattr(self.repo, "explanation_image_store", None)
            )
        if not dialog.exec():
            return

        data = dialog.get_data()
        question_id = self.repo.create_manual_question(data)
        if hasattr(dialog, "explanationImageEditor"):
            dialog.explanationImageEditor.discard_pending()
        if question_id:
            InfoBar.success(
                title='추가 완료',
                content=f"개인 제작 문제 ID {question_id}번을 추가했습니다.",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP_RIGHT,
                duration=2500,
                parent=self
            )
            self._load_exam_filters()
            self._select_filter_value(self.examFilter, data.get('exam_code'))
            self._load_subject_filters()
            self._select_filter_value(self.subjectFilter, data.get('subject_code'))
            self.load_data()
        else:
            InfoBar.error(
                title='추가 실패',
                content="같은 연도/회차/문제번호가 이미 있거나 문제은행에 저장하지 못했습니다.",
                parent=self
            )

    def add_descriptive_question(self):
        dialog = QuestionEditor(
            self.window(),
            self.repo.get_manual_descriptive_question_template(),
            subject_options=self.repo.get_manual_subject_options(),
            create_mode=True,
            choice_marker_style=self.choice_marker_style,
        )
        if hasattr(dialog, "set_explanation_image_store"):
            dialog.set_explanation_image_store(
                getattr(self.repo, "explanation_image_store", None)
            )
        if not dialog.exec():
            return

        data = dialog.get_data()
        question_id = self.repo.create_manual_question(data)
        if hasattr(dialog, "explanationImageEditor"):
            dialog.explanationImageEditor.discard_pending()
        if question_id:
            InfoBar.success(
                title='추가 완료',
                content=f"서술형 문제 ID {question_id}번을 추가했습니다.",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP_RIGHT,
                duration=2500,
                parent=self
            )
            self._load_exam_filters()
            self._select_filter_value(self.examFilter, data.get('exam_code'))
            self._load_subject_filters()
            self._select_filter_value(self.subjectFilter, data.get('subject_code'))
            self.load_data()
        else:
            InfoBar.error(
                title='추가 실패',
                content="같은 연도/회차/문제번호가 이미 있거나 문제은행에 저장하지 못했습니다.",
                parent=self
            )

    def clone_question(self, question_id):
        template = self.repo.get_manual_question_clone_template(question_id)
        if not template:
            InfoBar.error(
                title='복제 실패',
                content="복제할 문제를 찾을 수 없습니다.",
                parent=self
            )
            return

        dialog = QuestionEditor(
            self.window(),
            template,
            subject_options=self.repo.get_manual_subject_options(),
            create_mode=True,
            choice_marker_style=self.choice_marker_style,
        )
        if hasattr(dialog, "set_explanation_image_store"):
            dialog.set_explanation_image_store(
                getattr(self.repo, "explanation_image_store", None)
            )
        if not dialog.exec():
            return

        data = dialog.get_data()
        new_question_id = self.repo.create_manual_question(data)
        if hasattr(dialog, "explanationImageEditor"):
            dialog.explanationImageEditor.discard_pending()
        if new_question_id:
            InfoBar.success(
                title='복제 완료',
                content=f"개인 제작 문제 ID {new_question_id}번으로 복제했습니다.",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP_RIGHT,
                duration=2500,
                parent=self
            )
            self._load_exam_filters()
            self._select_filter_value(self.examFilter, data.get('exam_code'))
            self._load_subject_filters()
            self._select_filter_value(self.subjectFilter, data.get('subject_code'))
            self.load_data()
        else:
            InfoBar.error(
                title='복제 실패',
                content="같은 연도/회차/문제번호가 이미 있거나 문제은행에 저장하지 못했습니다.",
                parent=self
            )

    @staticmethod
    def _select_filter_value(combo, value):
        if value is None:
            return
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _format_info(self, question):
        prefix = "공통 " if question.get('group_id') is not None else ""
        type_prefix = "서술형 " if question.get('question_type') == 'descriptive' else ""
        info = (
            f"{prefix}{type_prefix}{question['year']}-{question['session']} "
            f"{question['subject_name']} {question['question_number']}번"
        )
        mount_label = question.get('mount_label')
        return f"{mount_label} · {info}" if mount_label else info

    def _format_question_preview(self, question):
        question_text = question.get('question_text') or ''
        text = question_text[:50] + "..." if len(question_text) > 50 else question_text
        prefixes = []
        if question.get('group_id') is not None:
            prefixes.append("[공통]")
        if question.get('question_type') == 'descriptive':
            prefixes.append("[서술형]")
        return f"{' '.join(prefixes)} {text}".strip() if prefixes else text

    def _make_action_widget(self, question_id):
        widget = QWidget(self)
        widget.setMinimumWidth(272)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        edit_btn = PrimaryPushButton("수정", self)
        edit_btn.setFixedSize(60, 30)
        edit_btn.clicked.connect(lambda checked, q_id=question_id: self.open_editor(q_id))

        clone_btn = PushButton("복제", self)
        clone_btn.setToolTip("이 문제를 개인 제작 문제로 복사해서 수정")
        clone_btn.setFixedSize(60, 30)
        clone_btn.clicked.connect(lambda checked, q_id=question_id: self.clone_question(q_id))

        delete_btn = PushButton("삭제", self)
        delete_btn.setFixedSize(60, 30)
        delete_btn.clicked.connect(lambda checked, q_id=question_id: self.delete_question(q_id))

        explanation_btn = PushButton("해설", self)
        explanation_btn.setFixedSize(60, 30)
        explanation_btn.clicked.connect(lambda checked, q_id=question_id: self.open_explanation(q_id))

        layout.addWidget(edit_btn)
        layout.addWidget(clone_btn)
        layout.addWidget(delete_btn)
        layout.addWidget(explanation_btn)
        return widget

    def open_explanation(self, question_id):
        q = self.repo.get_question(question_id)
        if not q:
            InfoBar.error(title='오류', content="문제를 찾을 수 없습니다.", parent=self)
            return

        self.current_explanation_question_id = question_id
        self.explanationInfoLabel.setText(self._format_info(q))
        self.explanationEditor.setPlainText(q.get('explanation') or '')
        attachments = q.get('explanation_images') or []
        self.explanationImageEditor.set_attachment(
            attachments[0] if attachments else None
        )
        self.set_explanation_sidecar_expanded(True)

    def save_current_explanation(self):
        if not self.current_explanation_question_id:
            InfoBar.warning(title='선택 없음', content="해설을 저장할 문제를 먼저 선택하세요.", parent=self)
            return

        try:
            updated = self.repo.update_question_explanation(
                self.current_explanation_question_id,
                self.explanationEditor.toPlainText(),
                image_change=self.explanationImageEditor.image_change(),
            )
        except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
            self._show_write_error("해설 저장", exc)
            return

        if updated:
            question = self.repo.get_question(self.current_explanation_question_id)
            attachments = question.get('explanation_images') if question else []
            self.explanationImageEditor.set_attachment(
                attachments[0] if attachments else None
            )
            InfoBar.success(title='저장 완료', content="문제 해설을 저장했습니다.", parent=self)
            if self.validation_mode:
                self.load_validation_results()
            else:
                self.load_data()
        else:
            InfoBar.error(title='저장 실패', content="해설 저장에 실패했습니다.", parent=self)

    def clear_current_explanation(self):
        self.explanationEditor.clear()

    def _make_select_checkbox(self, question_id):
        widget = QWidget(self)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        checkbox = QCheckBox(self)
        checkbox.setProperty("question_id", question_id)
        layout.addWidget(checkbox)
        return widget

    def selected_question_ids(self):
        ids = []
        for row in range(self.table.rowCount()):
            widget = self.table.cellWidget(row, 0)
            if widget is None:
                continue
            checkbox = widget.findChild(QCheckBox)
            if checkbox is not None and checkbox.isChecked():
                ids.append(checkbox.property("question_id"))
        return ids

    def delete_question(self, question_id):
        result = QMessageBox.question(
            self,
            "문제 삭제",
            f"ID {question_id} 문제를 삭제할까요?\n삭제하면 선지와 모의고사 연결에서도 제거됩니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if result != QMessageBox.StandardButton.Yes:
            return

        try:
            deleted = self.repo.delete_question(question_id)
        except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
            self._show_write_error("삭제", exc)
            return

        if deleted:
            InfoBar.success(
                title='삭제 완료',
                content="문제가 삭제되었습니다.",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP_RIGHT,
                duration=2000,
                parent=self
            )
            if self.validation_mode:
                self.load_validation_results()
            else:
                self.load_data()
        else:
            InfoBar.error(
                title='삭제 실패',
                content="문제은행에서 문제를 삭제하지 못했습니다.",
                parent=self
            )

    def delete_selected_questions(self):
        question_ids = self.selected_question_ids()
        if not question_ids:
            InfoBar.warning(
                title='선택 없음',
                content="삭제할 문제를 먼저 선택하세요.",
                parent=self
            )
            return

        result = QMessageBox.question(
            self,
            "선택 문제 삭제",
            f"선택한 {len(question_ids)}개 문제를 삭제할까요?\n삭제하면 선지와 모의고사 연결에서도 제거됩니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if result != QMessageBox.StandardButton.Yes:
            return

        try:
            deleted_count = self.repo.delete_questions(question_ids)
        except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
            self._show_write_error("선택 삭제", exc)
            return
        InfoBar.success(
            title='삭제 완료',
            content=f"{deleted_count}개 문제가 삭제되었습니다.",
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP_RIGHT,
            duration=2000,
            parent=self
        )
        if self.validation_mode:
            self.load_validation_results()
        else:
            self.load_data()

    def _show_write_error(self, action, exc):
        InfoBar.error(
            title=f'{action} 실패',
            content=str(exc),
            parent=self,
        )
