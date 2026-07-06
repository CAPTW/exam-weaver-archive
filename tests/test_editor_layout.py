import inspect
import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QDialog
from PyQt5.QtGui import QImage

from src.gui.interface.browser import BrowserInterface
import src.gui.interface.browser as browser_module
from src.gui.interface.editor import QuestionEditor
from src.database.repository import MANUAL_EXAM_CODE, MANUAL_SUBJECT_CODE, QUESTION_TYPE_DESCRIPTIVE
from src.parser.question import Choice, Question


APP = QApplication.instance() or QApplication([])


def test_question_editor_layout_uses_dialog_scroll_area_and_fixed_button_bar():
    source = inspect.getsource(QuestionEditor)

    assert issubclass(QuestionEditor, QDialog)
    assert "QScrollArea" in source
    assert "setWidgetResizable(True)" in source
    assert "buttonBar" in source
    assert "MessageBoxBase" not in source


def test_question_editor_combo_items_store_user_data():
    editor = QuestionEditor(
        question_data={
            'year': 2024,
            'session': 4,
            'question_number': 5,
            'subject_name': '기관3',
            'subject_code': 'engine3',
            'exam_code': '4급기관사',
            'question_text': '다음 그림과 같은 밸브는?',
            'correct_answer': 3,
            'tags': '#4급기관사, #직무일반',
            'choices': [
                {'choice_number': 1, 'choice_text': '나비밸브'},
                {
                    'choice_number': 2,
                    'choice_text': '슬루스밸브',
                    'choice_image_path': 'choice-valve.png',
                },
                {'choice_number': 3, 'choice_text': '체크밸브'},
                {'choice_number': 4, 'choice_text': '글러브밸브'},
            ],
        },
        subject_options=[
            {'code': 'engine1', 'name_ko': '기관1'},
            {'code': 'engine3', 'name_ko': '기관3'},
        ],
    )

    assert editor.answerCombo.currentData() == 3
    assert editor.subjectCombo.currentData() == 'engine3'
    assert editor.get_data()['correct_answer'] == 3
    assert editor.get_data()['subject_code'] == 'engine3'
    assert editor.get_data()['choices'][1]['choice_image_path'] == 'choice-valve.png'
    editor.deleteLater()
    APP.processEvents()


def test_question_editor_shows_shared_passage_as_read_only_context():
    editor = QuestionEditor(
        question_data={
            'year': 2024,
            'session': 1,
            'question_number': 2,
            'subject_code': 'engine1',
            'exam_code': '3급기관사',
            'question_text': '공통지문 하위 문제',
            'shared_passage': '공통 지문 본문',
            'correct_answer': 1,
            'choices': [
                {'choice_number': 1, 'choice_text': 'A'},
                {'choice_number': 2, 'choice_text': 'B'},
                {'choice_number': 3, 'choice_text': 'C'},
                {'choice_number': 4, 'choice_text': 'D'},
            ],
        },
        subject_options=[{'code': 'engine1', 'name_ko': '기관1'}],
    )

    assert editor.sharedPassageText.isReadOnly()
    assert editor.sharedPassageText.toPlainText() == '공통 지문 본문'
    assert 'shared_passage' not in editor.get_data()
    editor.deleteLater()
    APP.processEvents()


def test_question_editor_has_collapsible_explanation_sidecar():
    editor = QuestionEditor(
        question_data={
            'year': 2024,
            'session': 1,
            'question_number': 1,
            'subject_code': 'engine1',
            'exam_code': '3급기관사',
            'question_text': '해설을 붙일 문제',
            'correct_answer': 1,
            'explanation': '기존 해설',
            'choices': [
                {'choice_number': 1, 'choice_text': 'A'},
                {'choice_number': 2, 'choice_text': 'B'},
                {'choice_number': 3, 'choice_text': 'C'},
                {'choice_number': 4, 'choice_text': 'D'},
            ],
        },
        subject_options=[{'code': 'engine1', 'name_ko': '기관1'}],
    )

    assert editor.explanation_sidecar_expanded is True
    assert editor.explanationEditor.toPlainText() == '기존 해설'

    editor.set_explanation_sidecar_expanded(False)
    assert editor.explanationSidecar.isHidden() is True

    editor.explanationButton.click()
    assert editor.explanation_sidecar_expanded is True
    editor.explanationEditor.setPlainText('수정한 해설')

    assert editor.get_data()['explanation'] == '수정한 해설'

    editor.deleteLater()
    APP.processEvents()


def test_browser_interface_marks_grouped_rows_in_info_and_preview():
    interface = BrowserInterface.__new__(BrowserInterface)
    grouped_question = {
        'year': 2024,
        'session': 1,
        'subject_name': '기관1',
        'question_number': 3,
        'question_text': '공통지문 하위 문제',
        'group_id': 0,
        'group_order': 2,
        'group_shared_text': '공통 지문 본문',
    }
    standalone_question = dict(grouped_question, group_id=None, group_order=None)

    assert interface._format_info(grouped_question) == '공통 2024-1 기관1 3번'
    assert interface._format_question_preview(grouped_question) == '[공통] 공통지문 하위 문제'
    assert interface._format_info(standalone_question) == '2024-1 기관1 3번'
    assert interface._format_question_preview(standalone_question) == '공통지문 하위 문제'


def test_question_editor_supports_create_mode_for_manual_questions(repo):
    editor = QuestionEditor(
        question_data=repo.get_manual_question_template(),
        subject_options=repo.get_manual_subject_options(),
        create_mode=True,
    )

    assert editor.windowTitle() == "개인 제작 문제 추가"
    assert editor.titleLabel.text() == "개인 제작 문제 추가"
    assert editor.btnImage.text() == "이미지 추가"
    assert editor.get_data()['exam_code'] == MANUAL_EXAM_CODE
    assert editor.get_data()['subject_code'] == MANUAL_SUBJECT_CODE

    editor.deleteLater()
    APP.processEvents()


def test_question_editor_can_add_more_than_five_choices():
    editor = QuestionEditor(
        question_data={
            'year': 2024,
            'session': 1,
            'question_number': 1,
            'subject_code': 'manual_general',
            'exam_code': MANUAL_EXAM_CODE,
            'question_text': '6지선다로 바꿀 문제',
            'correct_answer': 1,
            'choices': [
                {'choice_number': 1, 'choice_text': 'A'},
                {'choice_number': 2, 'choice_text': 'B'},
                {'choice_number': 3, 'choice_text': 'C'},
                {'choice_number': 4, 'choice_text': 'D'},
            ],
        },
        subject_options=[{'code': MANUAL_SUBJECT_CODE, 'name_ko': '개인 문제'}],
        create_mode=True,
    )

    editor.btnAddChoice.click()
    editor.btnAddChoice.click()
    editor.choiceInputs[5].setText('E')
    editor.choiceInputs[6].setText('F')
    editor.answerCombo.setCurrentIndex(editor.answerCombo.findData(6))

    data = editor.get_data()
    assert len(data['choices']) == 6
    assert data['correct_answer'] == 6
    assert data['choices'][4]['choice_symbol'] == '⑤'
    assert data['choices'][5]['choice_symbol'] == '6'
    assert data['choices'][5]['choice_text'] == 'F'

    editor.deleteLater()
    APP.processEvents()


def test_question_editor_supports_descriptive_mode(repo):
    editor = QuestionEditor(
        question_data=repo.get_manual_descriptive_question_template(),
        subject_options=repo.get_manual_subject_options(),
        create_mode=True,
    )

    editor.questionText.setPlainText('복원성의 의미를 서술하시오.')
    editor.modelAnswerText.setPlainText('기울어진 선박이 원위치로 돌아가려는 성질이다.')
    data = editor.get_data()

    assert editor.windowTitle() == "서술형 문제 추가"
    assert editor.questionTypeCombo.currentData() == QUESTION_TYPE_DESCRIPTIVE
    assert editor.choiceWidget.isHidden() is True
    assert editor.answerCombo.isHidden() is True
    assert editor.modelAnswerText.isHidden() is False
    assert data['question_type'] == QUESTION_TYPE_DESCRIPTIVE
    assert data['model_answer'] == '기울어진 선박이 원위치로 돌아가려는 성질이다.'
    assert data['correct_answer'] == 0
    assert data['choices'] == []

    editor.deleteLater()
    APP.processEvents()


def test_browser_manual_add_button_creates_personal_question(repo, monkeypatch):
    class FakeManualQuestionDialog:
        captured_question_data = None
        captured_subject_options = None

        def __init__(self, _parent, question_data, subject_options=None, create_mode=False):
            self.captured_question_data = question_data
            self.captured_subject_options = subject_options
            self.create_mode = create_mode
            FakeManualQuestionDialog.captured_question_data = question_data
            FakeManualQuestionDialog.captured_subject_options = subject_options

        def exec(self):
            return True

        def get_data(self):
            data = dict(self.captured_question_data)
            data.update({
                'question_text': '개인 수동 추가 문제',
                'correct_answer': 1,
                'choices': [
                    {'choice_number': 1, 'choice_symbol': '㉮', 'choice_text': '정답'},
                    {'choice_number': 2, 'choice_symbol': '㉯', 'choice_text': '오답 1'},
                    {'choice_number': 3, 'choice_symbol': '㉴', 'choice_text': '오답 2'},
                    {'choice_number': 4, 'choice_symbol': '㉵', 'choice_text': '오답 3'},
                ],
            })
            return data

    monkeypatch.setattr(browser_module, "QuestionEditor", FakeManualQuestionDialog)
    widget = BrowserInterface(repo.db_path)

    assert widget.btnAddManual.text() == "문제 추가"
    widget.add_manual_question()

    saved = repo.get_questions_with_choices(exam_code=MANUAL_EXAM_CODE, limit=1)
    assert len(saved) == 1
    assert saved[0]['question_text'] == '개인 수동 추가 문제'
    assert widget.examFilter.currentData() == MANUAL_EXAM_CODE
    assert widget.subjectFilter.currentData() == MANUAL_SUBJECT_CODE
    assert FakeManualQuestionDialog.captured_subject_options == repo.get_manual_subject_options()

    widget.deleteLater()
    APP.processEvents()


def test_browser_clone_button_creates_customized_personal_question(repo, monkeypatch):
    source_question = Question(
        number=1,
        text='기존 기출문제 원본',
        choices=[
            Choice(number=1, symbol='㉮', text='A'),
            Choice(number=2, symbol='㉯', text='B'),
            Choice(number=3, symbol='㉴', text='C'),
            Choice(number=4, symbol='㉵', text='D'),
        ],
        correct_answer=2,
        subject_name='기관1',
        year=2024,
        session=1,
        exam_type='3급기관사',
    )
    metadata = type('Metadata', (), {'year': 2024, 'session': 1, 'exam_type': '3급기관사'})()
    repo.save_questions([source_question], metadata)
    source = repo.get_questions_with_choices(exam_code='3급기관사', limit=1)[0]

    class FakeCloneQuestionDialog:
        captured_question_data = None
        captured_subject_options = None

        def __init__(self, _parent, question_data, subject_options=None, create_mode=False):
            self.captured_question_data = question_data
            self.captured_subject_options = subject_options
            self.create_mode = create_mode
            FakeCloneQuestionDialog.captured_question_data = question_data
            FakeCloneQuestionDialog.captured_subject_options = subject_options

        def exec(self):
            return True

        def get_data(self):
            data = dict(self.captured_question_data)
            data.update({
                'question_text': '복제 후 커스터마이징한 문제',
                'correct_answer': 5,
                'choices': [
                    {'choice_number': 1, 'choice_symbol': '㉮', 'choice_text': 'A'},
                    {'choice_number': 2, 'choice_symbol': '㉯', 'choice_text': 'B'},
                    {'choice_number': 3, 'choice_symbol': '㉴', 'choice_text': 'C'},
                    {'choice_number': 4, 'choice_symbol': '㉵', 'choice_text': 'D'},
                    {'choice_number': 5, 'choice_symbol': '⑤', 'choice_text': 'E'},
                ],
            })
            return data

    monkeypatch.setattr(browser_module, "QuestionEditor", FakeCloneQuestionDialog)
    widget = BrowserInterface(repo.db_path)
    widget.clone_question(source['id'])

    saved = repo.get_questions_with_choices(exam_code=MANUAL_EXAM_CODE, limit=1)
    assert len(saved) == 1
    assert saved[0]['question_text'] == '복제 후 커스터마이징한 문제'
    assert saved[0]['correct_answer'] == 5
    assert [choice['choice_number'] for choice in saved[0]['choices']] == [1, 2, 3, 4, 5]
    assert widget.examFilter.currentData() == MANUAL_EXAM_CODE
    assert widget.subjectFilter.currentData() == MANUAL_SUBJECT_CODE
    assert FakeCloneQuestionDialog.captured_question_data['editor_title'] == '기존 문제 복제'
    assert FakeCloneQuestionDialog.captured_subject_options == repo.get_manual_subject_options()

    widget.deleteLater()
    APP.processEvents()


def test_browser_descriptive_add_button_creates_model_answer_question(repo, monkeypatch):
    class FakeDescriptiveQuestionDialog:
        captured_question_data = None
        captured_subject_options = None

        def __init__(self, _parent, question_data, subject_options=None, create_mode=False):
            self.captured_question_data = question_data
            self.captured_subject_options = subject_options
            self.create_mode = create_mode
            FakeDescriptiveQuestionDialog.captured_question_data = question_data
            FakeDescriptiveQuestionDialog.captured_subject_options = subject_options

        def exec(self):
            return True

        def get_data(self):
            data = dict(self.captured_question_data)
            data.update({
                'question_text': '서술형 수동 추가 문제',
                'question_type': QUESTION_TYPE_DESCRIPTIVE,
                'model_answer': '서술형 모범답안',
                'correct_answer': 0,
                'choices': [],
            })
            return data

    monkeypatch.setattr(browser_module, "QuestionEditor", FakeDescriptiveQuestionDialog)
    widget = BrowserInterface(repo.db_path)

    assert widget.btnAddDescriptive.text() == "서술형 추가"
    widget.add_descriptive_question()

    saved = repo.get_questions_with_choices(exam_code=MANUAL_EXAM_CODE, limit=1)
    assert len(saved) == 1
    assert saved[0]['question_type'] == QUESTION_TYPE_DESCRIPTIVE
    assert saved[0]['model_answer'] == '서술형 모범답안'
    assert saved[0]['choices'] == []
    assert widget.examFilter.currentData() == MANUAL_EXAM_CODE
    assert widget.subjectFilter.currentData() == MANUAL_SUBJECT_CODE
    assert FakeDescriptiveQuestionDialog.captured_subject_options == repo.get_manual_subject_options()

    widget.deleteLater()
    APP.processEvents()


def test_question_editor_pastes_clipboard_images_to_question_and_choice(tmp_path, monkeypatch):
    editor = QuestionEditor.__new__(QuestionEditor)
    editor.imagePath = None
    editor.choiceImagePaths = {1: None, 2: None, 3: None, 4: None}
    image = QImage(4, 4, QImage.Format.Format_RGB32)
    image.fill(0x00FF00)
    monkeypatch.setattr(editor, "_clipboard_image", lambda: image)
    monkeypatch.setattr(editor, "_clipboard_image_dir", lambda: tmp_path)
    monkeypatch.setattr(editor, "_set_image_preview", lambda _path: None)
    monkeypatch.setattr(editor, "_set_choice_image_status", lambda _number: None)

    editor._paste_image()
    editor._paste_choice_image(2)

    assert Path(editor.imagePath).exists()
    assert Path(editor.choiceImagePaths[2]).exists()
    assert editor.imagePath.endswith('.png')
    assert editor.choiceImagePaths[2].endswith('.png')


def test_question_editor_can_clear_question_and_choice_images():
    editor = QuestionEditor(
        question_data={
            'year': 2024,
            'session': 1,
            'question_number': 1,
            'subject_code': 'engine1',
            'exam_code': '4급기관사',
            'question_text': '잘못 붙은 이미지를 삭제할 문제',
            'image_path': 'wrong-question.png',
            'correct_answer': 1,
            'choices': [
                {
                    'choice_number': 1,
                    'choice_text': '이미지 없는 보기',
                    'choice_image_path': 'wrong-choice.png',
                },
                {'choice_number': 2, 'choice_text': 'B'},
                {'choice_number': 3, 'choice_text': 'C'},
                {'choice_number': 4, 'choice_text': 'D'},
            ],
        },
        subject_options=[{'code': 'engine1', 'name_ko': '기관1'}],
    )

    editor._clear_image()
    editor._clear_choice_image(1)
    data = editor.get_data()

    assert hasattr(editor, 'btnClearImage')
    assert 1 in editor.choiceClearImageButtons
    assert data['image_path'] is None
    assert data['choices'][0]['choice_image_path'] is None
    assert editor.imageStatusLabel.text() == "이미지 없음"
    assert editor.choiceImageLabels[1].text() == "없음"
    editor.deleteLater()
    APP.processEvents()


def test_question_editor_hides_generated_clipboard_image_filenames():
    assert QuestionEditor._format_image_status(None) == "이미지 없음"
    assert (
        QuestionEditor._format_image_status(
            r"C:\tmp\choice1_1d4ae94d82a642cc993c44256789abcd.png"
        )
        == "붙여넣은 이미지"
    )
    assert QuestionEditor._format_image_status(r"C:\tmp\valve-diagram.png") == "valve-diagram.png"


def test_question_editor_choice_images_have_thumbnail_previews():
    source = inspect.getsource(QuestionEditor)

    assert "choiceImagePreviews" in source
    assert "_set_choice_image_preview" in source
    assert "setImage(image_path)" in source


def test_question_editor_can_apply_question_underline_format():
    editor = QuestionEditor(
        question_data={
            'year': 2024,
            'session': 1,
            'question_number': 1,
            'subject_code': 'engine1',
            'exam_code': '4급기관사',
            'question_text': '밑줄 친 부분',
            'correct_answer': 1,
            'choices': [
                {'choice_number': 1, 'choice_text': 'A'},
                {'choice_number': 2, 'choice_text': 'B'},
                {'choice_number': 3, 'choice_text': 'C'},
                {'choice_number': 4, 'choice_text': 'D'},
            ],
        },
        subject_options=[{'code': 'engine1', 'name_ko': '기관1'}],
    )

    cursor = editor.questionText.textCursor()
    cursor.setPosition(0)
    cursor.setPosition(2, cursor.MoveMode.KeepAnchor)
    editor.questionText.setTextCursor(cursor)
    editor._toggle_question_underline()

    data = editor.get_data()
    spans = json.loads(data['question_format_json'])['spans']

    assert data['question_text'] == '밑줄 친 부분'
    assert spans == [{'start': 0, 'end': 2, 'underline': True}]
    editor.deleteLater()
    APP.processEvents()


def test_question_editor_restores_existing_question_underline_format():
    editor = QuestionEditor(
        question_data={
            'year': 2024,
            'session': 1,
            'question_number': 1,
            'subject_code': 'engine1',
            'exam_code': '4급기관사',
            'question_text': '밑줄 친 부분',
            'question_format_json': json.dumps({
                'spans': [{'start': 0, 'end': 2, 'underline': True}]
            }, ensure_ascii=False),
            'correct_answer': 1,
            'choices': [
                {'choice_number': 1, 'choice_text': 'A'},
                {'choice_number': 2, 'choice_text': 'B'},
                {'choice_number': 3, 'choice_text': 'C'},
                {'choice_number': 4, 'choice_text': 'D'},
            ],
        },
        subject_options=[{'code': 'engine1', 'name_ko': '기관1'}],
    )

    spans = json.loads(editor.get_data()['question_format_json'])['spans']

    assert spans == [{'start': 0, 'end': 2, 'underline': True}]
    editor.deleteLater()
    APP.processEvents()


def test_question_editor_converts_pasted_latex_to_format_json():
    editor = QuestionEditor(
        question_data={
            'year': 2024,
            'session': 1,
            'question_number': 1,
            'subject_code': 'engine1',
            'exam_code': '4급기관사',
            'question_text': '값은 \\(\\sqrt{GM}\\) 이다',
            'correct_answer': 1,
            'choices': [
                {'choice_number': 1, 'choice_text': '\\(\\sqrt{L}\\)'},
                {'choice_number': 2, 'choice_text': 'B'},
                {'choice_number': 3, 'choice_text': 'C'},
                {'choice_number': 4, 'choice_text': 'D'},
            ],
        },
        subject_options=[{'code': 'engine1', 'name_ko': '기관1'}],
    )

    data = editor.get_data()
    question_spans = json.loads(data['question_format_json'])['spans']
    choice_spans = json.loads(data['choices'][0]['choice_format_json'])['spans']

    assert data['question_text'] == '값은 \\sqrt{GM} 이다'
    assert question_spans == [{'start': 3, 'end': 12, 'latex': '\\sqrt{GM}'}]
    assert data['choices'][0]['choice_text'] == '\\sqrt{L}'
    assert choice_spans == [{'start': 0, 'end': 8, 'latex': '\\sqrt{L}'}]
    editor.deleteLater()
    APP.processEvents()


def test_question_editor_converts_pasted_unicode_power_formulas_to_latex_spans():
    editor = QuestionEditor(
        question_data={
            'year': 2024,
            'session': 1,
            'question_number': 1,
            'subject_code': 'engine2',
            'exam_code': '3급기관사',
            'question_text': '3상 교류 유효전력을 표시한 것으로 옳은 것은? (단, E는 선간전압, I는 선전류, θ는 위상각이다)',
            'correct_answer': 2,
            'choices': [
                {'choice_number': 1, 'choice_text': 'P = √2 × E × I × cosθ'},
                {'choice_number': 2, 'choice_text': 'P = √3 × E × I × cosθ'},
                {'choice_number': 3, 'choice_text': 'P = √2 × E × I × sinθ'},
                {'choice_number': 4, 'choice_text': 'P = √3 × E × I × sinθ'},
            ],
        },
        subject_options=[{'code': 'engine2', 'name_ko': '기관2'}],
    )

    data = editor.get_data()
    expected = [
        'P=\\sqrt{2} \\times E \\times I \\times \\cos\\theta',
        'P=\\sqrt{3} \\times E \\times I \\times \\cos\\theta',
        'P=\\sqrt{2} \\times E \\times I \\times \\sin\\theta',
        'P=\\sqrt{3} \\times E \\times I \\times \\sin\\theta',
    ]

    assert data['question_format_json'] is None
    assert [choice['choice_text'] for choice in data['choices']] == expected
    for choice, text in zip(data['choices'], expected):
        assert json.loads(choice['choice_format_json'])['spans'] == [
            {'start': 0, 'end': len(text), 'latex': text}
        ]
    editor.deleteLater()
    APP.processEvents()


def test_question_editor_displays_private_math_glyphs_as_readable_symbols():
    editor = QuestionEditor(
        question_data={
            'year': 2024,
            'session': 1,
            'question_number': 1,
            'subject_code': 'engine2',
            'exam_code': '3급기관사',
            'question_text': '3상 교류 유효전력을 표시한 것으로 옳은 것은? (단, \ue004는 선간전압, \ue008는 선전류, \ue0a4는 위상각이다)',
            'correct_answer': 2,
            'choices': [
                {'choice_number': 1, 'choice_text': 'P = \ue05c\ue06d\ue035 × \ue004 × \ue008 × cos\ue0a4'},
                {'choice_number': 2, 'choice_text': 'P = \ue05c\ue06d\ue036 × \ue004 × \ue008 × cos\ue0a4'},
                {'choice_number': 3, 'choice_text': 'C'},
                {'choice_number': 4, 'choice_text': 'D'},
            ],
        },
        subject_options=[{'code': 'engine2', 'name_ko': '기관2'}],
    )

    assert editor.questionText.toPlainText() == (
        '3상 교류 유효전력을 표시한 것으로 옳은 것은? '
        '(단, E는 선간전압, I는 선전류, θ는 위상각이다)'
    )
    assert editor.choiceInputs[0 + 1].text() == 'P = √2 × E × I × cosθ'
    assert editor.choiceInputs[2].text() == 'P = √3 × E × I × cosθ'
    data = editor.get_data()
    assert '\ue004' not in data['question_text']
    assert '\ue008' not in data['question_text']
    assert '\ue0a4' not in data['question_text']
    assert 'E는 선간전압' in data['question_text']
    assert 'I는 선전류' in data['question_text']
    assert 'θ는 위상각' in data['question_text']
    editor.deleteLater()
    APP.processEvents()


def test_question_editor_normalizes_private_math_glyphs_while_manually_editing():
    editor = QuestionEditor(
        question_data={
            'year': 2024,
            'session': 1,
            'question_number': 1,
            'subject_code': 'engine2',
            'exam_code': '3급기관사',
            'question_text': '초기 발문',
            'correct_answer': 1,
            'choices': [
                {'choice_number': 1, 'choice_text': 'A'},
                {'choice_number': 2, 'choice_text': 'B'},
                {'choice_number': 3, 'choice_text': 'C'},
                {'choice_number': 4, 'choice_text': 'D'},
            ],
        },
        subject_options=[{'code': 'engine2', 'name_ko': '기관2'}],
    )

    editor.questionText.setPlainText(
        '3상 교류 유효전력은? (단, \ue004는 선간전압, \ue008는 선전류, \ue0a4는 위상각이다)'
    )
    editor.choiceInputs[1].setText('P = \ue05c\ue06d\ue036 × \ue004 × \ue008 × cos\ue0a4')
    APP.processEvents()

    assert editor.questionText.toPlainText() == (
        '3상 교류 유효전력은? (단, E는 선간전압, I는 선전류, θ는 위상각이다)'
    )
    assert editor.choiceInputs[1].text() == 'P = √3 × E × I × cosθ'
    editor.deleteLater()
    APP.processEvents()


def test_question_editor_wraps_question_and_choice_selection_as_overline_latex():
    editor = QuestionEditor(
        question_data={
            'year': 2024,
            'session': 1,
            'question_number': 1,
            'subject_code': 'engine1',
            'exam_code': '4급기관사',
            'question_text': 'Y = A+B',
            'correct_answer': 1,
            'choices': [
                {'choice_number': 1, 'choice_text': 'Y = A+B'},
                {'choice_number': 2, 'choice_text': 'B'},
                {'choice_number': 3, 'choice_text': 'C'},
                {'choice_number': 4, 'choice_text': 'D'},
            ],
        },
        subject_options=[{'code': 'engine1', 'name_ko': '기관1'}],
    )

    question_cursor = editor.questionText.textCursor()
    question_cursor.setPosition(4)
    question_cursor.setPosition(7, question_cursor.MoveMode.KeepAnchor)
    editor.questionText.setTextCursor(question_cursor)
    editor._wrap_question_selection_as_overline()
    editor.choiceInputs[1].setSelection(4, 3)
    editor._wrap_choice_selection_as_overline(1)

    data = editor.get_data()
    question_spans = json.loads(data['question_format_json'])['spans']
    choice_spans = json.loads(data['choices'][0]['choice_format_json'])['spans']

    assert data['question_text'] == 'Y = \\overline{A+B}'
    assert question_spans == [{'start': 4, 'end': 18, 'latex': '\\overline{A+B}'}]
    assert data['choices'][0]['choice_text'] == 'Y = \\overline{A+B}'
    assert choice_spans == [{'start': 4, 'end': 18, 'latex': '\\overline{A+B}'}]
    editor.deleteLater()
    APP.processEvents()
