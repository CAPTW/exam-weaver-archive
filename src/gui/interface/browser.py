from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QHeaderView, QTableWidgetItem,
    QAbstractItemView, QCheckBox, QComboBox, QMessageBox, QTextEdit
)
from PyQt5.QtCore import Qt
from qfluentwidgets import (
    TableWidget, PrimaryPushButton, PushButton, LineEdit,
    SubtitleLabel, BodyLabel, InfoBar, InfoBarPosition
)
from ...database.repository import ExamRepository
from ...database.validator import QuestionValidator
from .editor import QuestionEditor

class BrowserInterface(QWidget):
    def __init__(self, db_path, parent=None):
        super().__init__(parent)
        self.repo = ExamRepository(db_path)
        self.validator = QuestionValidator(self.repo)
        self.validation_mode = False
        self.current_explanation_question_id = None
        self.explanation_sidecar_expanded = False
        self.setObjectName("BrowserInterface")

        self.rootLayout = QHBoxLayout(self)
        self.rootLayout.setContentsMargins(0, 0, 0, 0)
        self.rootLayout.setSpacing(0)
        self.contentWidget = QWidget(self)
        self.vBoxLayout = QVBoxLayout(self.contentWidget)
        self.init_ui()
        self.rootLayout.addWidget(self.contentWidget, 1)
        self._init_explanation_sidecar()
        self.rootLayout.addWidget(self.explanationDock, 0)
        self.load_data()

    def init_ui(self):
        # Header
        self.headerLayout = QHBoxLayout()
        self.titleLabel = SubtitleLabel("문제 관리", self)
        
        # Filters
        self.examFilterLabel = BodyLabel("EXAM", self)
        self.examFilterLabel.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.examFilterLabel.setMinimumWidth(44)

        self.examFilter = QComboBox()
        self.examFilter.setPlaceholderText("시험 선택")
        self._apply_combo_item_height(self.examFilter)

        self.subjectFilterLabel = BodyLabel("SUBJECT", self)
        self.subjectFilterLabel.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.subjectFilterLabel.setMinimumWidth(64)

        self.subjectFilter = QComboBox()
        self.subjectFilter.setPlaceholderText("과목 선택")
        self._apply_combo_item_height(self.subjectFilter)

        self.examFilter.currentIndexChanged.connect(lambda *_: self._on_exam_filter_changed())
        self.subjectFilter.currentIndexChanged.connect(lambda *_: self.load_data())
        
        self.searchBox = LineEdit()
        self.searchBox.setPlaceholderText("태그/문항/선지 검색...")
        self.searchBox.returnPressed.connect(self.load_data)
        
        self.btnRefresh = PrimaryPushButton("조회", self)
        self.btnRefresh.clicked.connect(self.load_data)

        self.btnAddManual = PrimaryPushButton("문제 추가", self)
        self.btnAddManual.setToolTip("개인이 만든 문제를 수동으로 추가")
        self.btnAddManual.clicked.connect(self.add_manual_question)

        self.btnValidate = PrimaryPushButton("오류 검사", self)
        self.btnValidate.clicked.connect(self.load_validation_results)

        self.btnDeleteSelected = PushButton("선택 삭제", self)
        self.btnDeleteSelected.clicked.connect(self.delete_selected_questions)

        self.headerLayout.addWidget(self.titleLabel)
        self.headerLayout.addStretch(1)
        self.headerLayout.addWidget(self.examFilterLabel)
        self.headerLayout.addWidget(self.examFilter)
        self.headerLayout.addWidget(self.subjectFilterLabel)
        self.headerLayout.addWidget(self.subjectFilter)
        self.headerLayout.addWidget(self.searchBox)
        self.headerLayout.addWidget(self.btnAddManual)
        self.headerLayout.addWidget(self.btnRefresh)
        self.headerLayout.addWidget(self.btnValidate)
        self.headerLayout.addWidget(self.btnDeleteSelected)

        # Table
        self.table = TableWidget(self)
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["선택", "ID", "정보", "문제", "태그", "관리"])
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 54)
        self.table.setColumnWidth(1, 70)
        self.table.setColumnWidth(4, 180)
        self.table.setColumnWidth(5, 216)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        # Layout
        self.vBoxLayout.addLayout(self.headerLayout)
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

    def _apply_combo_item_height(self, combo, height=44):
        view = combo.view()
        view.setStyleSheet(f"QListView::item {{ height: {height}px; }}")

    def toggle_explanation_sidecar(self):
        self.set_explanation_sidecar_expanded(not self.explanation_sidecar_expanded)

    def set_explanation_sidecar_expanded(self, expanded: bool):
        self.explanation_sidecar_expanded = bool(expanded)
        self.explanationSidecar.setVisible(self.explanation_sidecar_expanded)
        self.explanationToggleButton.setText(">" if self.explanation_sidecar_expanded else "<")
        self.explanationToggleButton.setToolTip(
            "해설 패널 접기" if self.explanation_sidecar_expanded else "해설 패널 펼치기"
        )
        self.explanationDock.setMaximumWidth(464 if self.explanation_sidecar_expanded else 34)

    def _load_exam_filters(self):
        current_code = self.examFilter.currentData()
        self.examFilter.blockSignals(True)
        self.examFilter.clear()
        self.examFilter.addItem("전체 시험", None)
        for exam in self.repo.get_filter_options().get('exams', []):
            self.examFilter.addItem(
                f"{exam['name']} ({exam['code']})",
                exam['code']
            )

        if current_code is not None:
            index = self.examFilter.findData(current_code)
            if index >= 0:
                self.examFilter.setCurrentIndex(index)
        self.examFilter.blockSignals(False)

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
        code = subject.get('code') or ''
        if not code or code.startswith(('custom_', 'auto_')) or code == name:
            return name
        return f"{name} ({code})"
        
    def load_data(self):
        self.validation_mode = False
        self.table.setHorizontalHeaderLabels(["선택", "ID", "정보", "문제", "태그", "관리"])
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
        q = self.repo.get_question(question_id)
        if not q:
            return

        dialog = QuestionEditor(
            self.window(),
            q,
            subject_options=self.repo.get_subject_options(q.get('exam_code'))
        )
        if dialog.exec():
            new_data = dialog.get_data()
            if self.repo.update_question(question_id, new_data):
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
            else:
                InfoBar.error(
                    title='오류',
                    content="DB 업데이트 실패",
                    parent=self
                )

    def add_manual_question(self):
        dialog = QuestionEditor(
            self.window(),
            self.repo.get_manual_question_template(),
            subject_options=self.repo.get_manual_subject_options(),
            create_mode=True,
        )
        if not dialog.exec():
            return

        data = dialog.get_data()
        question_id = self.repo.create_manual_question(data)
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
                content="같은 연도/회차/문제번호가 이미 있거나 DB 저장에 실패했습니다.",
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
        return (
            f"{prefix}{question['year']}-{question['session']} "
            f"{question['subject_name']} {question['question_number']}번"
        )

    def _format_question_preview(self, question):
        question_text = question.get('question_text') or ''
        text = question_text[:50] + "..." if len(question_text) > 50 else question_text
        return f"[공통] {text}" if question.get('group_id') is not None else text

    def _make_action_widget(self, question_id):
        widget = QWidget(self)
        widget.setMinimumWidth(204)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        edit_btn = PrimaryPushButton("수정", self)
        edit_btn.setFixedSize(64, 30)
        edit_btn.clicked.connect(lambda checked, q_id=question_id: self.open_editor(q_id))

        delete_btn = PushButton("삭제", self)
        delete_btn.setFixedSize(64, 30)
        delete_btn.clicked.connect(lambda checked, q_id=question_id: self.delete_question(q_id))

        explanation_btn = PushButton("해설", self)
        explanation_btn.setFixedSize(64, 30)
        explanation_btn.clicked.connect(lambda checked, q_id=question_id: self.open_explanation(q_id))

        layout.addWidget(edit_btn)
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
        self.set_explanation_sidecar_expanded(True)

    def save_current_explanation(self):
        if not self.current_explanation_question_id:
            InfoBar.warning(title='선택 없음', content="해설을 저장할 문제를 먼저 선택하세요.", parent=self)
            return

        if self.repo.update_question_explanation(
            self.current_explanation_question_id,
            self.explanationEditor.toPlainText(),
        ):
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
                ids.append(int(checkbox.property("question_id")))
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

        if self.repo.delete_question(question_id):
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
                content="DB 삭제 실패",
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

        deleted_count = self.repo.delete_questions(question_ids)
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
