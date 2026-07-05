import json
from pathlib import Path

import pytest

from src.parser.question import Choice, Question
from src.web_import.models import ComcbtParsedExam, ComcbtQuestionGroup
from src.web_import.quality import evaluate_parsed_exam, write_quality_report


def _choices() -> list[Choice]:
    return [
        Choice(number=1, symbol="㉮", text="A"),
        Choice(number=2, symbol="㉯", text="B"),
        Choice(number=3, symbol="㉴", text="C"),
        Choice(number=4, symbol="㉵", text="D"),
    ]


def _five_choices() -> list[Choice]:
    return [
        Choice(number=1, symbol="㉮", text="A"),
        Choice(number=2, symbol="㉯", text="B"),
        Choice(number=3, symbol="㉴", text="C"),
        Choice(number=4, symbol="㉵", text="D"),
        Choice(number=5, symbol="⑤", text="E"),
    ]


def _question(number: int = 1, **overrides) -> Question:
    data = {
        "number": number,
        "text": f"Question {number}",
        "choices": _choices(),
        "correct_answer": 1,
        "subject_name": "Sample Subject",
        "year": 2025,
        "session": 1,
        "exam_type": "Sample Exam",
    }
    data.update(overrides)
    return Question(**data)


def _exam(
    questions: list[Question] | None = None,
    groups: list[ComcbtQuestionGroup] | None = None,
    diagnostics: dict[str, object] | None = None,
) -> ComcbtParsedExam:
    return ComcbtParsedExam(
        title="Sample",
        source_url="https://www.comcbt.com/xe/wc/8837719",
        exam_type="Sample Exam",
        subject_name="Sample Subject",
        year=2025,
        session=1,
        questions=questions if questions is not None else [_question()],
        attachments=[],
        groups=groups or [],
        diagnostics=diagnostics or {},
    )


@pytest.mark.parametrize(
    ("parsed_exam", "error_code"),
    [
        (_exam([]), "question_count"),
        (_exam([_question(text="")]), "blank_question_text"),
        (_exam([_question(choices=_choices()[:3])]), "choice_count"),
        (_exam([_question(correct_answer=5)]), "invalid_correct_answer"),
        (_exam([_question(has_image=True, image_path=None)]), "missing_question_image"),
        (_exam(diagnostics={"invalid_group_range": True}), "invalid_group_range"),
        (_exam(diagnostics={"ambiguous_group_range": True}), "ambiguous_group_range"),
    ],
)
def test_quality_gate_rejects_blocking_parse_and_question_errors(parsed_exam, error_code):
    report = evaluate_parsed_exam(parsed_exam)

    assert report.importable is False
    assert any(error_code in error for error in report.errors)


def test_quality_gate_accepts_five_choice_question():
    report = evaluate_parsed_exam(
        _exam([_question(choices=_five_choices(), correct_answer=5)])
    )

    assert report.importable is True
    assert report.errors == []


def test_quality_gate_accepts_textual_next_description_without_image():
    report = evaluate_parsed_exam(
        _exam([_question(text="다음 설명에 해당하는 업무시설의 코어 형식은?", has_image=False)])
    )

    assert report.importable is True
    assert report.errors == []


def test_quality_gate_accepts_generic_circuit_text_without_image():
    report = evaluate_parsed_exam(
        _exam([_question(text="어떤 회로의 유효전력에 대한 설명으로 옳은 것은?", has_image=False)])
    )

    assert report.importable is True
    assert report.errors == []


def test_quality_gate_accepts_generic_psychrometric_chart_term_without_image():
    report = evaluate_parsed_exam(
        _exam([_question(text="공기선도(psychrometric chart)와 관련된 설명으로 옳지 않은 것은?", has_image=False)])
    )

    assert report.importable is True
    assert report.errors == []


def test_quality_gate_rejects_explicit_next_circuit_without_image():
    report = evaluate_parsed_exam(
        _exam([_question(text="다음 회로에서 전류의 크기로 옳은 것은?", has_image=False)])
    )

    assert report.importable is False
    assert any("missing_question_image" in error for error in report.errors)


def test_quality_gate_rejects_blank_choice_except_image_placeholder():
    question = _question()
    question.choices = [
        Choice(number=1, symbol="㉮", text="A"),
        Choice(number=2, symbol="㉯", text=""),
        Choice(number=3, symbol="㉴", text="[이미지 선지]"),
        Choice(number=4, symbol="㉵", text="D"),
    ]

    report = evaluate_parsed_exam(_exam([question]))

    assert report.importable is False
    assert any("blank_choice_text" in error for error in report.errors)


def test_quality_gate_treats_image_choice_placeholder_as_image_requirement_not_blank_choice():
    question = _question()
    question.choices = [
        Choice(number=1, symbol="㉮", text="A"),
        Choice(number=2, symbol="㉯", text="[이미지 선지]"),
        Choice(number=3, symbol="㉴", text="C"),
        Choice(number=4, symbol="㉵", text="D"),
    ]

    report = evaluate_parsed_exam(_exam([question]))

    assert report.importable is False
    assert not any("blank_choice_text" in error for error in report.errors)
    assert any("missing_question_image" in error for error in report.errors)


def test_quality_gate_accepts_image_choice_placeholder_when_question_crop_exists():
    question = _question(image_path="images/q001.png")
    question.choices = [
        Choice(number=1, symbol="㉮", text="A"),
        Choice(number=2, symbol="㉯", text="[이미지 선지]"),
        Choice(number=3, symbol="㉴", text="C"),
        Choice(number=4, symbol="㉵", text="D"),
    ]

    report = evaluate_parsed_exam(_exam([question]))

    assert report.importable is True
    assert report.errors == []


def test_quality_gate_rejects_visual_hint_question_without_image_even_when_has_image_false():
    question = _question(text="다음 그래프를 보고 옳은 것은?", has_image=False)

    report = evaluate_parsed_exam(_exam([question]))

    assert report.importable is False
    assert any("missing_question_image" in error for error in report.errors)


def test_quality_gate_accepts_clean_grouped_exam_and_writes_json_report(tmp_path: Path):
    group = ComcbtQuestionGroup(
        group_id="group-1",
        text="공통 지문",
        child_numbers=[1, 2],
        range_start=1,
        range_end=2,
        explicit_range=True,
        ambiguous_range=False,
    )
    questions = [
        _question(number=1, group_id="group-1", group_order=1, shared_passage="공통 지문"),
        _question(number=2, correct_answer=2, group_id="group-1", group_order=2, shared_passage="공통 지문"),
    ]
    parsed_exam = _exam(
        questions=questions,
        groups=[group],
        diagnostics={"invalid_group_range": False, "ambiguous_group_range": False},
    )

    report = evaluate_parsed_exam(parsed_exam)
    output = write_quality_report(report, tmp_path / "quality.json")

    assert report.importable is True
    assert report.question_count == 2
    assert report.answer_count == 2
    assert report.group_count == 1
    assert report.errors == []
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["importable"] is True
    assert payload["group_count"] == 1


def test_quality_gate_rejects_inconsistent_group_children():
    group = ComcbtQuestionGroup(
        group_id="group-1",
        text="공통 지문",
        child_numbers=[1, 3],
        range_start=1,
        range_end=2,
        explicit_range=True,
    )
    questions = [
        _question(number=1, group_id="group-1", group_order=1, shared_passage="공통 지문"),
        _question(number=2, group_id="group-1", group_order=2, shared_passage="공통 지문"),
    ]

    report = evaluate_parsed_exam(_exam(questions=questions, groups=[group]))

    assert report.importable is False
    assert any("group_child_mismatch" in error for error in report.errors)
