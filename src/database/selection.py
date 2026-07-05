"""Question selection helpers shared by export and mock exam generation."""

from dataclasses import dataclass
import random
import re
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple


def _canonical_text(value) -> str:
    text = str(value or "").lower()
    text = re.sub(r"\[[^\]]*제\d+과목[^\]]*\]", "", text)
    text = re.sub(r"\(([a-z])\)", "", text)
    text = re.sub(r"[㉮㉯㉴㉵]", "", text)
    text = re.sub(r"[-‐‑‒–—−]", "", text)
    text = re.sub(r"[\s\.,,!?？:;·ㆍ'\"“”‘’()\[\]{}<>/\\]", "", text)
    return text


def question_content_key(question: Dict) -> Tuple:
    """Build a stable key for detecting the same problem across records."""
    return (
        _canonical_text(question.get('question_text') or question.get('text')),
    )


@dataclass
class SelectionUnit:
    """Atomic random-selection unit."""

    type: str
    question_ids: List[Any]
    count: int
    questions: List[Dict]
    group_id: Any = None
    first_index: int = 0
    content_keys: Tuple[Tuple, ...] = ()


def dedupe_questions_by_content(questions: Iterable[Dict]) -> List[Dict]:
    """Keep the first record for each logical problem."""
    deduped = []
    seen = set()
    for question in questions:
        key = question_content_key(question)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(question)
    return deduped


def dedupe_group_aware_questions_by_content(questions: Iterable[Dict]) -> List[Dict]:
    """Keep first non-duplicate selection units while preserving group children."""
    deduped = []
    seen = set()
    for unit in build_selection_units(questions):
        unit_keys = set(unit.content_keys)
        if seen.intersection(unit_keys):
            continue
        seen.update(unit_keys)
        deduped.extend(unit.questions)
    return deduped


def selection_content_keys(questions: Iterable[Dict]) -> Set[Tuple]:
    """Return duplicate-detection keys for already selected atomic units."""
    keys = set()
    for unit in build_selection_units(questions):
        keys.update(unit.content_keys)
    return keys


def filter_random_eligible_questions(questions: Iterable[Dict], validator) -> List[Dict]:
    """Remove questions with blocking validation errors from random pools."""
    return [
        question
        for question in questions
        if validator.is_random_eligible(question)
    ]


def filter_group_aware_random_eligible_questions(
    questions: Iterable[Dict],
    validator,
) -> List[Dict]:
    """Remove entire selection units when any child has blocking errors."""
    eligible = []
    for unit in build_selection_units(questions):
        if all(validator.is_random_eligible(question) for question in unit.questions):
            eligible.extend(unit.questions)
    return eligible


def build_selection_units(
    questions: Iterable[Dict],
    excluded_keys: Optional[Set[Tuple]] = None,
    key_func: Callable[[Dict], Tuple] = question_content_key,
) -> List[SelectionUnit]:
    """Group questions into atomic units for random selection."""
    entries = []
    groups = {}
    excluded_keys = excluded_keys or set()

    for index, question in enumerate(questions or []):
        group_id = question.get('group_id')
        if group_id is None:
            unit = _make_selection_unit(
                'single',
                [question],
                first_index=index,
                key_func=key_func,
            )
            entries.append(unit)
            continue

        if group_id not in groups:
            groups[group_id] = []
            entries.append(group_id)
        groups[group_id].append((index, question))

    units = []
    for entry in entries:
        if isinstance(entry, SelectionUnit):
            unit = entry
        else:
            indexed_questions = sorted(groups[entry], key=_group_question_sort_key)
            unit = _make_selection_unit(
                'group',
                [question for _index, question in indexed_questions],
                group_id=entry,
                first_index=min(index for index, _question in groups[entry]),
                key_func=key_func,
            )

        if excluded_keys and any(key in excluded_keys for key in unit.content_keys):
            continue
        units.append(unit)

    return units


def count_group_aware_questions(
    questions: Iterable[Dict],
    excluded_keys: Optional[Set[Tuple]] = None,
    key_func: Callable[[Dict], Tuple] = question_content_key,
) -> int:
    """Count questions available after group-aware duplicate filtering."""
    return sum(
        unit.count
        for unit in build_selection_units(
            questions,
            excluded_keys=excluded_keys,
            key_func=key_func,
        )
    )


def select_group_aware_questions(
    questions: Iterable[Dict],
    count: int,
    rng=None,
    excluded_keys: Optional[Set[Tuple]] = None,
) -> List[Dict]:
    """Randomly select exactly count child questions without splitting groups."""
    if count < 0:
        raise ValueError("Question count must be non-negative.")
    if count == 0:
        return []

    units = build_selection_units(questions, excluded_keys=excluded_keys)
    candidate_units = [unit for unit in units if unit.count <= count]
    available_count = sum(unit.count for unit in candidate_units)
    if available_count < count:
        raise ValueError(
            f"Not enough questions available for group-aware selection ({available_count}/{count})"
        )

    rng = rng or random
    randomized_units = list(rng.sample(candidate_units, len(candidate_units)))
    selected_units = _select_exact_unit_count(randomized_units, count)
    if selected_units is None:
        raise ValueError(
            f"Not enough questions available for group-aware selection ({available_count}/{count})"
        )

    selected_units = sorted(selected_units, key=lambda unit: unit.first_index)
    selected_questions = []
    for unit in selected_units:
        selected_questions.extend(unit.questions)
    return selected_questions


def _make_selection_unit(
    unit_type: str,
    questions: List[Dict],
    first_index: int,
    key_func: Callable[[Dict], Tuple],
    group_id=None,
) -> SelectionUnit:
    if unit_type == 'group':
        content_keys = (_group_content_key(questions, key_func),)
    else:
        content_keys = tuple(key_func(question) for question in questions)

    return SelectionUnit(
        type=unit_type,
        question_ids=[question.get('id') for question in questions],
        count=len(questions),
        questions=questions,
        group_id=group_id,
        first_index=first_index,
        content_keys=content_keys,
    )


def _group_content_key(
    questions: List[Dict],
    key_func: Callable[[Dict], Tuple],
) -> Tuple:
    shared_texts = []
    seen_shared_texts = set()
    for question in questions:
        shared_text = _canonical_text(
            question.get('shared_passage')
            or question.get('group_shared_text')
            or question.get('shared_text')
        )
        if shared_text and shared_text not in seen_shared_texts:
            seen_shared_texts.add(shared_text)
            shared_texts.append(shared_text)
    return (
        'group',
        tuple(shared_texts),
        tuple(key_func(question) for question in questions),
    )


def _group_question_sort_key(indexed_question):
    index, question = indexed_question
    group_order = _int_or_none(question.get('group_order'))
    if group_order is not None:
        return (0, group_order, index)

    question_number = _int_or_none(question.get('question_number'))
    if question_number is not None:
        return (1, question_number, index)

    return (2, index, index)


def _int_or_none(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _select_exact_unit_count(units: List[SelectionUnit], count: int):
    paths = {0: []}
    for unit in units:
        if unit.count > count:
            continue
        for total, path in list(paths.items()):
            new_total = total + unit.count
            if new_total > count or new_total in paths:
                continue
            paths[new_total] = path + [unit]
        if count in paths:
            return paths[count]
    return paths.get(count)
