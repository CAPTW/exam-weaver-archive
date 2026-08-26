from __future__ import annotations

import copy
import json
import random
from typing import Any, Optional

from ..parser.patterns import CHOICE_SYMBOL_TO_NUMBER, NUMBER_TO_CHOICE_SYMBOL
from ..parser.question import ALL_CHOICES_CORRECT
from .exam_document import (
    AnswerKeyEntry,
    ExamChoice,
    ExamDocument,
    ExamSection,
    QuestionBlock,
    SharedPassageBlock,
)


def split_title(title: Any) -> tuple[str, ...]:
    lines = [line.strip() for line in str(title).splitlines() if line.strip()]
    return tuple(lines or [""])


def freeze_format_payload(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return json.dumps(copy.deepcopy(value), ensure_ascii=False, sort_keys=True)
    return copy.deepcopy(value)


def normalize_choice(choice: Any) -> dict:
    if isinstance(choice, dict):
        data = dict(choice)
        orig_number = data.get("choice_number")
        if orig_number is None and data.get("choice_symbol"):
            orig_number = CHOICE_SYMBOL_TO_NUMBER.get(data["choice_symbol"])
        data["_orig_number"] = orig_number
        data["choice_image_path"] = data.get("choice_image_path") or data.get("image_path")
        data["choice_format_json"] = data.get("choice_format_json") or data.get("format_json")
        return data

    orig_number = getattr(choice, "number", None)
    if orig_number is None:
        sym = getattr(choice, "symbol", None)
        if sym:
            orig_number = CHOICE_SYMBOL_TO_NUMBER.get(sym)
    return {
        "choice_number": getattr(choice, "number", None),
        "choice_symbol": getattr(choice, "symbol", None),
        "choice_text": getattr(choice, "text", None),
        "choice_image_path": getattr(choice, "choice_image_path", None)
        or getattr(choice, "image_path", None),
        "choice_format_json": getattr(choice, "choice_format_json", None)
        or getattr(choice, "format_json", None),
        "_orig_number": orig_number,
    }


def _shared_passage_text(question: dict) -> str:
    return question.get("shared_passage") or question.get("group_shared_text") or ""


def _shared_image_path(question: dict) -> Optional[str]:
    return (
        question.get("group_image_path")
        or question.get("shared_image_path")
        or question.get("group_shared_image")
        or None
    )


def _choice_from_normalized(data: dict) -> ExamChoice:
    number = data.get("choice_number")
    symbol = data.get("choice_symbol") or ""
    return ExamChoice(
        number=number,
        original_number=data.get("_orig_number"),
        symbol=str(symbol or ""),
        text=data.get("choice_text") or "",
        format_json=freeze_format_payload(data.get("choice_format_json")),
        image_path=data.get("choice_image_path"),
    )


class ExamDocumentBuilder:
    def __init__(self, rng: Optional[random.Random] = None):
        self._rng = rng

    def build(
        self,
        title: str,
        questions: Optional[list] = None,
        sections: Optional[list] = None,
        shuffle_choices: bool = False,
        include_answer_key: bool = False,
        rng: Optional[random.Random] = None,
    ) -> ExamDocument:
        questions = list(questions or [])
        active_rng = rng if rng is not None else self._rng
        document_sections: list[ExamSection] = []
        answer_key: list[AnswerKeyEntry] = []
        display_number = 1

        if sections:
            source_sections = sections
        else:
            source_sections = [{"title": None, "questions": questions}]

        for section_spec in source_sections:
            spec = section_spec or {}
            raw_title = spec.get("title")
            section_title = str(raw_title).strip() if raw_title else None
            last_group_id = None
            blocks: list[Any] = []
            for question in spec.get("questions") or []:
                group_id = question.get("group_id")
                shared_text = _shared_passage_text(question)
                if group_id is not None and shared_text and group_id != last_group_id:
                    blocks.append(
                        SharedPassageBlock(
                            group_id=group_id,
                            text=str(shared_text),
                            image_path=_shared_image_path(question),
                        )
                    )
                last_group_id = group_id if group_id is not None else None

                question_type = question.get("question_type")
                choices_in = question.get("choices") or []
                normalized = [normalize_choice(choice) for choice in choices_in]
                correct_answer = question.get("correct_answer")

                if question_type != "descriptive" and shuffle_choices and len(normalized) == 4:
                    shuffle_rng = active_rng or random.Random()
                    shuffle_rng.shuffle(normalized)
                    if correct_answer is not None and correct_answer != ALL_CHOICES_CORRECT:
                        remapped = None
                        for idx, choice in enumerate(normalized, start=1):
                            if choice.get("_orig_number") == correct_answer:
                                remapped = idx
                                break
                        correct_answer = remapped
                    for idx, choice in enumerate(normalized, start=1):
                        choice["choice_number"] = idx
                        choice["choice_symbol"] = NUMBER_TO_CHOICE_SYMBOL.get(idx, str(idx))

                model_answer = str(question.get("model_answer") or "").strip() or None
                blocks.append(
                    QuestionBlock(
                        display_number=display_number,
                        source_question_id=question.get("id"),
                        question_number=question.get("question_number"),
                        question_type=question_type,
                        text=question.get("question_text", "") or "",
                        format_json=freeze_format_payload(question.get("question_format_json")),
                        image_path=question.get("image_path"),
                        choices=tuple(_choice_from_normalized(choice) for choice in normalized)
                        if question_type != "descriptive"
                        else (),
                        correct_answer=correct_answer,
                        answer_available=question.get("answer_available"),
                        model_answer=model_answer,
                        group_id=group_id,
                    )
                )
                answer_key.append(
                    AnswerKeyEntry(
                        display_number=display_number,
                        question_type=question_type,
                        correct_answer=correct_answer,
                        answer_available=question.get("answer_available"),
                    )
                )
                display_number += 1
            document_sections.append(ExamSection(title=section_title, blocks=tuple(blocks)))

        return ExamDocument(
            title_lines=split_title(title),
            sections=tuple(document_sections),
            answer_key=tuple(answer_key),
            include_answer_key=include_answer_key,
        )
