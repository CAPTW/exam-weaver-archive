# src/parser/question.py
"""문제 텍스트 파싱"""

import re
import json
from typing import List, Optional, Tuple
from dataclasses import dataclass, field
from .patterns import (
    QUESTION_START, CHOICE_PATTERN, PAGE_NUMBER,
    CHOICE_SYMBOL_TO_NUMBER, EXAM_SUBJECT_ORDER
)
from .formatting import (
    apply_overline_marks,
    merge_spans,
    normalize_latex_text,
    repair_extracted_text_artifacts,
)

LEGACY_CHOICE_SYMBOL_TO_NUMBER = {
    '가': 1,
    '나': 2,
    '사': 3,
    '아': 4,
    # Common OCR miss for "가." in scanned pages.
    '卜': 1,
    # Common OCR miss for "아." in scanned 2019 PDFs.
    '0h': 4,
    'Oh': 4,
    'OH': 4,
    'oh': 4,
}

LEGACY_CHOICE_PATTERN = re.compile(
    r'(?<![A-Za-z0-9가-힣])'
    r'(가|나|사|아|卜|0h|Oh|OH|oh)\s*'
    r'(?:[\.\),，,]|(?=\s+[A-Za-z0-9\[\(]))'
)


@dataclass
class Choice:
    """선지"""
    number: int
    symbol: str
    text: str
    image_path: Optional[str] = None
    format_json: Optional[str] = None


@dataclass
class Question:
    """문제"""
    number: int
    text: str
    choices: List[Choice] = field(default_factory=list)
    correct_answer: Optional[int] = None
    has_image: bool = False
    image_path: Optional[str] = None  # Added image_path
    source_page: Optional[int] = None
    subject_name: Optional[str] = None
    year: Optional[int] = None
    session: Optional[int] = None
    exam_type: Optional[str] = None
    format_json: Optional[str] = None
    group_id: Optional[str] = None
    group_order: Optional[int] = None
    shared_passage: Optional[str] = None


@dataclass
class _QuestionStart:
    number: str
    start_pos: int
    end_pos: int

    def group(self, index: int) -> str:
        if index != 1:
            raise IndexError(index)
        return self.number

    def start(self) -> int:
        return self.start_pos

    def end(self) -> int:
        return self.end_pos


class QuestionParser:
    """문제 텍스트 파싱"""
    
    def __init__(self, exam_type: str):
        self.exam_type = exam_type
        self.subject_order = EXAM_SUBJECT_ORDER.get(exam_type, [])
    
    def parse_questions(self, pages: List, recover_missing: bool = True) -> List[Question]:
        """
        페이지들에서 문제 추출
        
        Args:
            pages: PageData 리스트
            
        Returns:
            Question 리스트
        """
        questions = []
        current_subject_idx = 0
        current_subject_count = 0
        prev_question_num = None
        
        # 전체 원본 텍스트 저장 (Gap Recovery용)
        all_raw_text = ""
        
        for page in pages:
            # 표지 페이지 건너뛰기
            if self._is_cover_page(page.text):
                continue
            
            all_raw_text += page.text + "\n"
            
            # 페이지에서 문제 추출 (이미지 경로 전달)
            page_questions = self._parse_page(
                page.text,
                page.number,
                page.image_paths,
                getattr(page, 'image_infos', None),
                getattr(page, 'underlined_texts', None),
                getattr(page, 'tables', None),
                getattr(page, 'overlined_texts', None)
            )
            
            for q in page_questions:
                # 과목 전환 감지 (1번 리셋)
                if prev_question_num is not None and q.number == 1 and prev_question_num >= 20:
                    current_subject_idx += 1
                    current_subject_count = 0
                elif current_subject_count >= 25:
                    current_subject_idx += 1
                    current_subject_count = 0
                
                # 과목 이름 할당
                if current_subject_idx < len(self.subject_order):
                    q.subject_name = self.subject_order[current_subject_idx]
                
                questions.append(q)
                current_subject_count += 1
                prev_question_num = q.number
        
        # Gap Recovery: 누락된 문제 복구
        if recover_missing:
            questions = self._recover_missing_questions(questions, all_raw_text)
        
        return questions
    
    def _is_cover_page(self, text: str) -> bool:
        """표지 페이지 판별"""
        if re.search(r'문\s*제\s*지', text):
            return True
        if QUESTION_START.search(text):
            return False
        indicators = ['자격시험', '정기시험', '기출']
        return any(ind in text for ind in indicators)
    
    def _recover_missing_questions(
        self, 
        questions: List[Question], 
        raw_text: str,
        expected_per_subject: int = 25
    ) -> List[Question]:
        """
        Gap Recovery: 누락된 문제 번호를 원본 텍스트에서 복구
        
        Args:
            questions: 초기 파싱된 문제 리스트
            raw_text: 전체 원본 텍스트
            expected_per_subject: 과목당 예상 문제 수 (기본 25)
            
        Returns:
            복구된 문제가 추가된 리스트
        """
        if not questions:
            return questions
        
        # 과목별로 그룹화
        by_subject = {}
        for q in questions:
            subj = q.subject_name or 'unknown'
            if subj not in by_subject:
                by_subject[subj] = []
            by_subject[subj].append(q)
        
        recovered = []
        
        for subject, subj_questions in by_subject.items():
            if subject == 'unknown':
                continue

            existing_nums = {q.number for q in subj_questions}
            expected_nums = set(range(1, expected_per_subject + 1))
            missing_nums = expected_nums - existing_nums
            
            if missing_nums:
                # 누락된 번호마다 타겟 검색
                for num in missing_nums:
                    # 패턴: "N." 다음에 문제 내용
                    pattern = rf'(?:^|\D){num}[\.,•](.*?)(?=\d{{1,2}}[\.,•]|㉮|가\s*\.|$)'
                    match = re.search(pattern, raw_text, re.DOTALL)
                    
                    if match:
                        candidate_text = match.group(1)
                        choices = self._extract_choices(candidate_text)
                        # 최소 길이 검증 (너무 짧으면 오탐 가능성)
                        q_text = self._clean_question_text(candidate_text)[:300].strip()
                        if len(q_text) > 20:
                            recovered.append(Question(
                                number=num,
                                text=q_text,
                                subject_name=subject,
                                choices=choices
                            ))
        
        # 원본 + 복구된 문제 합치고 정렬
        all_questions = questions + recovered
        
        # 과목별, 번호별 정렬
        return sorted(all_questions, key=lambda q: (q.subject_name or '', q.number))
    
    def _parse_page(
        self,
        text: str,
        page_num: int,
        image_paths: Optional[List[str]] = None,
        image_infos: Optional[List] = None,
        underlined_texts: Optional[List[str]] = None,
        tables: Optional[List] = None,
        overlined_texts: Optional[List] = None,
        allow_subject_reset: bool = True
    ) -> List[Question]:
        """단일 페이지에서 문제 추출"""
        questions = []
        image_assignments = []
        candidate_images = self._filter_image_candidates(image_paths or [], image_infos)
        reserved_image_count = 0
        
        # 페이지 번호 제거
        text = PAGE_NUMBER.sub('', text)
        text = self._normalize_ocr_question_number_artifacts(text)
        text = self._separate_joined_question_numbers(text)
        
        # 문제 분리
        matches = self._find_question_starts(text, allow_subject_reset=allow_subject_reset)

        for idx, match in enumerate(matches):
            try:
                q_num = int(match.group(1))
                
                # 유효한 문제 번호 범위 검증 (1-25)
                if q_num < 1 or q_num > 25:
                    continue
                    
                next_start = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
                q_text_raw = text[match.end():next_start]
                q_text_raw = apply_overline_marks(q_text_raw, overlined_texts or [])
                
                # 선지 추출
                choices = self._extract_choices(q_text_raw)
                
                # 문제 텍스트 정리 (선지 제거)
                q_text = self._clean_question_text(q_text_raw)
                q_text = repair_extracted_text_artifacts(q_text.strip())
                formatted_question = normalize_latex_text(q_text)
                matching_tables = self._matching_tables(q_text_raw, tables or [])
                q_format_json = self._build_format_json(
                    formatted_question.text,
                    underlined_texts or [],
                    matching_tables,
                    formatted_question.spans
                )
                self._apply_choice_format_json(choices, underlined_texts or [])
                
                # 이미지 필요 여부 판단
                needs_image = self._needs_image(q_text_raw, choices)
                choice_image_numbers = self._choice_image_numbers(choices, len(candidate_images))
                
                questions.append(Question(
                    number=q_num,
                    text=formatted_question.text,
                    choices=choices,
                    has_image=False,
                    image_path=None,
                    source_page=page_num,
                    format_json=q_format_json
                ))

                if choice_image_numbers:
                    q_idx = len(questions) - 1
                    required_for_choices = len(choice_image_numbers)
                    remaining_image_count = max(0, len(candidate_images) - reserved_image_count)
                    if needs_image and remaining_image_count >= required_for_choices + 1:
                        image_assignments.append(('question', q_idx, None))
                        image_assignments.append(('choices', q_idx, choice_image_numbers))
                        reserved_image_count += required_for_choices + 1
                    elif remaining_image_count >= required_for_choices:
                        image_assignments.append(('choices', q_idx, choice_image_numbers))
                        reserved_image_count += required_for_choices
                elif needs_image:
                    image_assignments.append(('question', len(questions) - 1, None))
                    reserved_image_count += 1
                
            except (ValueError, IndexError):
                continue

        # 이미지 할당 (문제 등장 순서대로 question image와 choice image를 소비)
        remaining_images = list(candidate_images)
        for kind, q_idx, choice_numbers in image_assignments:
            if not remaining_images:
                break
            if kind == 'question':
                questions[q_idx].image_path = remaining_images.pop(0)
                questions[q_idx].has_image = True
                continue

            for choice_number in choice_numbers:
                if not remaining_images:
                    break
                image_path = remaining_images.pop(0)
                for choice in questions[q_idx].choices:
                    if choice.number == choice_number:
                        choice.image_path = image_path
                        questions[q_idx].has_image = True
                        break

        return questions

    def _apply_choice_format_json(self, choices: List[Choice], underlined_texts: List[str]) -> None:
        for choice in choices:
            choice.text = repair_extracted_text_artifacts(choice.text)
            formatted_choice = normalize_latex_text(choice.text)
            choice.text = formatted_choice.text
            choice.format_json = self._build_format_json(
                choice.text,
                underlined_texts,
                [],
                formatted_choice.spans
            )

    def _build_format_json(
        self,
        text: str,
        underlined_texts: List[str],
        tables: List[dict],
        latex_spans: Optional[List[dict]] = None
    ) -> Optional[str]:
        payload = {}
        spans = merge_spans(
            self._underline_spans(text, underlined_texts),
            latex_spans or []
        )
        if spans:
            payload['spans'] = spans
        if tables:
            payload['tables'] = tables
        if not payload:
            return None
        return json.dumps(payload, ensure_ascii=False)

    def _underline_spans(self, text: str, underlined_texts: List[str]) -> List[dict]:
        spans = []
        seen = set()
        for phrase in underlined_texts:
            phrase = str(phrase or '').strip()
            if len(phrase) < 2:
                continue
            start = 0
            while True:
                found = text.find(phrase, start)
                if found < 0:
                    break
                key = (found, found + len(phrase))
                if key not in seen:
                    spans.append({'start': found, 'end': found + len(phrase), 'underline': True})
                    seen.add(key)
                start = found + len(phrase)
        spans.sort(key=lambda span: (span['start'], span['end']))
        return spans

    def _matching_tables(self, text: str, tables: List) -> List[dict]:
        matched = []
        normalized_text = self._normalize_for_match(text)
        for table in tables:
            rows = getattr(table, 'rows', None)
            if not rows:
                continue
            cells = [
                self._normalize_for_match(cell)
                for row in rows
                for cell in row
                if str(cell or '').strip()
            ]
            distinctive = [cell for cell in cells if len(cell) >= 2]
            if not distinctive:
                continue
            sample = distinctive[:8]
            hit_count = sum(1 for cell in sample if cell in normalized_text)
            required = 1 if len(sample) == 1 else 2
            if hit_count >= required:
                matched.append({'rows': rows})
        return matched

    def _normalize_for_match(self, value: str) -> str:
        return re.sub(r'\s+', '', str(value or ''))

    def _find_question_starts(self, text: str, allow_subject_reset: bool = True) -> List[_QuestionStart]:
        """Find question starts while ignoring numbering inside question text."""
        starts = []
        prev_num = None
        previous_start = 0

        for match in re.finditer(r'(?=([1-9]\d?)[\.,•])', text):
            start = match.start(1)
            if self._is_overlapping_number_match(text, start):
                continue
            q_num_text = match.group(1)
            q_num = int(q_num_text)
            if (
                not allow_subject_reset
                and prev_num is not None
                and prev_num < 9
                and q_num == prev_num + 11
            ):
                q_num = prev_num + 1
                q_num_text = str(q_num)
            if (
                not allow_subject_reset
                and prev_num is not None
                and 20 <= prev_num < 25
                and 1 <= q_num <= 5
            ):
                q_num = prev_num + 1
                q_num_text = str(q_num)
            end = match.end(1) + 1
            while end < len(text) and text[end].isspace():
                end += 1

            if q_num < 1 or q_num > 25:
                continue

            if prev_num is None:
                inferred_start = self._infer_leading_missing_question_start(text, start, q_num)
                if inferred_start:
                    starts.append(inferred_start)
                    prev_num = int(inferred_start.group(1))
                    previous_start = inferred_start.start()
                if not self._is_first_question_start_candidate(text, start, end):
                    continue
                starts.append(_QuestionStart(q_num_text, start, end))
                prev_num = q_num
                previous_start = start
                continue

            expected_next = q_num == prev_num + 1
            forward_gap = prev_num is not None and prev_num < q_num <= 25
            require_previous_choices = forward_gap and not expected_next
            subject_reset = allow_subject_reset and q_num == 1 and prev_num >= 20
            if (expected_next or forward_gap or subject_reset) and self._is_question_start_candidate(
                text,
                start,
                end,
                previous_start,
                allow_numeric_text=expected_next,
                require_previous_choices=require_previous_choices,
            ):
                if forward_gap and q_num > prev_num + 1:
                    inferred_starts = self._infer_missing_question_starts(
                        text,
                        previous_start,
                        start,
                        prev_num,
                        q_num,
                    )
                    for inferred_start in inferred_starts:
                        starts.append(inferred_start)
                        prev_num = int(inferred_start.group(1))
                        previous_start = inferred_start.start()
                starts.append(_QuestionStart(q_num_text, start, end))
                prev_num = q_num
                previous_start = start

        return starts

    def _is_overlapping_number_match(self, text: str, start: int) -> bool:
        if start > 0 and text[start - 1] in {'㉮', '㉯', '㉴', '㉵'}:
            return True
        if start <= 0 or not text[start - 1].isdigit():
            return False
        line_start = text.rfind('\n', 0, start) + 1
        if start - line_start == 1:
            return True
        line_prefix = text[line_start:start]
        if any(symbol in line_prefix for symbol in {'㉮', '㉯', '㉴', '㉵'}):
            return False
        if LEGACY_CHOICE_PATTERN.search(line_prefix):
            return False
        return True

    def _is_first_question_start_candidate(self, text: str, start: int, end: int) -> bool:
        previous = text[start - 1] if start > 0 else ''
        if previous and previous.isdigit():
            return False
        next_char = text[end] if end < len(text) else ''
        if next_char.isdigit() and not re.search(r'[\.,•]\s+', text[start:end]):
            if not re.match(r'\d+[A-Za-z가-힣]', text[end:end + 6]):
                return False
        return True

    def _is_question_start_candidate(
        self,
        text: str,
        start: int,
        end: int,
        previous_start: int,
        allow_numeric_text: bool = False,
        require_previous_choices: bool = False,
    ) -> bool:
        delimiter_match = re.match(r'\d{1,2}([,])', text[start:])
        if delimiter_match:
            next_char_after_comma = text[end] if end < len(text) else ''
            line_start = text.rfind('\n', 0, start) + 1
            line_prefix = text[line_start:start].strip()
            if line_prefix and next_char_after_comma.isascii() and next_char_after_comma.isalpha():
                return False

        next_char = text[end] if end < len(text) else ''
        previous_block = text[previous_start:start]
        if require_previous_choices and not self._block_has_choice_marker(previous_block):
            return False

        if next_char.isdigit():
            if not allow_numeric_text:
                return False
            if not self._block_has_choice_marker(previous_block):
                return False

        previous_char = text[start - 1] if start > 0 else ''
        if previous_char.isdigit() and not allow_numeric_text:
            return False
        previous_previous_char = text[start - 2] if start > 1 else ''
        if previous_char in {'.', ',', '•'} and previous_previous_char.isdigit():
            return False

        return True

    def _block_has_choice_marker(self, text: str) -> bool:
        return '㉵' in text or LEGACY_CHOICE_PATTERN.search(text) is not None

    def _infer_missing_question_starts(
        self,
        text: str,
        block_start: int,
        next_start: int,
        prev_num: int,
        next_num: int,
    ) -> List[_QuestionStart]:
        if next_num - prev_num != 2:
            return []

        block = text[block_start:next_start]
        symbol_matches = list(re.finditer(r'(㉮|㉯|㉴|㉵)', block))
        legacy_matches = list(LEGACY_CHOICE_PATTERN.finditer(block))
        choice_matches = symbol_matches if len(symbol_matches) >= 8 else legacy_matches
        if len(choice_matches) < 8:
            return []

        fourth_choice = choice_matches[3]
        fifth_choice = choice_matches[4]
        line_end = block.find('\n', fourth_choice.end())
        if line_end < 0 or line_end >= fifth_choice.start():
            return []

        candidate = line_end + 1
        while candidate < len(block) and block[candidate].isspace():
            candidate += 1
        if candidate >= fifth_choice.start():
            return []

        inferred_text = block[candidate:fifth_choice.start()].strip()
        if len(inferred_text) < 10:
            return []
        if re.match(r'[1-9]\d?[\.,•]', inferred_text):
            return []

        absolute = block_start + candidate
        return [_QuestionStart(str(prev_num + 1), absolute, absolute)]

    def _infer_leading_missing_question_start(
        self,
        text: str,
        first_start: int,
        first_num: int,
    ) -> Optional[_QuestionStart]:
        if first_num != 2:
            return None
        prefix = text[:first_start]
        symbol_matches = list(re.finditer(r'(㉮|㉯|㉴|㉵)', prefix))
        legacy_matches = list(LEGACY_CHOICE_PATTERN.finditer(prefix))
        if len(symbol_matches) < 4 and len(legacy_matches) < 4:
            return None

        candidate = 0
        while candidate < len(prefix) and prefix[candidate].isspace():
            candidate += 1
        while candidate < len(prefix) and prefix[candidate] in {':', '.', '-'}:
            candidate += 1
        while candidate < len(prefix) and prefix[candidate].isspace():
            candidate += 1

        inferred_text = prefix[candidate:].strip()
        if len(inferred_text) < 10:
            return None
        return _QuestionStart('1', candidate, candidate)

    def _separate_joined_question_numbers(self, text: str) -> str:
        """
        Compatibility hook for older parsing flow.

        Question starts are now resolved by _find_question_starts using sequential
        numbering, including numbers joined to the previous choice text.
        """
        return text

    def _normalize_ocr_question_number_artifacts(self, text: str) -> str:
        """Fix common scanned OCR mistakes in line-start question numbers."""
        text = re.sub(r'(?m)^(\s*)([12])\s+([0-9])[\.,•]?[ \t]*(?=[A-Za-z가-힣])', r'\g<1>\g<2>\g<3>.', text)
        text = re.sub(r'(?m)^(\s*)1이(?=[A-Za-z가-힣])', r'\g<1>10.', text)
        text = re.sub(r'(?m)^(\s*)2이(?=[A-Za-z가-힣])', r'\g<1>20.', text)
        text = re.sub(r'(?m)^(\s*)([1-9]\d?)![ \t]*(?=[A-Za-z가-힣])', r'\g<1>\g<2>. ', text)
        text = re.sub(r'(?m)^(\s*)기\.\s*(?=[A-Za-z가-힣])', r'\g<1>21. ', text)
        text = re.sub(
            r'(?m)^(\s*)(?:II|Il|lI|Ⅱ)[•\.\s]+(?=[A-Za-z가-힣])',
            r'\g<1>11.',
            text
        )
        return text
    
    def _extract_choices(self, text: str) -> List[Choice]:
        """선지 추출"""
        choices = []
        symbol_matches = list(re.finditer(r'(㉮|㉯|㉴|㉵)', text))

        if symbol_matches:
            for idx, match in enumerate(symbol_matches):
                symbol = match.group(1)
                number = CHOICE_SYMBOL_TO_NUMBER.get(symbol)
                if not number:
                    continue
                next_start = (
                    symbol_matches[idx + 1].start()
                    if idx + 1 < len(symbol_matches)
                    else len(text)
                )
                choices.append(Choice(
                    number=number,
                    symbol=symbol,
                    text=text[match.end():next_start].strip()
                ))
            return sorted(choices, key=lambda c: c.number)

        legacy_matches = list(LEGACY_CHOICE_PATTERN.finditer(text))
        if len(legacy_matches) >= 2:
            for idx, match in enumerate(legacy_matches):
                symbol = match.group(1)
                number = LEGACY_CHOICE_SYMBOL_TO_NUMBER.get(symbol)
                if not number:
                    continue
                next_start = (
                    legacy_matches[idx + 1].start()
                    if idx + 1 < len(legacy_matches)
                    else len(text)
                )
                if symbol in {'0h', 'Oh', 'OH', 'oh'}:
                    display_symbol = '아.'
                elif symbol == '卜':
                    display_symbol = '가.'
                else:
                    display_symbol = f'{symbol}.'
                choices.append(Choice(
                    number=number,
                    symbol=display_symbol,
                    text=text[match.end():next_start].strip()
                ))
            return sorted(choices, key=lambda c: c.number)

        matches = CHOICE_PATTERN.findall(text)
        
        for symbol, choice_text in matches:
            number = CHOICE_SYMBOL_TO_NUMBER.get(symbol)
            if number:
                choices.append(Choice(
                    number=number,
                    symbol=symbol,
                    text=choice_text.strip()
                ))
        
        return sorted(choices, key=lambda c: c.number)

    def _choice_image_numbers(self, choices: List[Choice], candidate_image_count: int = 0) -> List[int]:
        """텍스트가 비어 있는 선지를 이미지 선지 후보로 판단"""
        if len(choices) != 4:
            return []
        empty_choices = [
            choice.number
            for choice in choices
            if not choice.text.strip()
        ]
        if not empty_choices or candidate_image_count < len(empty_choices):
            return []
        return empty_choices
    
    def _clean_question_text(self, text: str) -> str:
        """문제 텍스트에서 선지 제거"""
        # 첫 번째 선지 기호 전까지만 추출
        for symbol in ['㉮', '㉯', '㉴', '㉵']:
            if symbol in text:
                text = text.split(symbol)[0]
                break
        else:
            legacy_matches = list(LEGACY_CHOICE_PATTERN.finditer(text))
            if len(legacy_matches) >= 2:
                text = text[:legacy_matches[0].start()]
        return text.strip()

    def _needs_image(self, text: str, choices: List[Choice]) -> bool:
        """문제에 이미지가 필요하다고 판단되는지 여부"""
        if len(choices) < 4:
            return True
        # Image hints in question text (use word boundaries for English keywords)
        return bool(
            re.search(
                r'(그림|도표|사진|다음과\s*같은|\bfig\.?\b|\bfigure\b|\bdiagram\b|\bchart\b|\bgraph\b)',
                text,
                re.IGNORECASE,
            )
        )

    def _filter_image_candidates(
        self,
        image_paths: List[str],
        image_infos: Optional[List] = None
    ) -> List[str]:
        """필터링된 이미지 후보 목록"""
        if image_infos:
            candidates = []
            for info in image_infos:
                path = getattr(info, 'path', None)
                bbox = getattr(info, 'bbox', None)
                if not path:
                    continue

                if bbox:
                    x0, y0, x1, y1 = bbox
                    display_w = abs(x1 - x0)
                    display_h = abs(y1 - y0)
                    # Skip footer logos, masks, separator fragments and tiny icons.
                    if display_w < 35 or display_h < 25:
                        continue

                if self._is_usable_image_file(path):
                    candidates.append(info)

            candidates.sort(key=self._image_reading_order_key)
            return [img.path for img in candidates]

        if not image_paths:
            return []
        return [path for path in image_paths if self._is_usable_image_file(path)]

    def _is_usable_image_file(self, path: str) -> bool:
        """이미지 파일 자체가 유효한 문제 그림 후보인지 확인"""
        try:
            from PIL import Image, ImageStat
        except Exception:
            # If Pillow isn't available, return all paths
            return True

        try:
            with Image.open(path) as im:
                w, h = im.size
                # Skip very thin separators/lines
                if h < 35 or w < 35:
                    return False
                # Skip near-empty images
                stddev = ImageStat.Stat(im.convert('L')).stddev[0]
                if stddev < 2:
                    return False
            return True
        except Exception:
            return False

    def _image_reading_order_key(self, image_info) -> tuple:
        """시험지 2단 편집 기준의 이미지 읽기 순서"""
        bbox = getattr(image_info, 'bbox', None)
        if not bbox:
            return (0, 0, 0)

        x0, y0, x1, _ = bbox
        center_x = (x0 + x1) / 2
        # The maritime exam PDFs are rendered on a ~728pt-wide page.
        # Text extraction follows left column top-to-bottom, then right column.
        column = 0 if center_x < 360 else 1
        return (column, y0, x0)
