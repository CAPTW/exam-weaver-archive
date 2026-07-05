import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from src.gui.interface.export import ExportInterface


APP = QApplication.instance() or QApplication([])


class _Combo:
    def __init__(self, data, text):
        self._data = data
        self._text = text

    def currentData(self):
        return self._data

    def currentText(self):
        return self._text


class _Spin:
    def __init__(self, value):
        self._value = value

    def value(self):
        return self._value

    def setValue(self, value):
        self._value = value


class _Check:
    def __init__(self, checked=False):
        self._checked = checked

    def isChecked(self):
        return self._checked

    def setChecked(self, checked):
        self._checked = checked


class _Line:
    def __init__(self, text):
        self._text = text

    def text(self):
        return self._text


def _subject_request(code, name, count, checked=True):
    return {
        'code': code,
        'name': name,
        'checkbox': _Check(checked),
        'count_spin': _Spin(count),
    }


def test_build_title_matches_reference_docx_header():
    interface = ExportInterface.__new__(ExportInterface)

    title = interface._build_title(
        "4급 기관사 (4급기관사)",
        2023,
        2025,
        "기관1 (engine1)",
        25,
    )

    assert title == "2023-2025 4급 기관사\n기관1"


def test_subject_label_hides_auto_generated_codes():
    assert ExportInterface._subject_label({
        'name_ko': '컴퓨터 이해',
        'code': 'custom_e797728190',
    }) == '컴퓨터 이해'
    assert ExportInterface._subject_label({
        'name_ko': '정보통신 이해',
        'code': 'auto_정보통신_이해_c28b98',
    }) == '정보통신 이해'
    assert ExportInterface._subject_label({
        'name_ko': '기관1',
        'code': 'engine1',
    }) == '기관1 (engine1)'


def test_export_interface_initializes_all_subject_bulk_controls(repo):
    interface = ExportInterface(repo.db_path)

    assert interface.allSubjectCountSpin.value() == 25
    assert interface.btnApplyAllSubjects.text() == "Apply to all subjects"
    interface.deleteLater()
    APP.processEvents()


def test_export_interface_initializes_hashtag_filter(repo):
    interface = ExportInterface(repo.db_path)

    assert interface.tagFilter.text() == ""
    assert interface.tagFilter.placeholderText() == "#계산, #SOLAS"
    interface.deleteLater()
    APP.processEvents()


def test_export_interface_keeps_random_subject_section_visible_on_initial_window(repo):
    interface = ExportInterface(repo.db_path)

    assert interface.vBoxLayout.spacing() <= 12
    assert interface.subjectSelectionTable.minimumHeight() >= 168
    assert interface.subjectSelectionTable.maximumHeight() <= 240
    interface.deleteLater()
    APP.processEvents()


def test_export_interface_hides_seed_exams_when_database_has_no_questions(repo):
    interface = ExportInterface(repo.db_path)

    assert interface.examFilter.count() == 0
    assert interface.subjectFilter.count() == 1
    assert interface.subjectSelectionTable.rowCount() == 0

    interface.deleteLater()
    APP.processEvents()


def test_apply_all_subject_count_selects_every_subject_with_same_count():
    interface = ExportInterface.__new__(ExportInterface)
    interface.subjectSelectionRows = [
        _subject_request('engine1', '기관1', 0, checked=False),
        _subject_request('engine2', '기관2', 3, checked=False),
        _subject_request('engine3', '기관3', 7, checked=True),
    ]

    interface._apply_all_subject_count(25)

    assert interface._selected_random_subject_requests() == (
        [
            {'code': 'engine1', 'name': '기관1', 'count': 25},
            {'code': 'engine2', 'name': '기관2', 'count': 25},
            {'code': 'engine3', 'name': '기관3', 'count': 25},
        ],
        [],
    )


def test_apply_all_subject_count_uses_spin_value_when_called_from_button_signal():
    interface = ExportInterface.__new__(ExportInterface)
    interface.allSubjectCountSpin = _Spin(12)
    interface.subjectSelectionRows = [
        _subject_request('engine1', '기관1', 0, checked=False),
        _subject_request('engine2', '기관2', 0, checked=False),
    ]

    interface._apply_all_subject_count(False)

    assert [request['count'] for request in interface._selected_random_subject_requests()[0]] == [12, 12]


def test_export_docx_filters_selected_year_range_before_deduping(monkeypatch):
    interface = ExportInterface.__new__(ExportInterface)
    interface.examFilter = _Combo('3급기관사', '3급기관사 (3급기관사)')
    interface.yearFromFilter = _Combo(2024, '2024')
    interface.yearToFilter = _Combo(2024, '2024')
    interface.subjectFilter = _Combo('engine1', '기관1 (engine1)')
    interface.tagFilter = _Line('#계산, #안전')
    interface.randomCountSpin = _Spin(0)
    interface.shuffleChoices = _Check(False)

    exported = {}

    class Repo:
        def get_questions_with_choices(self, **kwargs):
            exported['repo_kwargs'] = kwargs
            return [
                {
                    'id': 1,
                    'year': 2025,
                    'question_text': '중복 문제',
                    'image_path': None,
                    'choices': [],
                    'correct_answer': 1,
                },
                {
                    'id': 2,
                    'year': 2024,
                    'question_text': '중복 문제',
                    'image_path': None,
                    'choices': [],
                    'correct_answer': 1,
                },
            ]

    class Exporter:
        def export(self, title, questions, file_path, shuffle_choices=False, sections=None):
            exported['title'] = title
            exported['questions'] = questions
            exported['file_path'] = file_path
            exported['shuffle_choices'] = shuffle_choices
            exported['sections'] = sections

    interface.repo = Repo()
    interface.exporter = Exporter()

    monkeypatch.setattr(
        'src.gui.interface.export.QFileDialog.getSaveFileName',
        lambda *_args, **_kwargs: ('C:/tmp/out.docx', 'Word Documents (*.docx)'),
    )
    monkeypatch.setattr(
        'src.gui.interface.export.InfoBar.success',
        lambda **_kwargs: None,
    )

    interface.export_docx()

    assert exported['repo_kwargs']['year_from'] == 2024
    assert exported['repo_kwargs']['year_to'] == 2024
    assert exported['repo_kwargs']['tag_query'] == '#계산, #안전'
    assert [q['id'] for q in exported['questions']] == [2]


def test_export_docx_combines_random_questions_from_multiple_subjects(monkeypatch):
    interface = ExportInterface.__new__(ExportInterface)
    interface.examFilter = _Combo('3급기관사', '3급기관사 (3급기관사)')
    interface.yearFromFilter = _Combo(2025, '2025')
    interface.yearToFilter = _Combo(2025, '2025')
    interface.subjectFilter = _Combo(None, 'All subjects')
    interface.randomCountSpin = _Spin(0)
    interface.shuffleChoices = _Check(False)
    interface.subjectSelectionRows = [
        _subject_request('engine1', '기관1', 1),
        _subject_request('engine2', '기관2', 2),
    ]

    exported = {'calls': []}

    class Repo:
        def get_questions_with_choices(self, **kwargs):
            exported['calls'].append(kwargs)
            if kwargs['subject_code'] == 'engine1':
                return [
                    {
                        'id': 1,
                        'year': 2025,
                        'question_text': '기관1 2025 문제',
                        'image_path': None,
                        'choices': [],
                        'correct_answer': 1,
                    },
                    {
                        'id': 2,
                        'year': 2024,
                        'question_text': '기관1 2024 문제',
                        'image_path': None,
                        'choices': [],
                        'correct_answer': 1,
                    },
                ]
            if kwargs['subject_code'] == 'engine2':
                return [
                    {
                        'id': 3,
                        'year': 2025,
                        'question_text': '기관2 2025 문제 A',
                        'image_path': None,
                        'choices': [],
                        'correct_answer': 1,
                    },
                    {
                        'id': 4,
                        'year': 2025,
                        'question_text': '기관2 2025 문제 B',
                        'image_path': None,
                        'choices': [],
                        'correct_answer': 1,
                    },
                    {
                        'id': 5,
                        'year': 2024,
                        'question_text': '기관2 2024 문제',
                        'image_path': None,
                        'choices': [],
                        'correct_answer': 1,
                    },
                ]
            return []

    class Validator:
        def is_random_eligible(self, question):
            return True

    class Exporter:
        def export(self, title, questions, file_path, shuffle_choices=False, sections=None):
            exported['title'] = title
            exported['questions'] = questions
            exported['file_path'] = file_path
            exported['shuffle_choices'] = shuffle_choices
            exported['sections'] = sections

    interface.repo = Repo()
    interface.validator = Validator()
    interface.exporter = Exporter()

    monkeypatch.setattr(
        'src.gui.interface.export.random.sample',
        lambda population, count: list(population)[:count],
    )
    monkeypatch.setattr(
        'src.gui.interface.export.QFileDialog.getSaveFileName',
        lambda *_args, **_kwargs: ('C:/tmp/out.docx', 'Word Documents (*.docx)'),
    )
    monkeypatch.setattr(
        'src.gui.interface.export.InfoBar.success',
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        'src.gui.interface.export.InfoBar.warning',
        lambda **_kwargs: None,
    )

    interface.export_docx()

    assert [call['subject_code'] for call in exported['calls']] == ['engine1', 'engine2']
    assert all(call['year_from'] == 2025 and call['year_to'] == 2025 for call in exported['calls'])
    assert [q['id'] for q in exported['questions']] == [1, 3, 4]
    assert exported['title'].endswith("3급 기관사 모의고사")
    assert [(section['title'], [q['id'] for q in section['questions']]) for section in exported['sections']] == [
        ('기관1', [1]),
        ('기관2', [3, 4]),
    ]


def test_export_docx_random_subject_keeps_grouped_questions_together_in_group_order(monkeypatch):
    interface = ExportInterface.__new__(ExportInterface)
    interface.examFilter = _Combo('3급기관사', '3급기관사 (3급기관사)')
    interface.yearFromFilter = _Combo(2025, '2025')
    interface.yearToFilter = _Combo(2025, '2025')
    interface.subjectFilter = _Combo('engine1', '기관1 (engine1)')
    interface.randomCountSpin = _Spin(2)
    interface.shuffleChoices = _Check(False)

    exported = {}

    class Repo:
        def get_questions_with_choices(self, **kwargs):
            return [
                {
                    'id': 1,
                    'year': 2025,
                    'question_number': 1,
                    'question_text': '두 번째 group child',
                    'group_id': 10,
                    'group_order': 2,
                    'image_path': None,
                    'choices': [],
                    'correct_answer': 1,
                },
                {
                    'id': 2,
                    'year': 2025,
                    'question_number': 2,
                    'question_text': '첫 번째 group child',
                    'group_id': 10,
                    'group_order': 1,
                    'image_path': None,
                    'choices': [],
                    'correct_answer': 1,
                },
                {
                    'id': 3,
                    'year': 2025,
                    'question_number': 3,
                    'question_text': '단독 문제',
                    'image_path': None,
                    'choices': [],
                    'correct_answer': 1,
                },
            ]

    class Validator:
        def is_random_eligible(self, question):
            return True

    class Exporter:
        def export(self, title, questions, file_path, shuffle_choices=False, sections=None):
            exported['questions'] = questions
            exported['sections'] = sections

    interface.repo = Repo()
    interface.validator = Validator()
    interface.exporter = Exporter()

    monkeypatch.setattr(
        'src.gui.interface.export.random.sample',
        lambda population, count: list(population)[:count],
    )
    monkeypatch.setattr(
        'src.gui.interface.export.QFileDialog.getSaveFileName',
        lambda *_args, **_kwargs: ('C:/tmp/out.docx', 'Word Documents (*.docx)'),
    )
    monkeypatch.setattr(
        'src.gui.interface.export.InfoBar.success',
        lambda **_kwargs: None,
    )

    interface.export_docx()

    assert [question['id'] for question in exported['questions']] == [2, 1]
    assert exported['sections'] is None


def test_export_docx_random_subject_excludes_entire_group_when_any_child_is_invalid(monkeypatch):
    interface = ExportInterface.__new__(ExportInterface)
    interface.examFilter = _Combo('3급기관사', '3급기관사 (3급기관사)')
    interface.yearFromFilter = _Combo(2025, '2025')
    interface.yearToFilter = _Combo(2025, '2025')
    interface.subjectFilter = _Combo('engine1', '기관1 (engine1)')
    interface.randomCountSpin = _Spin(1)
    interface.shuffleChoices = _Check(False)

    exported = {}

    class Repo:
        def get_questions_with_choices(self, **kwargs):
            return [
                {
                    'id': 1,
                    'year': 2025,
                    'question_number': 1,
                    'question_text': '유효한 공통 하위 문제',
                    'group_id': 10,
                    'group_order': 1,
                    'image_path': None,
                    'choices': [],
                    'correct_answer': 1,
                },
                {
                    'id': 2,
                    'year': 2025,
                    'question_number': 2,
                    'question_text': '정답 오류가 있는 공통 하위 문제',
                    'group_id': 10,
                    'group_order': 2,
                    'image_path': None,
                    'choices': [],
                    'correct_answer': 5,
                },
                {
                    'id': 3,
                    'year': 2025,
                    'question_number': 3,
                    'question_text': '선택 가능한 단독 문제',
                    'image_path': None,
                    'choices': [],
                    'correct_answer': 1,
                },
            ]

    class Validator:
        def is_random_eligible(self, question):
            return question['correct_answer'] in (1, 2, 3, 4)

    class Exporter:
        def export(self, title, questions, file_path, shuffle_choices=False, sections=None):
            exported['questions'] = questions
            exported['sections'] = sections

    interface.repo = Repo()
    interface.validator = Validator()
    interface.exporter = Exporter()

    monkeypatch.setattr(
        'src.gui.interface.export.random.sample',
        lambda population, count: list(population)[:count],
    )
    monkeypatch.setattr(
        'src.gui.interface.export.QFileDialog.getSaveFileName',
        lambda *_args, **_kwargs: ('C:/tmp/out.docx', 'Word Documents (*.docx)'),
    )
    monkeypatch.setattr(
        'src.gui.interface.export.InfoBar.success',
        lambda **_kwargs: None,
    )

    interface.export_docx()

    assert [question['id'] for question in exported['questions']] == [3]
    assert exported['sections'] is None


def test_export_docx_random_subject_filters_invalid_duplicate_group_before_dedupe(monkeypatch):
    interface = ExportInterface.__new__(ExportInterface)
    interface.examFilter = _Combo('3급기관사', '3급기관사 (3급기관사)')
    interface.yearFromFilter = _Combo(2025, '2025')
    interface.yearToFilter = _Combo(2025, '2025')
    interface.subjectFilter = _Combo('engine1', '기관1 (engine1)')
    interface.randomCountSpin = _Spin(1)
    interface.shuffleChoices = _Check(False)

    exported = {}

    class Repo:
        def get_questions_with_choices(self, **kwargs):
            return [
                {
                    'id': 1,
                    'year': 2025,
                    'question_number': 1,
                    'question_text': '다음 중 옳은 것은?',
                    'group_id': 10,
                    'group_order': 1,
                    'group_shared_text': '같은 지문',
                    'image_path': None,
                    'choices': [],
                    'correct_answer': 5,
                },
                {
                    'id': 2,
                    'year': 2025,
                    'question_number': 2,
                    'question_text': '다음 중 옳은 것은?',
                    'group_id': 20,
                    'group_order': 1,
                    'group_shared_text': '같은 지문',
                    'image_path': None,
                    'choices': [],
                    'correct_answer': 1,
                },
            ]

    class Validator:
        def is_random_eligible(self, question):
            return question['correct_answer'] in (1, 2, 3, 4)

    class Exporter:
        def export(self, title, questions, file_path, shuffle_choices=False, sections=None):
            exported['questions'] = questions
            exported['sections'] = sections

    interface.repo = Repo()
    interface.validator = Validator()
    interface.exporter = Exporter()

    monkeypatch.setattr(
        'src.gui.interface.export.random.sample',
        lambda population, count: list(population)[:count],
    )
    monkeypatch.setattr(
        'src.gui.interface.export.QFileDialog.getSaveFileName',
        lambda *_args, **_kwargs: ('C:/tmp/out.docx', 'Word Documents (*.docx)'),
    )
    monkeypatch.setattr(
        'src.gui.interface.export.InfoBar.success',
        lambda **_kwargs: None,
    )

    interface.export_docx()

    assert [question['id'] for question in exported['questions']] == [2]
    assert exported['sections'] is None


def test_export_docx_multi_subject_random_keeps_duplicate_text_group_atomic(monkeypatch):
    interface = ExportInterface.__new__(ExportInterface)
    interface.examFilter = _Combo('3급기관사', '3급기관사 (3급기관사)')
    interface.yearFromFilter = _Combo(2025, '2025')
    interface.yearToFilter = _Combo(2025, '2025')
    interface.subjectFilter = _Combo(None, 'All subjects')
    interface.randomCountSpin = _Spin(0)
    interface.shuffleChoices = _Check(False)
    interface.subjectSelectionRows = [
        _subject_request('engine1', '기관1', 2),
        _subject_request('engine2', '기관2', 1),
    ]

    exported = {'calls': []}

    class Repo:
        def get_questions_with_choices(self, **kwargs):
            exported['calls'].append(kwargs)
            if kwargs['subject_code'] == 'engine1':
                return [
                    {
                        'id': 1,
                        'year': 2025,
                        'question_number': 1,
                        'question_text': '같은 공통 발문',
                        'group_id': 10,
                        'group_order': 2,
                        'group_shared_text': '공통 지문 본문',
                        'image_path': None,
                        'choices': [],
                        'correct_answer': 1,
                    },
                    {
                        'id': 2,
                        'year': 2025,
                        'question_number': 2,
                        'question_text': '같은 공통 발문',
                        'group_id': 10,
                        'group_order': 1,
                        'group_shared_text': '공통 지문 본문',
                        'image_path': None,
                        'choices': [],
                        'correct_answer': 1,
                    },
                    {
                        'id': 3,
                        'year': 2025,
                        'question_number': 3,
                        'question_text': '단독 대체 문제',
                        'image_path': None,
                        'choices': [],
                        'correct_answer': 1,
                    },
                ]
            if kwargs['subject_code'] == 'engine2':
                return [
                    {
                        'id': 4,
                        'year': 2025,
                        'question_number': 1,
                        'question_text': '같은 공통 발문',
                        'group_id': 20,
                        'group_order': 1,
                        'group_shared_text': '기관2의 다른 공통 지문',
                        'image_path': None,
                        'choices': [],
                        'correct_answer': 1,
                    },
                ]
            return []

    class Validator:
        def is_random_eligible(self, question):
            return True

    class Exporter:
        def export(self, title, questions, file_path, shuffle_choices=False, sections=None):
            exported['questions'] = questions
            exported['sections'] = sections

    interface.repo = Repo()
    interface.validator = Validator()
    interface.exporter = Exporter()

    monkeypatch.setattr(
        'src.gui.interface.export.random.sample',
        lambda population, count: list(population)[:count],
    )
    monkeypatch.setattr(
        'src.gui.interface.export.QFileDialog.getSaveFileName',
        lambda *_args, **_kwargs: ('C:/tmp/out.docx', 'Word Documents (*.docx)'),
    )
    monkeypatch.setattr(
        'src.gui.interface.export.InfoBar.success',
        lambda **_kwargs: None,
    )

    interface.export_docx()

    assert [question['id'] for question in exported['questions']] == [2, 1, 4]
    assert [(section['title'], [q['id'] for q in section['questions']]) for section in exported['sections']] == [
        ('기관1', [2, 1]),
        ('기관2', [4]),
    ]


def test_export_docx_skips_duplicate_random_questions_across_subject_sections(monkeypatch):
    interface = ExportInterface.__new__(ExportInterface)
    interface.examFilter = _Combo('3급기관사', '3급기관사 (3급기관사)')
    interface.yearFromFilter = _Combo(2024, '2024')
    interface.yearToFilter = _Combo(2025, '2025')
    interface.subjectFilter = _Combo(None, 'All subjects')
    interface.randomCountSpin = _Spin(0)
    interface.shuffleChoices = _Check(False)
    interface.subjectSelectionRows = [
        _subject_request('engine1', '기관1', 1),
        _subject_request('engine2', '기관2', 1),
    ]

    exported = {'calls': []}

    class Repo:
        def get_questions_with_choices(self, **kwargs):
            exported['calls'].append(kwargs)
            if kwargs['subject_code'] == 'engine1':
                return [
                    {
                        'id': 1,
                        'year': 2024,
                        'session': 1,
                        'question_text': '회차만 다른 반복 문제',
                        'image_path': None,
                        'choices': [],
                        'correct_answer': 1,
                    }
                ]
            if kwargs['subject_code'] == 'engine2':
                return [
                    {
                        'id': 2,
                        'year': 2025,
                        'session': 2,
                        'question_text': '회차만 다른 반복 문제',
                        'image_path': None,
                        'choices': [],
                        'correct_answer': 1,
                    },
                    {
                        'id': 3,
                        'year': 2025,
                        'session': 2,
                        'question_text': '대체 가능한 기관2 문제',
                        'image_path': None,
                        'choices': [],
                        'correct_answer': 1,
                    },
                ]
            return []

    class Validator:
        def is_random_eligible(self, question):
            return True

    class Exporter:
        def export(self, title, questions, file_path, shuffle_choices=False, sections=None):
            exported['questions'] = questions
            exported['sections'] = sections

    interface.repo = Repo()
    interface.validator = Validator()
    interface.exporter = Exporter()

    monkeypatch.setattr(
        'src.gui.interface.export.random.sample',
        lambda population, count: list(population)[:count],
    )
    monkeypatch.setattr(
        'src.gui.interface.export.QFileDialog.getSaveFileName',
        lambda *_args, **_kwargs: ('C:/tmp/out.docx', 'Word Documents (*.docx)'),
    )
    monkeypatch.setattr(
        'src.gui.interface.export.InfoBar.success',
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        'src.gui.interface.export.InfoBar.warning',
        lambda **_kwargs: None,
    )

    interface.export_docx()

    assert [q['id'] for q in exported['questions']] == [1, 3]
    assert [(section['title'], [q['id'] for q in section['questions']]) for section in exported['sections']] == [
        ('기관1', [1]),
        ('기관2', [3]),
    ]


def test_export_docx_requires_positive_count_for_selected_random_subject(monkeypatch):
    interface = ExportInterface.__new__(ExportInterface)
    interface.examFilter = _Combo('3급기관사', '3급기관사 (3급기관사)')
    interface.yearFromFilter = _Combo(2025, '2025')
    interface.yearToFilter = _Combo(2025, '2025')
    interface.subjectFilter = _Combo(None, 'All subjects')
    interface.randomCountSpin = _Spin(0)
    interface.shuffleChoices = _Check(False)
    interface.subjectSelectionRows = [
        _subject_request('engine1', '기관1', 0),
    ]
    interface.repo = type('Repo', (), {'get_questions_with_choices': lambda self, **kwargs: []})()

    errors = []

    monkeypatch.setattr(
        'src.gui.interface.export.InfoBar.error',
        lambda **kwargs: errors.append(kwargs),
    )
    monkeypatch.setattr(
        'src.gui.interface.export.InfoBar.warning',
        lambda **_kwargs: None,
    )

    interface.export_docx()

    assert errors[0]['title'] == "Invalid random count"
