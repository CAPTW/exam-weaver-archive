"""Question selection helpers shared by export and mock exam generation."""

from dataclasses import dataclass
from difflib import SequenceMatcher
import random
import re
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple


QUESTION_FINGERPRINT_KIND = 'question'
GROUP_FINGERPRINT_KIND = 'group'
MIN_FUZZY_PROMPT_LENGTH = 18
MIN_PROMPT_SIMILARITY = 0.90
MIN_CHOICE_SIMILARITY = 0.92
MIN_COMBINED_SIMILARITY = 0.95
MIN_DESCRIPTIVE_PROMPT_SIMILARITY = 0.97
PROMPT_SIMILARITY_WEIGHT = 0.55
CHOICE_SIMILARITY_WEIGHT = 0.45
NEGATIVE_PROMPT_MARKERS = (
    '옳지않',
    '아닌',
    '틀린',
    '잘못된',
    '부적절',
    '하지않',
    '없는것',
    '제외한',
    '제외되는',
    '불가능',
)


def _canonical_text(value) -> str:
    text = str(value or "").lower()
    text = re.sub(r"\[[^\]]*제\d+과목[^\]]*\]", "", text)
    text = re.sub(r"\(([a-z])\)", "", text)
    text = re.sub(r"[㉮㉯㉴㉵]", "", text)
    text = re.sub(r"[-‐‑‒–—−]", "", text)
    text = re.sub(r"[\s\.,,!?？:;·ㆍ'\"“”‘’()\[\]{}<>/\\]", "", text)
    return text


def _choice_fingerprint(question: Dict) -> Tuple[str, ...]:
    normalized_choices = []
    for choice in question.get('choices') or []:
        if isinstance(choice, dict):
            value = choice.get('choice_text') or choice.get('text')
        else:
            value = getattr(choice, 'choice_text', None) or getattr(choice, 'text', None)
        normalized = _canonical_text(value)
        if normalized:
            normalized_choices.append(normalized)
    return tuple(sorted(normalized_choices))


def _prompt_semantic_anchors(value) -> Tuple[Tuple[str, ...], bool]:
    text = str(value or '').lower()
    number_text = re.sub(r'(?<=\d),(?=\d)', '', text)
    numbers = tuple(re.findall(r'\d+(?:\.\d+)?', number_text))
    compact = re.sub(r'\s+', '', text)
    has_negative_polarity = any(marker in compact for marker in NEGATIVE_PROMPT_MARKERS)
    has_negative_polarity = has_negative_polarity or bool(
        re.search(r'\b(?:not|incorrect|wrong|except|least)\b', text)
    )
    return numbers, has_negative_polarity


def question_content_key(question: Dict) -> Tuple:
    """Build a normalized prompt-and-choice fingerprint for a problem."""
    prompt = question.get('question_text') or question.get('text')
    return (
        QUESTION_FINGERPRINT_KIND,
        _canonical_text(prompt),
        _choice_fingerprint(question),
        _prompt_semantic_anchors(prompt),
    )


def _text_similarity(first: str, second: str, minimum: float = 0.0) -> float:
    if not first or not second:
        return 0.0
    if first == second:
        return 1.0
    matcher = SequenceMatcher(None, first, second, autojunk=False)
    if minimum:
        if matcher.real_quick_ratio() < minimum:
            return 0.0
        if matcher.quick_ratio() < minimum:
            return 0.0
    return matcher.ratio()


def _question_fingerprints_are_logical_duplicates(first: Tuple, second: Tuple) -> bool:
    if len(first) != 4 or len(second) != 4:
        return False

    _first_kind, first_prompt, first_choices, first_anchors = first
    _second_kind, second_prompt, second_choices, second_anchors = second
    if first_anchors != second_anchors:
        return False
    if min(len(first_prompt), len(second_prompt)) < MIN_FUZZY_PROMPT_LENGTH:
        return False

    if first_choices or second_choices:
        if (
            not first_choices
            or not second_choices
            or len(first_choices) != len(second_choices)
        ):
            return False
        if first_choices == second_choices:
            choice_similarity = 1.0
        else:
            choice_similarity = _text_similarity(
                '\x1f'.join(first_choices),
                '\x1f'.join(second_choices),
                minimum=MIN_CHOICE_SIMILARITY,
            )
            if choice_similarity < MIN_CHOICE_SIMILARITY:
                return False
        prompt_similarity = _text_similarity(
            first_prompt,
            second_prompt,
            minimum=MIN_PROMPT_SIMILARITY,
        )
        combined_similarity = (
            PROMPT_SIMILARITY_WEIGHT * prompt_similarity
            + CHOICE_SIMILARITY_WEIGHT * choice_similarity
        )
        return (
            prompt_similarity >= MIN_PROMPT_SIMILARITY
            and choice_similarity >= MIN_CHOICE_SIMILARITY
            and combined_similarity >= MIN_COMBINED_SIMILARITY
        )

    return _text_similarity(
        first_prompt,
        second_prompt,
        minimum=MIN_DESCRIPTIVE_PROMPT_SIMILARITY,
    ) >= MIN_DESCRIPTIVE_PROMPT_SIMILARITY


def _group_fingerprints_are_logical_duplicates(first: Tuple, second: Tuple) -> bool:
    if len(first) != 3 or len(second) != 3:
        return False

    _first_kind, first_shared_texts, first_children = first
    _second_kind, second_shared_texts, second_children = second
    if len(first_children) != len(second_children):
        return False
    if not all(
        _content_keys_are_logical_duplicates(first_child, second_child)
        for first_child, second_child in zip(first_children, second_children)
    ):
        return False

    if first_shared_texts == second_shared_texts:
        return True
    if not first_shared_texts or not second_shared_texts:
        return False

    first_shared = '\x1f'.join(first_shared_texts)
    second_shared = '\x1f'.join(second_shared_texts)
    if min(len(first_shared), len(second_shared)) < MIN_FUZZY_PROMPT_LENGTH:
        return False
    return _text_similarity(
        first_shared,
        second_shared,
        minimum=MIN_DESCRIPTIVE_PROMPT_SIMILARITY,
    ) >= MIN_DESCRIPTIVE_PROMPT_SIMILARITY


def _content_keys_are_logical_duplicates(first: Tuple, second: Tuple) -> bool:
    if first == second:
        return True
    if not first or not second or first[0] != second[0]:
        return False
    if first[0] == QUESTION_FINGERPRINT_KIND:
        return _question_fingerprints_are_logical_duplicates(first, second)
    if first[0] == GROUP_FINGERPRINT_KIND:
        return _group_fingerprints_are_logical_duplicates(first, second)
    return False


def _contains_logical_duplicate(key: Tuple, existing_keys: Iterable[Tuple]) -> bool:
    return any(
        _content_keys_are_logical_duplicates(key, existing_key)
        for existing_key in existing_keys
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
    seen = []
    for question in questions:
        key = question_content_key(question)
        if _contains_logical_duplicate(key, seen):
            continue
        seen.append(key)
        deduped.append(question)
    return deduped


def dedupe_group_aware_questions_by_content(questions: Iterable[Dict]) -> List[Dict]:
    """Keep first non-duplicate selection units while preserving group children."""
    deduped = []
    seen = []
    for unit in build_selection_units(questions):
        unit_keys = tuple(unit.content_keys)
        if any(_contains_logical_duplicate(key, seen) for key in unit_keys):
            continue
        seen.extend(unit_keys)
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

        if excluded_keys and any(
            _contains_logical_duplicate(key, excluded_keys)
            for key in unit.content_keys
        ):
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
        GROUP_FINGERPRINT_KIND,
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
