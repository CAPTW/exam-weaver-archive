from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Union


@dataclass(frozen=True, slots=True)
class ExamChoice:
    number: Optional[int]
    original_number: Optional[int]
    symbol: str
    text: str
    format_json: Any
    image_path: Optional[str]


@dataclass(frozen=True, slots=True)
class SharedPassageBlock:
    group_id: Any
    text: str
    image_path: Optional[str] = None


@dataclass(frozen=True, slots=True)
class QuestionBlock:
    display_number: int
    source_question_id: Any
    question_number: Any
    question_type: Optional[str]
    text: str
    format_json: Any
    image_path: Optional[str]
    choices: tuple[ExamChoice, ...]
    correct_answer: Any
    answer_available: Any
    model_answer: Optional[str]
    group_id: Any


@dataclass(frozen=True, slots=True)
class ExamSection:
    title: Optional[str]
    blocks: tuple[Union[SharedPassageBlock, QuestionBlock], ...]


@dataclass(frozen=True, slots=True)
class AnswerKeyEntry:
    display_number: int
    question_type: Optional[str]
    correct_answer: Any
    answer_available: Any


@dataclass(frozen=True, slots=True)
class ExamDocument:
    title_lines: tuple[str, ...]
    sections: tuple[ExamSection, ...]
    answer_key: tuple[AnswerKeyEntry, ...]
    include_answer_key: bool
