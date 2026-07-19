from PyQt5.QtWidgets import (
    QApplication, QDialog, QFileDialog, QGridLayout, QHBoxLayout, QScrollArea,
    QMessageBox, QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QTextCharFormat, QTextCursor
from qfluentwidgets import (
    SubtitleLabel, LineEdit, TextEdit, BodyLabel, PushButton,
    ImageLabel, ComboBox, PrimaryPushButton
)
from pathlib import Path
import uuid
import re
import json

from ...runtime_paths import get_clipboard_image_dir
from ...parser.formatting import (
    existing_latex_spans,
    merge_spans,
    normalize_latex_text,
    normalize_private_math_glyphs,
)
from ...parser.patterns import NUMBER_TO_CHOICE_SYMBOL
from ...parser.question import ALL_CHOICES_CORRECT
from ...parser.table_format import (
    merge_format_spans,
    parse_format_payload,
    resolve_table_anchor,
    serialize_format_payload,
)
from ...parser.table_structure import normalize_rectangular_table
from ...parser.view_table import (
    add_one_cell_table,
    promote_view_block,
    remove_table_and_restore,
)
from ...choice_markers import (
    DEFAULT_CHOICE_MARKER_STYLE,
    choice_marker,
    normalize_choice_marker_style,
)
from ..table_editor import TableEditorDialog
from ..table_preview import TablePreviewCard


MIN_CHOICE_COUNT = 4
MAX_CHOICE_COUNT = 10
QUESTION_TYPE_MULTIPLE_CHOICE = "multiple_choice"
QUESTION_TYPE_DESCRIPTIVE = "descriptive"


class QuestionEditor(QDialog):
    """문제 전체 수정 다이얼로그"""
    
    def __init__(
        self,
        parent=None,
        question_data=None,
        subject_options=None,
        create_mode=False,
        choice_marker_style=DEFAULT_CHOICE_MARKER_STYLE,
    ):
        super().__init__(parent)
        self.create_mode = bool(create_mode)
        self.choice_marker_style = normalize_choice_marker_style(choice_marker_style)
        self.setModal(True)
        self.question_data = question_data or {}
        promoted_text, promoted_format_json, promoted = promote_view_block(
            self.question_data.get('question_text', ''),
            self.question_data.get('question_format_json'),
        )
        if promoted:
            self.question_data['question_text'] = promoted_text
            self.question_data['question_format_json'] = promoted_format_json
        self.editor_title = (
            self.question_data.get('editor_title')
            or ("개인 제작 문제 추가" if self.create_mode else "문제 수정")
        )
        self.setWindowTitle(self.editor_title)
        self.subject_options = subject_options or []
        self._normalizing_private_glyphs = False
        self.explanation_sidecar_expanded = False
        self.sharedPassage = (
            self.question_data.get('shared_passage')
            or self.question_data.get('group_shared_text')
        )
        self.titleLabel = SubtitleLabel(
            self.editor_title,
            self,
        )

        self.rootLayout = QVBoxLayout(self)
        self.rootLayout.setContentsMargins(18, 16, 18, 14)
        self.rootLayout.setSpacing(12)

        self.scrollArea = QScrollArea(self)
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.contentWidget = QWidget(self.scrollArea)
        self.viewLayout = QVBoxLayout(self.contentWidget)
        self.viewLayout.setContentsMargins(0, 0, 0, 0)
        self.viewLayout.setSpacing(10)
        self.scrollArea.setWidget(self.contentWidget)

        info = self._format_question_info()
        self.infoLabel = BodyLabel(info, self)

        self.metadataWidget = QWidget(self)
        self.metadataLayout = QGridLayout(self.metadataWidget)
        self.metadataLayout.setContentsMargins(0, 0, 0, 0)
        self.metadataLayout.setHorizontalSpacing(14)
        self.metadataLayout.setVerticalSpacing(6)
        self.yearInput = QSpinBox(self)
        self.yearInput.setRange(2000, 2100)
        self.yearInput.setValue(int(self.question_data.get('year') or 2024))
        self._apply_input_height(self.yearInput)
        self.sessionInput = QSpinBox(self)
        self.sessionInput.setRange(1, 9)
        self.sessionInput.setValue(int(self.question_data.get('session') or 1))
        self._apply_input_height(self.sessionInput)
        self.questionNumberInput = QSpinBox(self)
        self.questionNumberInput.setRange(1, 200)
        self.questionNumberInput.setValue(int(self.question_data.get('question_number') or 1))
        self._apply_input_height(self.questionNumberInput)
        self.subjectCombo = ComboBox(self)
        self._apply_input_height(self.subjectCombo)
        self._init_subjects()
        self.questionTypeCombo = ComboBox(self)
        self._apply_input_height(self.questionTypeCombo)
        self._init_question_types()
        self.questionTypeCombo.currentIndexChanged.connect(
            lambda *_: self._apply_question_type_visibility()
        )
        self._add_metadata_field("연도", self.yearInput, 0, 0)
        self._add_metadata_field("회차", self.sessionInput, 0, 1)
        self._add_metadata_field("문제번호", self.questionNumberInput, 0, 2)
        self._add_metadata_field("과목", self.subjectCombo, 0, 3, stretch=2)
        self._add_metadata_field("유형", self.questionTypeCombo, 0, 4)

        self.sharedPassageText = None
        if self.sharedPassage:
            self.sharedPassageText = TextEdit(self)
            self.sharedPassageText.setReadOnly(True)
            self.sharedPassageText.setPlainText(self._display_text(self.sharedPassage))
            self.sharedPassageText.setMinimumHeight(88)
            self.sharedPassageText.setMaximumHeight(120)
            self.sharedPassageText.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )
        
        self.questionText = TextEdit(self)
        self.questionText.setPlaceholderText("발문")
        self.questionText.setPlainText(
            self._display_text(self.question_data.get('question_text', ''))
        )
        self.questionText.setMinimumHeight(112)
        self.questionText.setMaximumHeight(132)
        self.questionText.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._apply_question_format_json(self.question_data.get('question_format_json'))
        self.questionText.textChanged.connect(self._normalize_question_text_input)

        self.questionToolbar = QWidget(self)
        self.questionToolbarLayout = QHBoxLayout(self.questionToolbar)
        self.questionToolbarLayout.setContentsMargins(0, 0, 0, 0)
        self.questionToolbarLayout.setSpacing(8)
        self.btnQuestionUnderline = PushButton("U", self)
        self.btnQuestionUnderline.setToolTip("선택한 발문에 밑줄")
        self.btnQuestionUnderline.setFixedWidth(44)
        self._apply_input_height(self.btnQuestionUnderline, 34)
        self.btnQuestionUnderline.clicked.connect(self._toggle_question_underline)
        self.questionToolbarLayout.addWidget(self.btnQuestionUnderline)
        self.btnQuestionOverline = PushButton("O̅", self)
        self.btnQuestionOverline.setToolTip("선택한 발문을 overline 수식으로 변환")
        self.btnQuestionOverline.setFixedWidth(44)
        self._apply_input_height(self.btnQuestionOverline, 34)
        self.btnQuestionOverline.clicked.connect(self._wrap_question_selection_as_overline)
        self.questionToolbarLayout.addWidget(self.btnQuestionOverline)
        self.btnAddQuestionTable = PushButton("발문 표 추가", self)
        self.btnAddQuestionTable.setToolTip(
            "선택한 발문을 한 셀 표로 옮기거나 커서 위치에 빈 <보기> 표를 추가"
        )
        self._apply_input_height(self.btnAddQuestionTable, 34)
        self.btnAddQuestionTable.clicked.connect(self._add_question_table)
        self.questionToolbarLayout.addWidget(self.btnAddQuestionTable)
        self.questionToolbarLayout.addStretch(1)

        self.answerCombo = ComboBox(self)
        self.choice_count = self._initial_choice_count()
        self.choiceInputs = {}
        self.choiceRows = {}
        self.choiceLabels = {}
        self.choiceOverlineButtons = {}
        self.choiceImagePaths = {
            number: self._choice_image_path(number)
            for number in self._choice_numbers()
        }
        self.choiceImageLabels = {}
        self.choiceImagePreviews = {}
        self.choiceClearImageButtons = {}
        self._init_answer_and_choices()

        self.choiceWidget = QWidget(self)
        self.choiceLayout = QVBoxLayout(self.choiceWidget)
        self.choiceLayout.setContentsMargins(0, 2, 0, 2)
        self.choiceLayout.setSpacing(8)
        self.choiceWidget.setMinimumHeight(248)
        self.choiceWidget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        for number in self._choice_numbers():
            self._add_choice_row(number)
        self.choiceControlWidget = QWidget(self)
        choiceControlLayout = QHBoxLayout(self.choiceControlWidget)
        choiceControlLayout.setContentsMargins(0, 0, 0, 0)
        choiceControlLayout.setSpacing(8)
        self.btnAddChoice = PushButton("선지 추가", self)
        self.btnAddChoice.setToolTip(f"최대 {MAX_CHOICE_COUNT}개까지 선지를 추가")
        self._apply_input_height(self.btnAddChoice)
        self.btnAddChoice.clicked.connect(self._add_choice)
        self.btnRemoveChoice = PushButton("마지막 선지 삭제", self)
        self.btnRemoveChoice.setToolTip(f"{MIN_CHOICE_COUNT}개 미만으로는 줄일 수 없습니다.")
        self._apply_input_height(self.btnRemoveChoice)
        self.btnRemoveChoice.clicked.connect(self._remove_last_choice)
        choiceControlLayout.addStretch(1)
        choiceControlLayout.addWidget(self.btnAddChoice)
        choiceControlLayout.addWidget(self.btnRemoveChoice)
        self.choiceLayout.addWidget(self.choiceControlWidget)
        self._update_choice_control_state()

        self.modelAnswerText = TextEdit(self)
        self.modelAnswerText.setPlaceholderText("모범답안")
        self.modelAnswerText.setPlainText(
            self._display_text(self.question_data.get('model_answer', ''))
        )
        self.modelAnswerText.setMinimumHeight(128)
        self.modelAnswerText.setMaximumHeight(180)
        self.modelAnswerText.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        self.tagsInput = LineEdit(self)
        self.tagsInput.setPlaceholderText("해시태그 (쉼표로 구분)")
        self.tagsInput.setText(self.question_data.get('tags') or '')
        self._apply_input_height(self.tagsInput)
        
        # Image
        self.imagePath = self.question_data.get('image_path')
        self.imageWidget = QWidget(self)
        self.imageLayout = QHBoxLayout(self.imageWidget)
        self.imageLayout.setContentsMargins(0, 0, 0, 0)
        self.imageLayout.setSpacing(12)
        self.imageLabel = ImageLabel(self)
        self.imageLabel.setBorderRadius(8, 8, 8, 8)
        self.imageLabel.setScaledContents(True)
        self.imageStatusLabel = BodyLabel("", self)
        self.imageStatusLabel.setWordWrap(True)
        self.btnImage = PushButton("이미지 추가" if self.create_mode else "이미지 변경", self)
        self.btnPasteImage = PushButton("붙여넣기", self)
        self.btnCopyImage = PushButton("클립보드에 복사", self)
        self.btnClearImage = PushButton("삭제", self)
        for button, width in (
            (self.btnImage, 120),
            (self.btnPasteImage, 100),
            (self.btnCopyImage, 140),
            (self.btnClearImage, 80),
        ):
            self._apply_input_height(button)
            button.setFixedWidth(width)

        self.btnImage.clicked.connect(self._select_image)
        self.btnPasteImage.clicked.connect(self._paste_image)
        self.btnCopyImage.clicked.connect(self._copy_image_to_clipboard)
        self.btnClearImage.setToolTip("문제 이미지 경로 삭제")
        self.btnClearImage.clicked.connect(self._clear_image)

        self.imageButtonBar = QWidget(self)
        self.imageButtonLayout = QHBoxLayout(self.imageButtonBar)
        self.imageButtonLayout.setContentsMargins(0, 0, 0, 0)
        self.imageButtonLayout.setSpacing(8)
        self.imageButtonLayout.addWidget(self.btnImage)
        self.imageButtonLayout.addWidget(self.btnPasteImage)
        self.imageButtonLayout.addWidget(self.btnCopyImage)
        self.imageButtonLayout.addWidget(self.btnClearImage)

        imageControls = QWidget(self)
        imageControlsLayout = QVBoxLayout(imageControls)
        imageControlsLayout.setContentsMargins(0, 0, 0, 0)
        imageControlsLayout.setSpacing(8)
        imageControlsLayout.addWidget(self.imageStatusLabel)
        imageControlsLayout.addWidget(self.imageButtonBar)
        imageControlsLayout.addStretch(1)

        self.imageLayout.addWidget(self.imageLabel)
        self.imageLayout.addWidget(imageControls, 1)
        self.imageWidget.setMinimumHeight(138)
        self.imageWidget.setMaximumHeight(156)
        self.imageWidget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._set_image_preview(self.imagePath)

        self._init_table_cards()

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.infoLabel)
        self.viewLayout.addWidget(BodyLabel("기본 정보", self))
        self.viewLayout.addWidget(self.metadataWidget)
        if self.sharedPassageText:
            self.viewLayout.addWidget(BodyLabel("공통지문", self))
            self.viewLayout.addWidget(self.sharedPassageText)
        self.questionSectionLabel = BodyLabel("발문", self)
        self.choiceSectionLabel = BodyLabel("선지", self)
        self.answerSectionLabel = BodyLabel("정답", self)
        self.modelAnswerSectionLabel = BodyLabel("모범답안", self)
        self.tagsSectionLabel = BodyLabel("해시태그", self)
        self.imageSectionLabel = BodyLabel("이미지", self)

        self.viewLayout.addWidget(self.questionSectionLabel)
        self.viewLayout.addWidget(self.questionToolbar)
        self.viewLayout.addWidget(self.questionText)
        self.viewLayout.addWidget(self.tableSectionLabel)
        self.viewLayout.addWidget(self.tableCardsWidget)
        self.viewLayout.addWidget(self.choiceSectionLabel)
        self.viewLayout.addWidget(self.choiceWidget)
        self.viewLayout.addWidget(self.answerSectionLabel)
        self._apply_input_height(self.answerCombo)
        self.viewLayout.addWidget(self.answerCombo)
        self.viewLayout.addWidget(self.modelAnswerSectionLabel)
        self.viewLayout.addWidget(self.modelAnswerText)
        self.viewLayout.addWidget(self.tagsSectionLabel)
        self.viewLayout.addWidget(self.tagsInput)
        self.viewLayout.addWidget(self.imageSectionLabel)
        self.viewLayout.addWidget(self.imageWidget)
        self.viewLayout.addStretch(1)

        self.editorBody = QWidget(self)
        self.editorBodyLayout = QHBoxLayout(self.editorBody)
        self.editorBodyLayout.setContentsMargins(0, 0, 0, 0)
        self.editorBodyLayout.setSpacing(4)
        self.editorBodyLayout.addWidget(self.scrollArea, 1)
        self._init_explanation_sidecar()
        self.editorBodyLayout.addWidget(self.explanationDock, 0)
        self.rootLayout.addWidget(self.editorBody, 1)

        self.buttonBar = QWidget(self)
        self.buttonBar.setMinimumHeight(62)
        buttonLayout = QHBoxLayout(self.buttonBar)
        buttonLayout.setContentsMargins(0, 8, 0, 0)
        buttonLayout.setSpacing(12)
        self.explanationButton = PushButton("해설", self)
        self.saveButton = PrimaryPushButton("저장", self)
        self.cancelButton = PushButton("취소", self)
        self._apply_input_height(self.explanationButton, 42)
        self._apply_input_height(self.saveButton, 42)
        self._apply_input_height(self.cancelButton, 42)
        buttonLayout.addWidget(self.explanationButton)
        buttonLayout.addStretch(1)
        buttonLayout.addWidget(self.saveButton, 1)
        buttonLayout.addWidget(self.cancelButton, 1)
        self.explanationButton.clicked.connect(
            lambda: self.set_explanation_sidecar_expanded(True)
        )
        self.saveButton.clicked.connect(self.accept)
        self.cancelButton.clicked.connect(self.reject)
        self.rootLayout.addWidget(self.buttonBar, 0)

        self._apply_question_type_visibility()
        self.setMinimumSize(960, 780)
        self.resize(1060, 820)

    def _init_table_cards(self):
        """Create the dynamic card container used by all stored tables."""
        self.tableSectionLabel = BodyLabel("표", self)
        self.tableCardsWidget = QWidget(self)
        self.tableCardsLayout = QVBoxLayout(self.tableCardsWidget)
        self.tableCardsLayout.setContentsMargins(0, 0, 0, 0)
        self.tableCardsLayout.setSpacing(10)
        self.tablePreviewCards = {}
        self.tableRenderModeCombos = {}
        self._rebuild_table_cards()

    def _clear_table_cards(self):
        while self.tableCardsLayout.count():
            item = self.tableCardsLayout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _rebuild_table_cards(self):
        """Recreate table controls after add, edit, or deletion."""
        self._clear_table_cards()
        self.tablePreviewCards = {}
        self.tableRenderModeCombos = {}

        owners = [("question", self.question_data.get('question_format_json'))]
        for choice in self.question_data.get('choices') or []:
            number = int(choice.get('choice_number') or 0)
            owners.append((
                f"choice:{number}",
                choice.get('choice_format_json') or choice.get('format_json'),
            ))

        for owner, format_json in owners:
            payload = parse_format_payload(format_json)
            for table in payload.get('tables', []):
                table_id = str(table['id'])
                card = TablePreviewCard(
                    owner,
                    table,
                    self.tableCardsWidget,
                )
                card.editRequested.connect(self._edit_table_structure)
                card.sourceRequested.connect(self._compare_table_source)
                card.deleteRequested.connect(self._delete_table)
                card.renderModeChanged.connect(self._set_table_render_mode)
                self.tableCardsLayout.addWidget(card)
                key = (owner, table_id)
                self.tablePreviewCards[key] = card
                self.tableRenderModeCombos[key] = card.mode_combo

        self.tableSectionLabel.setVisible(True)
        self.tableCardsWidget.setVisible(bool(self.tablePreviewCards))

    def _owner_format_payload(self, owner):
        if owner == 'question':
            return parse_format_payload(self.question_data.get('question_format_json'))
        number = int(owner.split(':', 1)[1])
        for choice in self.question_data.get('choices') or []:
            if int(choice.get('choice_number') or 0) == number:
                return parse_format_payload(
                    choice.get('choice_format_json') or choice.get('format_json')
                )
        return parse_format_payload(None)

    def _store_owner_format_payload(self, owner, payload):
        encoded = serialize_format_payload(payload)
        if owner == 'question':
            self.question_data['question_format_json'] = encoded
            return
        number = int(owner.split(':', 1)[1])
        for choice in self.question_data.get('choices') or []:
            if int(choice.get('choice_number') or 0) == number:
                choice['choice_format_json'] = encoded
                return

    def _owner_text(self, owner):
        if owner == 'question':
            return self.questionText.toPlainText()
        number = int(owner.split(':', 1)[1])
        field = self.choiceInputs.get(number)
        return field.text() if field is not None else ''

    def _set_owner_text(self, owner, text):
        if owner == 'question':
            self.questionText.setPlainText(str(text or ''))
            return
        number = int(owner.split(':', 1)[1])
        field = self.choiceInputs.get(number)
        if field is not None:
            field.setText(str(text or ''))

    def _add_question_table(self):
        cursor = self.questionText.textCursor()
        start = cursor.selectionStart()
        if cursor.hasSelection():
            cell_text = cursor.selectedText().replace('\u2029', '\n')
            cursor.removeSelectedText()
            self.questionText.setTextCursor(cursor)
        else:
            cell_text = '<보기>\n'
        owner_text = self.questionText.toPlainText()
        self.question_data['question_format_json'] = add_one_cell_table(
            owner_text,
            self.question_data.get('question_format_json'),
            cell_text,
            start,
        )
        self._rebuild_table_cards()

    def _delete_table(self, owner, table_id, confirm=True):
        if confirm:
            answer = QMessageBox.question(
                self,
                "표 삭제",
                "표를 삭제하고 셀 내용을 원래 위치의 텍스트로 복원할까요?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
        restored, encoded, removed = remove_table_and_restore(
            self._owner_text(owner),
            serialize_format_payload(self._owner_format_payload(owner)),
            table_id,
        )
        if not removed:
            return False
        self._set_owner_text(owner, restored)
        self._store_owner_format_payload(owner, parse_format_payload(encoded))
        self._rebuild_table_cards()
        return True

    def _set_table_render_mode(self, owner, table_id, mode):
        payload = self._owner_format_payload(owner)
        for table in payload.get('tables', []):
            if table.get('id') == table_id:
                table['render_mode'] = mode if mode in {'auto', 'image', 'native'} else 'auto'
                break
        self._store_owner_format_payload(owner, payload)

    def _find_owner_table(self, owner, table_id):
        payload = self._owner_format_payload(owner)
        return next(
            (table for table in payload.get('tables', []) if table.get('id') == table_id),
            None,
        )

    def _replace_table_spec(self, owner, table_id, replacement):
        payload = self._owner_format_payload(owner)
        editable_keys = {
            'rows',
            'cells',
            'column_widths',
            'row_heights',
            'layout',
        }
        for index, table in enumerate(payload.get('tables', [])):
            if table.get('id') != table_id:
                continue
            merged = dict(table)
            for key in editable_keys:
                if key in replacement:
                    merged[key] = replacement[key]
            merged['id'] = table_id
            payload['tables'][index] = normalize_rectangular_table(merged)
            self._store_owner_format_payload(owner, payload)
            self._rebuild_table_cards()
            return True
        return False

    def _open_table_editor(self, owner, table_id, *, show_source=False):
        table = self._find_owner_table(owner, table_id)
        if not table:
            return
        dialog = TableEditorDialog(
            table,
            self,
            show_source=show_source,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        self._replace_table_spec(owner, table_id, dialog.result_table_spec())

    def _edit_table_structure(self, owner, table_id):
        self._open_table_editor(owner, table_id, show_source=False)

    def _compare_table_source(self, owner, table_id):
        self._open_table_editor(owner, table_id, show_source=True)

    def _update_table_rows(self, owner, table_id, rows):
        table = self._find_owner_table(owner, table_id)
        if not table:
            return False
        cleaned_rows = [
            [str(cell or '') for cell in row]
            for row in rows or []
            if isinstance(row, (list, tuple))
        ]
        replacement = dict(table)
        replacement['rows'] = cleaned_rows
        replacement['cells'] = []
        return self._replace_table_spec(owner, table_id, replacement)

    def accept(self):
        data = self.get_data()
        if not str(data.get('question_text') or '').strip():
            QMessageBox.warning(self, "입력 필요", "발문을 입력하세요.")
            return
        if not data.get('subject_code'):
            QMessageBox.warning(self, "입력 필요", "과목을 선택하세요.")
            return
        if data.get('question_type') == QUESTION_TYPE_DESCRIPTIVE:
            if not str(data.get('model_answer') or '').strip():
                QMessageBox.warning(self, "입력 필요", "모범답안을 입력하세요.")
                return
            super().accept()
            return

        choices = data.get('choices', [])
        if len(choices) < MIN_CHOICE_COUNT:
            QMessageBox.warning(
                self,
                "입력 필요",
                f"선지는 최소 {MIN_CHOICE_COUNT}개 이상 필요합니다.",
            )
            return
        missing_choices = [
            str(choice.get('choice_number'))
            for choice in choices
            if not str(choice.get('choice_text') or '').strip()
            and not choice.get('choice_image_path')
        ]
        if missing_choices:
            QMessageBox.warning(
                self,
                "입력 필요",
                f"{', '.join(missing_choices)}번 선지를 입력하거나 이미지를 지정하세요.",
            )
            return
        choice_numbers = {choice.get('choice_number') for choice in choices}
        if data.get('correct_answer') not in choice_numbers:
            QMessageBox.warning(self, "입력 필요", "정답 번호가 선지 목록에 없습니다.")
            return
        super().accept()

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
        self.explanationSidecar.setObjectName("EditorExplanationSidecar")
        self.explanationSidecar.setMinimumWidth(340)
        self.explanationSidecar.setMaximumWidth(410)
        self.explanationSidecar.setStyleSheet(
            "#EditorExplanationSidecar { border-left: 1px solid rgba(0, 0, 0, 24); }"
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

        self.explanationEditor = TextEdit(self.explanationSidecar)
        self.explanationEditor.setPlaceholderText("이 문제의 상세 해설을 입력하세요.")
        self.explanationEditor.setPlainText(self.question_data.get('explanation') or '')
        self.explanationEditor.setMinimumHeight(420)
        sideLayout.addWidget(self.explanationEditor, 1)

        self.explanationDockLayout.addWidget(
            self.explanationToggleButton,
            0,
            Qt.AlignmentFlag.AlignTop,
        )
        self.explanationDockLayout.addWidget(self.explanationSidecar)
        self.set_explanation_sidecar_expanded(bool(self.question_data.get('explanation')))

    def toggle_explanation_sidecar(self):
        self.set_explanation_sidecar_expanded(not self.explanation_sidecar_expanded)

    def set_explanation_sidecar_expanded(self, expanded: bool):
        self.explanation_sidecar_expanded = bool(expanded)
        self.explanationSidecar.setVisible(self.explanation_sidecar_expanded)
        self.explanationToggleButton.setText(">" if self.explanation_sidecar_expanded else "<")
        self.explanationToggleButton.setToolTip(
            "해설 패널 접기" if self.explanation_sidecar_expanded else "해설 패널 펼치기"
        )
        self.explanationDock.setMaximumWidth(444 if self.explanation_sidecar_expanded else 34)

    def _add_metadata_field(self, label, field, row, column, stretch=1):
        label_widget = BodyLabel(label, self)
        label_widget.setFixedHeight(22)
        field.setMinimumWidth(120 * stretch)
        self.metadataLayout.addWidget(label_widget, row * 2, column)
        self.metadataLayout.addWidget(field, row * 2 + 1, column)
        self.metadataLayout.setColumnStretch(column, stretch)

    def _make_choice_row(self, symbol, field, number):
        row = QWidget(self)
        row.setMinimumHeight(56)
        row.setMaximumHeight(62)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        label = BodyLabel(symbol, self)
        label.setFixedSize(40, 38)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_preview = ImageLabel(self)
        image_preview.setBorderRadius(6, 6, 6, 6)
        image_preview.setScaledContents(True)
        image_preview.setFixedSize(72, 48)
        image_label = BodyLabel("", self)
        image_label.setFixedWidth(74)
        image_label.setWordWrap(False)
        overline_button = PushButton("O̅", self)
        overline_button.setToolTip(f"{symbol} 선지 선택 텍스트를 overline 수식으로 변환")
        self._apply_input_height(overline_button)
        overline_button.setFixedWidth(48)
        overline_button.clicked.connect(lambda checked=False, n=number: self._wrap_choice_selection_as_overline(n))
        image_button = PushButton("이미지", self)
        self._apply_input_height(image_button)
        image_button.setFixedWidth(84)
        image_button.clicked.connect(lambda checked=False, n=number: self._select_choice_image(n))
        paste_button = PushButton("붙여넣기", self)
        self._apply_input_height(paste_button)
        paste_button.setFixedWidth(92)
        paste_button.clicked.connect(lambda checked=False, n=number: self._paste_choice_image(n))
        clear_button = PushButton("삭제", self)
        clear_button.setToolTip(f"{symbol} 선지 이미지 경로 삭제")
        self._apply_input_height(clear_button)
        clear_button.setFixedWidth(64)
        clear_button.clicked.connect(lambda checked=False, n=number: self._clear_choice_image(n))
        self.choiceLabels[number] = label
        self.choiceOverlineButtons[number] = overline_button
        self.choiceImagePreviews[number] = image_preview
        self.choiceImageLabels[number] = image_label
        self.choiceClearImageButtons[number] = clear_button
        self._set_choice_image_preview(number)

        layout.addWidget(label)
        layout.addWidget(field, 1)
        layout.addWidget(overline_button)
        layout.addWidget(image_preview)
        layout.addWidget(image_label)
        layout.addWidget(image_button)
        layout.addWidget(paste_button)
        layout.addWidget(clear_button)
        return row

    def _choice_numbers(self):
        return range(1, self.choice_count + 1)

    def _initial_choice_count(self):
        numbers = []
        for choice in self.question_data.get('choices') or []:
            try:
                numbers.append(int(choice.get('choice_number') or choice.get('number')))
            except (TypeError, ValueError, AttributeError):
                continue
        try:
            correct_answer = int(self.question_data.get('correct_answer') or 0)
        except (TypeError, ValueError):
            correct_answer = 0
        if correct_answer:
            numbers.append(correct_answer)
        count = max(numbers or [MIN_CHOICE_COUNT])
        return max(MIN_CHOICE_COUNT, min(MAX_CHOICE_COUNT, count))

    def _choice_symbol(self, number):
        return choice_marker(number, self.choice_marker_style, fallback=str(number))

    def _stored_choice_symbol(self, number):
        for choice in self.question_data.get('choices') or []:
            try:
                choice_number = int(
                    choice.get('choice_number') or choice.get('number') or 0
                )
            except (TypeError, ValueError, AttributeError):
                continue
            if choice_number == int(number):
                return choice.get('choice_symbol') or choice.get('symbol') or (
                    NUMBER_TO_CHOICE_SYMBOL.get(number, str(number))
                )
        return NUMBER_TO_CHOICE_SYMBOL.get(number, str(number))

    def set_choice_marker_style(self, style):
        self.choice_marker_style = normalize_choice_marker_style(style)
        for number in self._choice_numbers():
            symbol = self._choice_symbol(number)
            label = self.choiceLabels.get(number)
            if label is not None:
                label.setText(symbol)
            field = self.choiceInputs.get(number)
            if field is not None:
                field.setPlaceholderText(f"{symbol} 선지 내용")
            overline_button = self.choiceOverlineButtons.get(number)
            if overline_button is not None:
                overline_button.setToolTip(
                    f"{symbol} 선지 선택 텍스트를 overline 수식으로 변환"
                )
            clear_button = self.choiceClearImageButtons.get(number)
            if clear_button is not None:
                clear_button.setToolTip(f"{symbol} 선지 이미지 경로 삭제")
            answer_index = self.answerCombo.findData(number)
            if answer_index >= 0:
                self.answerCombo.setItemText(answer_index, f"{symbol} ({number}번)")

    def _add_choice_row(self, number):
        symbol = self._choice_symbol(number)
        field = LineEdit(self)
        field.setPlaceholderText(f"{symbol} 선지 내용")
        field.setText(self._choice_text(number))
        self._apply_input_height(field)
        self.choiceInputs[number] = field
        field.textChanged.connect(
            lambda _text, n=number: self._normalize_choice_text_input(n)
        )
        row = self._make_choice_row(symbol, field, number)
        self.choiceRows[number] = row
        insert_index = self.choiceLayout.count()
        if hasattr(self, 'choiceControlWidget'):
            insert_index = max(0, insert_index - 1)
        self.choiceLayout.insertWidget(insert_index, row)

    def _add_answer_option(self, number):
        symbol = self._choice_symbol(number)
        self.answerCombo.addItem(f"{symbol} ({number}번)", userData=number)

    def _remove_answer_option(self, number):
        index = self.answerCombo.findData(number)
        if index >= 0:
            self.answerCombo.removeItem(index)

    def _add_choice(self):
        if self.choice_count >= MAX_CHOICE_COUNT:
            return
        self.choice_count += 1
        self.choiceImagePaths[self.choice_count] = None
        self._add_choice_row(self.choice_count)
        self._add_answer_option(self.choice_count)
        self._update_choice_control_state()

    def _remove_last_choice(self):
        if self.choice_count <= MIN_CHOICE_COUNT:
            return
        number = self.choice_count
        if self.answerCombo.currentData() == number:
            previous_index = self.answerCombo.findData(number - 1)
            self.answerCombo.setCurrentIndex(previous_index if previous_index >= 0 else 0)
        self._remove_answer_option(number)
        row = self.choiceRows.pop(number, None)
        if row is not None:
            self.choiceLayout.removeWidget(row)
            row.deleteLater()
        self.choiceInputs.pop(number, None)
        self.choiceLabels.pop(number, None)
        self.choiceOverlineButtons.pop(number, None)
        self.choiceImagePaths.pop(number, None)
        self.choiceImageLabels.pop(number, None)
        self.choiceImagePreviews.pop(number, None)
        self.choiceClearImageButtons.pop(number, None)
        self.choice_count -= 1
        self._update_choice_control_state()

    def _update_choice_control_state(self):
        if hasattr(self, 'btnAddChoice'):
            self.btnAddChoice.setEnabled(self.choice_count < MAX_CHOICE_COUNT)
        if hasattr(self, 'btnRemoveChoice'):
            self.btnRemoveChoice.setEnabled(self.choice_count > MIN_CHOICE_COUNT)

    def _apply_input_height(self, widget, height=38):
        widget.setMinimumHeight(height)
        if hasattr(widget, "setFixedHeight"):
            widget.setFixedHeight(height)

    def _set_image_preview(self, image_path):
        can_copy = self._can_copy_image(image_path)
        if can_copy:
            self.imageLabel.setVisible(True)
            self.imageLabel.setImage(image_path)
            self.imageLabel.setFixedSize(180, 110)
            self.imageStatusLabel.setText(self._format_image_status(image_path))
        else:
            self.imageLabel.setVisible(False)
            self.imageLabel.setFixedSize(0, 0)
            self.imageStatusLabel.setText(
                self._format_image_status(None) if not image_path else "이미지를 읽을 수 없음"
            )
        self.btnCopyImage.setEnabled(can_copy)

    def _format_question_info(self):
        year = self.question_data.get('year')
        session = self.question_data.get('session')
        subject = self.question_data.get('subject_name') or ''
        number = self.question_data.get('question_number')
        return f"{year}년 {session}회 {subject} {number}번"

    def _init_answer_and_choices(self):
        answer_available = bool(
            self.question_data.get(
                'answer_available', self.question_data.get('correct_answer') != 0
            )
        )
        if not answer_available:
            self.answerCombo.addItem("정답 없음", userData=0)
        self.answerCombo.addItem("전원 정답", userData=ALL_CHOICES_CORRECT)
        for number in self._choice_numbers():
            self._add_answer_option(number)

        correct_answer = self.question_data.get('correct_answer')
        index = self.answerCombo.findData(correct_answer)
        if index < 0:
            index = self.answerCombo.findData(1)
        self.answerCombo.setCurrentIndex(index)

    def _init_subjects(self):
        for subject in self.subject_options:
            self.subjectCombo.addItem(
                subject.get('name_ko') or subject.get('code'),
                userData=subject.get('code')
            )

        current_subject = self.question_data.get('subject_code')
        index = self.subjectCombo.findData(current_subject)
        if index >= 0:
            self.subjectCombo.setCurrentIndex(index)

    def _init_question_types(self):
        self.questionTypeCombo.addItem("객관식", userData=QUESTION_TYPE_MULTIPLE_CHOICE)
        self.questionTypeCombo.addItem("서술형", userData=QUESTION_TYPE_DESCRIPTIVE)
        index = self.questionTypeCombo.findData(self._initial_question_type())
        self.questionTypeCombo.setCurrentIndex(index if index >= 0 else 0)

    def _initial_question_type(self):
        raw = str(self.question_data.get('question_type') or '').strip().lower()
        if raw in {QUESTION_TYPE_DESCRIPTIVE, 'subjective', 'essay', 'written'}:
            return QUESTION_TYPE_DESCRIPTIVE
        if self.question_data.get('model_answer') and not (self.question_data.get('choices') or []):
            return QUESTION_TYPE_DESCRIPTIVE
        return QUESTION_TYPE_MULTIPLE_CHOICE

    def _current_question_type(self):
        return self.questionTypeCombo.currentData() or QUESTION_TYPE_MULTIPLE_CHOICE

    def _apply_question_type_visibility(self):
        is_descriptive = self._current_question_type() == QUESTION_TYPE_DESCRIPTIVE
        for widget in (
            self.choiceSectionLabel,
            self.choiceWidget,
            self.answerSectionLabel,
            self.answerCombo,
        ):
            widget.setVisible(not is_descriptive)
        self.modelAnswerSectionLabel.setVisible(is_descriptive)
        self.modelAnswerText.setVisible(is_descriptive)

    def _choice_text(self, number):
        for choice in self.question_data.get('choices') or []:
            if choice.get('choice_number') == number or choice.get('number') == number:
                return self._display_text(choice.get('choice_text') or choice.get('text') or '')
        return ''

    @staticmethod
    def _display_text(value):
        return normalize_private_math_glyphs(value)

    def _normalize_question_text_input(self):
        if self._normalizing_private_glyphs:
            return
        text = self.questionText.toPlainText()
        normalized = self._display_text(text)
        if normalized == text:
            return
        cursor_position = self.questionText.textCursor().position()
        self._normalizing_private_glyphs = True
        self.questionText.setPlainText(normalized)
        cursor = self.questionText.textCursor()
        cursor.setPosition(min(cursor_position, len(normalized)))
        self.questionText.setTextCursor(cursor)
        self._normalizing_private_glyphs = False

    def _normalize_choice_text_input(self, number):
        if self._normalizing_private_glyphs:
            return
        field = self.choiceInputs.get(number)
        if not field:
            return
        text = field.text()
        normalized = self._display_text(text)
        if normalized == text:
            return
        cursor_position = field.cursorPosition()
        self._normalizing_private_glyphs = True
        field.setText(normalized)
        field.setCursorPosition(min(cursor_position, len(normalized)))
        self._normalizing_private_glyphs = False

    def _choice_image_path(self, number):
        for choice in self.question_data.get('choices') or []:
            if choice.get('choice_number') == number or choice.get('number') == number:
                return choice.get('choice_image_path') or choice.get('image_path')
        return None

    def _choice_format_json(self, number):
        for choice in self.question_data.get('choices') or []:
            if choice.get('choice_number') == number or choice.get('number') == number:
                return choice.get('choice_format_json') or choice.get('format_json')
        return None

    def _set_choice_image_status(self, number):
        self._set_choice_image_preview(number)

    def _set_choice_image_preview(self, number):
        label = self.choiceImageLabels.get(number)
        preview = self.choiceImagePreviews.get(number)
        if not label or not preview:
            return
        image_path = self.choiceImagePaths.get(number)
        if image_path and Path(image_path).exists():
            preview.setImage(image_path)
            preview.setVisible(True)
            label.setText("이미지")
        else:
            if hasattr(preview, "clear"):
                preview.clear()
            preview.setVisible(True)
            label.setText("없음" if not image_path else "파일 없음")

    def _toggle_question_underline(self):
        cursor = self.questionText.textCursor()
        if not cursor.hasSelection():
            return

        make_underlined = not self._selection_is_underlined(cursor)
        text_format = QTextCharFormat()
        text_format.setFontUnderline(make_underlined)
        cursor.mergeCharFormat(text_format)
        self.questionText.mergeCurrentCharFormat(text_format)

    def _wrap_question_selection_as_overline(self):
        cursor = self.questionText.textCursor()
        if not cursor.hasSelection():
            return

        selected = cursor.selectedText().replace('\u2029', '\n')
        cursor.insertText(self._latex_overline(selected))

    def _wrap_choice_selection_as_overline(self, number):
        field = self.choiceInputs.get(number)
        if not field or not field.hasSelectedText():
            return

        start = field.selectionStart()
        selected = field.selectedText()
        replacement = self._latex_overline(selected)
        text = field.text()
        field.setText(f"{text[:start]}{replacement}{text[start + len(selected):]}")
        field.setSelection(start, len(replacement))

    @staticmethod
    def _latex_overline(value):
        return f"\\overline{{{str(value or '').strip()}}}"

    def _selection_is_underlined(self, cursor):
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        if start == end:
            return False

        probe = QTextCursor(self.questionText.document())
        for position in range(start, end):
            probe.setPosition(position)
            probe.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
            if not probe.charFormat().fontUnderline():
                return False
        return True

    def _apply_question_format_json(self, format_json):
        spans = self._format_spans(format_json)
        if not spans:
            return

        text_length = len(self.questionText.toPlainText())
        cursor = QTextCursor(self.questionText.document())
        text_format = QTextCharFormat()
        text_format.setFontUnderline(True)
        for span in spans:
            start = span['start']
            end = span['end']
            if start < 0 or end <= start or end > text_length:
                continue
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            cursor.mergeCharFormat(text_format)

    def _question_text_and_format_json(self):
        return self._text_and_format_json(
            self.questionText.toPlainText(),
            self._underlined_spans_from_document(),
            self.question_data.get('question_format_json')
        )

    def _choice_text_and_format_json(self, number):
        return self._text_and_format_json(
            self.choiceInputs[number].text(),
            [],
            self._choice_format_json(number)
        )

    def _text_and_format_json(self, raw_text, underline_spans, existing_format_json=None):
        formatted = normalize_latex_text(raw_text)
        mapped_underlines = self._map_spans_to_normalized(
            underline_spans,
            formatted.raw_to_normalized,
            len(formatted.text)
        )
        spans = merge_spans(
            mapped_underlines,
            existing_latex_spans(existing_format_json, formatted.text),
            formatted.spans
        )
        encoded = merge_format_spans(existing_format_json, spans)
        payload = parse_format_payload(encoded)
        for table in payload.get('tables', []):
            offset, _recovered = resolve_table_anchor(
                formatted.text,
                table.get('anchor'),
            )
            table['anchor'] = {
                'offset': offset,
                'before_context': formatted.text[max(0, offset - 24):offset],
                'after_context': formatted.text[offset:offset + 24],
            }
        return formatted.text, serialize_format_payload(payload)

    def _map_spans_to_normalized(self, spans, raw_to_normalized, text_length):
        mapped = []
        for span in spans or []:
            try:
                start = int(span.get('start'))
                end = int(span.get('end'))
            except (TypeError, ValueError, AttributeError):
                continue

            positions = [
                raw_to_normalized[index]
                for index in range(max(0, start), min(end, len(raw_to_normalized)))
                if raw_to_normalized[index] is not None
            ]
            if not positions:
                continue
            mapped_start = min(positions)
            mapped_end = max(positions) + 1
            if 0 <= mapped_start < mapped_end <= text_length:
                mapped.append({'start': mapped_start, 'end': mapped_end, 'underline': True})
        return mapped

    def _underlined_spans_from_document(self):
        text = self.questionText.toPlainText()
        if not text:
            return []

        spans = []
        start = None
        cursor = QTextCursor(self.questionText.document())
        for position, char in enumerate(text):
            if char == '\u2029':
                underlined = False
            else:
                cursor.setPosition(position)
                cursor.movePosition(QTextCursor.MoveOperation.NextCharacter, QTextCursor.MoveMode.KeepAnchor)
                underlined = cursor.charFormat().fontUnderline()

            if underlined and start is None:
                start = position
            elif not underlined and start is not None:
                spans.append({'start': start, 'end': position, 'underline': True})
                start = None

        if start is not None:
            spans.append({'start': start, 'end': len(text), 'underline': True})
        return spans

    def _format_spans(self, format_json):
        if not format_json:
            return []
        try:
            payload = json.loads(format_json) if isinstance(format_json, str) else format_json
        except (TypeError, ValueError):
            return []
        spans = payload.get('spans') if isinstance(payload, dict) else []
        normalized = []
        for span in spans or []:
            try:
                start = int(span.get('start'))
                end = int(span.get('end'))
            except (TypeError, ValueError, AttributeError):
                continue
            if span.get('underline') and end > start:
                normalized.append({'start': start, 'end': end, 'underline': True})
        return normalized

    @staticmethod
    def _format_image_status(image_path):
        if not image_path:
            return "이미지 없음"

        name = Path(image_path).name
        if re.match(r"^(?:question|choice\d+)_[0-9a-f]{32}\.png$", name, re.IGNORECASE):
            return "붙여넣은 이미지"
        return name
        
    def _select_image(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "이미지 선택", "", "Images (*.png *.jpg *.jpeg)"
        )
        if file_path:
            self.imagePath = file_path
            self._set_image_preview(file_path)

    def _clipboard_image_dir(self):
        return get_clipboard_image_dir()

    def _clipboard(self):
        return QApplication.clipboard()

    def _clipboard_image(self):
        clipboard = self._clipboard()
        return clipboard.image() if clipboard else None

    @staticmethod
    def _can_copy_image(image_path):
        if not image_path or not Path(image_path).is_file():
            return False
        return not QImage(str(image_path)).isNull()

    def _copy_image_to_clipboard(self):
        if not self._can_copy_image(self.imagePath):
            self.imageStatusLabel.setText(
                "이미지 없음" if not self.imagePath else "이미지를 읽을 수 없음"
            )
            self.btnCopyImage.setEnabled(False)
            return False

        clipboard = self._clipboard()
        if clipboard is None:
            self.imageStatusLabel.setText("클립보드를 사용할 수 없음")
            self.btnCopyImage.setEnabled(False)
            return False

        clipboard.setImage(QImage(str(self.imagePath)))
        self.imageStatusLabel.setText("클립보드에 복사됨")
        return True

    def _save_clipboard_image(self, prefix):
        image = self._clipboard_image()
        if image is None or image.isNull():
            return None

        image_dir = self._clipboard_image_dir()
        image_dir.mkdir(parents=True, exist_ok=True)
        file_path = image_dir / f"{prefix}_{uuid.uuid4().hex}.png"
        if not image.save(str(file_path), "PNG"):
            raise ValueError("클립보드 이미지를 PNG로 저장하지 못했습니다.")
        return str(file_path)

    def _paste_image(self):
        file_path = self._save_clipboard_image("question")
        if file_path:
            self.imagePath = file_path
            self._set_image_preview(file_path)
        else:
            self.imageStatusLabel.setText("클립보드 이미지 없음")

    def _clear_image(self):
        self.imagePath = None
        self._set_image_preview(None)

    def _select_choice_image(self, number):
        file_path, _ = QFileDialog.getOpenFileName(
            self, f"{self._choice_symbol(number)} 선지 이미지 선택", "", "Images (*.png *.jpg *.jpeg)"
        )
        if file_path:
            self.choiceImagePaths[number] = file_path
            self._set_choice_image_status(number)

    def _paste_choice_image(self, number):
        file_path = self._save_clipboard_image(f"choice{number}")
        if file_path:
            self.choiceImagePaths[number] = file_path
        else:
            self.choiceImagePaths[number] = self.choiceImagePaths.get(number)
        self._set_choice_image_status(number)

    def _clear_choice_image(self, number):
        self.choiceImagePaths[number] = None
        self._set_choice_image_status(number)

    def get_data(self):
        question_text, question_format_json = self._question_text_and_format_json()
        question_type = self._current_question_type()
        choices = []
        if question_type != QUESTION_TYPE_DESCRIPTIVE:
            for number in self._choice_numbers():
                choice_text, choice_format_json = self._choice_text_and_format_json(number)
                choices.append({
                    'choice_number': number,
                    'choice_symbol': self._stored_choice_symbol(number),
                    'choice_text': choice_text,
                    'choice_format_json': choice_format_json,
                    'choice_image_path': self.choiceImagePaths.get(number),
                })

        correct_answer = (
            0
            if question_type == QUESTION_TYPE_DESCRIPTIVE
            else self.answerCombo.currentData()
        )
        return {
            'year': self.yearInput.value(),
            'session': self.sessionInput.value(),
            'question_number': self.questionNumberInput.value(),
            'exam_code': self.question_data.get('exam_code'),
            'subject_code': self.subjectCombo.currentData() or self.question_data.get('subject_code'),
            'question_text': question_text,
            'question_format_json': question_format_json,
            'question_type': question_type,
            'model_answer': self.modelAnswerText.toPlainText().strip() if question_type == QUESTION_TYPE_DESCRIPTIVE else None,
            'correct_answer': correct_answer,
            'answer_available': question_type != QUESTION_TYPE_DESCRIPTIVE and correct_answer != 0,
            'tags': self.tagsInput.text(),
            'explanation': self.explanationEditor.toPlainText().strip() or None,
            'image_path': self.imagePath,
            'choices': choices
        }
