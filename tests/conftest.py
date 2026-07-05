from pathlib import Path
from types import SimpleNamespace

import pytest

from src.database.repository import ExamRepository
from src.parser.question import Choice, Question


@pytest.fixture()
def sample_metadata():
    return SimpleNamespace(year=2024, session=1, exam_type='3급기관사')


@pytest.fixture()
def repo(tmp_path: Path):
    db_path = tmp_path / "exam_bank.db"
    repository = ExamRepository(str(db_path))
    repository.init_database()
    return repository


@pytest.fixture()
def sample_question():
    return Question(
        number=1,
        text="기관 출력 계산 문제",
        choices=[
            Choice(number=1, symbol='㉮', text='10'),
            Choice(number=2, symbol='㉯', text='20'),
            Choice(number=3, symbol='㉴', text='30'),
            Choice(number=4, symbol='㉵', text='40'),
        ],
        correct_answer=2,
        subject_name='기관1',
        year=2024,
        session=1,
        exam_type='3급기관사',
    )
