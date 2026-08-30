from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

from src.exporter.exam_document import (
    AnswerKeyEntry,
    ExamChoice,
    ExamDocument,
    ExamSection,
    QuestionBlock,
    SharedPassageBlock,
)


def four_choices() -> tuple[ExamChoice, ...]:
    return tuple(
        ExamChoice(
            number=number,
            original_number=number,
            symbol=symbol,
            text=text,
            format_json=None,
            image_path=None,
        )
        for number, symbol, text in (
            (1, "㉮", "기관실"),
            (2, "㉯", "선교"),
            (3, "㉴", "갑판"),
            (4, "㉵", "조타실"),
        )
    )


def minimal_document(*, include_answer_key: bool = False) -> ExamDocument:
    question = QuestionBlock(
        display_number=1,
        source_question_id=101,
        question_number=77,
        question_type="objective",
        text="당직 장소는 어디인가?",
        format_json=None,
        image_path=None,
        choices=four_choices(),
        correct_answer=2,
        answer_available=True,
        model_answer=None,
        group_id=None,
    )
    return ExamDocument(
        title_lines=("2026 모의고사",),
        sections=(ExamSection("기관", (question,)),),
        answer_key=(AnswerKeyEntry(1, "objective", 2, True),),
        include_answer_key=include_answer_key,
    )


def numbered_choices(count: int, *, reverse_provenance: bool = False) -> tuple[ExamChoice, ...]:
    choices = []
    for number in range(1, count + 1):
        original = count - number + 1 if reverse_provenance else number
        choices.append(ExamChoice(number, original, str(number), f"선택-{number}", None, None))
    return tuple(choices)


def semantic_document() -> ExamDocument:
    shared = SharedPassageBlock(group_id="group-private-id", text="공통 안전 수칙")
    objective = QuestionBlock(
        display_number=7,
        source_question_id="db-private-7",
        question_number=700,
        question_type="objective",
        text="당직자는 무엇을 확인하는가?",
        format_json=None,
        image_path=None,
        choices=numbered_choices(4, reverse_provenance=True),
        correct_answer=3,
        answer_available=True,
        model_answer=None,
        group_id="group-private-id",
    )
    descriptive = QuestionBlock(
        display_number=8,
        source_question_id="db-private-8",
        question_number=800,
        question_type="descriptive",
        text="복원성을 설명하시오.\n두 문장으로 쓰시오.",
        format_json=None,
        image_path=None,
        choices=(),
        correct_answer=0,
        answer_available=True,
        model_answer="원위치로 돌아오려는 성질",
        group_id=None,
    )
    english = QuestionBlock(
        display_number=9,
        source_question_id=9,
        question_number=9,
        question_type="objective",
        text="Choose the correct signal.",
        format_json=None,
        image_path=None,
        choices=numbered_choices(5),
        correct_answer=5,
        answer_available=True,
        model_answer=None,
        group_id=None,
    )
    return ExamDocument(
        title_lines=("2026 해기사", "기관사"),
        sections=(
            ExamSection("기관일반", (shared, objective, descriptive)),
            ExamSection("해사영어", (english,)),
        ),
        answer_key=(
            AnswerKeyEntry(7, "objective", 3, True),
            AnswerKeyEntry(8, "descriptive", 0, True),
            AnswerKeyEntry(9, "objective", 5, True),
        ),
        include_answer_key=False,
    )


def variable_choice_document() -> ExamDocument:
    questions = tuple(
        QuestionBlock(
            display_number=index,
            source_question_id=index,
            question_number=index,
            question_type="objective",
            text=f"보기 {count}개",
            format_json=None,
            image_path=None,
            choices=numbered_choices(count, reverse_provenance=True),
            correct_answer=count,
            answer_available=True,
            model_answer=None,
            group_id=None,
        )
        for index, count in enumerate((4, 5, 10), start=1)
    )
    return ExamDocument(
        title_lines=("가변 보기",),
        sections=(ExamSection(None, questions),),
        answer_key=tuple(
            AnswerKeyEntry(question.display_number, "objective", question.correct_answer, True)
            for question in questions
        ),
        include_answer_key=False,
    )
def zip_names(path: Path) -> list[str]:
    with ZipFile(path) as package:
        return package.namelist()


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
