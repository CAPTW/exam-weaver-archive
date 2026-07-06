from pathlib import Path
import re
from typing import Dict, List

from ..parser.formatting import has_suspicious_text_artifact
from ..parser.patterns import NUMBER_TO_CHOICE_SYMBOL


class QuestionValidator:
    """Validate parsed question records for common PDF extraction mistakes."""

    MIN_SESSION = 1
    MAX_SESSION = 99
    MIN_QUESTION_NUMBER = 1
    MAX_QUESTION_NUMBER = 500
    MIN_CHOICE_COUNT = 4
    MAX_CHOICE_COUNT = 10
    VALID_ANSWERS = set(range(1, MAX_CHOICE_COUNT + 1))
    IMAGE_HINT_PATTERN = re.compile(
        r'(그림|사진|그래프|(?<!해)도표|'
        r'다음과\s*같은|다음\s*(?:그림|회로|선도|기호|도표|파형|진리표|타임차트)|'
        r'다음\s*중.{0,20}기호|'
        r'\bfig\.?\b|\bfigure\b|\bdiagram\b)',
        re.IGNORECASE,
    )
    OCR_NOISE_PATTERN = re.compile(
        r'(?:0[卜ㅏ]|(?<![A-Za-z])[O0]h(?![A-Za-z])|[卜入人]{2,}|으\s*(?:9|느|그)|으\s+거|'
        r'[가-힣A-Za-z][卜入人][가-힣A-Za-z]|[쥐튢飇恤喬盞])'
    )
    BROKEN_UNIT_PATTERN = re.compile(
        r'\[(?:0/해|Ⅵ|H기|시|외|이(?=\s|$|[\]\)])|P비|kg되|넣디|Q|\(\)|\))'
    )
    LEGACY_CHOICE_SYMBOLS = {
        1: {'㉮', '가', '가.', '가)', 'ㄱ'},
        2: {'㉯', '나', '나.', '나)', 'ㄴ'},
        3: {'㉴', '사', '사.', '사)', 'ㄷ'},
        4: {'㉵', '아', '아.', '아)', 'ㄹ', '0h', 'Oh', 'OH', 'oh'},
        5: {'⑤', '❺', '5', 'ㅁ'},
    }

    def __init__(self, repository):
        self.repository = repository

    def scan(self, exam_code=None, subject_code=None, search_text=None, limit=None) -> List[Dict]:
        questions = self.repository.get_questions_with_choices(
            exam_code=exam_code,
            subject_code=subject_code,
            search_text=search_text,
            limit=limit,
        )
        findings = []
        for question in questions:
            issues = self._validate_question(question)
            if not issues:
                continue
            findings.append({
                'question_id': question['id'],
                'question': question,
                'issues': issues,
                'severity': self._severity(issues),
                'summary': ", ".join(issue['message'] for issue in issues),
            })
        return findings

    def _validate_question(self, question: Dict) -> List[Dict]:
        issues = []

        if not str(question.get('question_text') or '').strip():
            issues.append(self._issue('empty_question_text', '발문 없음', 'error'))
        else:
            question_text = str(question.get('question_text') or '')
            if question_text.startswith('[OCR 누락]'):
                issues.append(self._issue('ocr_placeholder', 'OCR 누락 placeholder', 'error'))
            if has_suspicious_text_artifact(question_text):
                issues.append(self._issue('suspicious_text_artifact', '발문 텍스트 순서 의심', 'error'))
            self._validate_text_quality(question_text, '발문', issues)

        if not self._valid_session(question.get('session')):
            issues.append(self._issue('invalid_session', '회차 범위 이상', 'error'))

        question_number = question.get('question_number')
        if (
            not isinstance(question_number, int)
            or question_number < self.MIN_QUESTION_NUMBER
            or question_number > self.MAX_QUESTION_NUMBER
        ):
            issues.append(self._issue('invalid_question_number', '문제번호 범위 이상', 'error'))

        choices = question.get('choices') or []
        choice_numbers = {
            choice.get('choice_number')
            for choice in choices
            if choice.get('choice_number') is not None
        }
        if question.get('correct_answer') not in choice_numbers:
            issues.append(self._issue('invalid_correct_answer', '정답 번호 이상', 'error'))

        image_state = self._image_state(question)
        self._validate_choices(choices, issues, image_state)
        self._validate_image(question, issues)
        self._validate_tags(question, issues)

        return issues

    def has_blocking_errors(self, question: Dict) -> bool:
        return any(
            issue['severity'] == 'error'
            for issue in self._validate_question(question)
        )

    def is_random_eligible(self, question: Dict) -> bool:
        return not self.has_blocking_errors(question)

    def _validate_choices(self, choices: List[Dict], issues: List[Dict], image_state: Dict):
        numbers = [choice.get('choice_number') for choice in choices]
        if (
            len(numbers) < self.MIN_CHOICE_COUNT
            or len(numbers) > self.MAX_CHOICE_COUNT
            or sorted(numbers) != list(range(1, len(numbers) + 1))
        ):
            issues.append(self._issue('choice_count', '선지 번호/개수 이상', 'error'))

        for choice in choices:
            number = choice.get('choice_number')
            expected_symbol = NUMBER_TO_CHOICE_SYMBOL.get(number)
            choice_image_path = choice.get('choice_image_path') or choice.get('image_path')
            symbol = str(choice.get('choice_symbol') or '').strip()
            if expected_symbol and symbol not in self.LEGACY_CHOICE_SYMBOLS.get(number, {expected_symbol}):
                issues.append(self._issue('invalid_choice_symbol', f'{number}번 선지 기호 이상', 'error'))
            choice_text = str(choice.get('choice_text') or '')
            if choice_text.strip() and has_suspicious_text_artifact(choice_text):
                issues.append(self._issue('suspicious_text_artifact', f'{number}번 선지 텍스트 순서 의심', 'error'))
            if choice_text.strip():
                self._validate_text_quality(choice_text, f'{number}번 선지', issues)
            if (
                not choice_text.strip()
                and not choice_image_path
                and not image_state['has_question_image_file']
            ):
                issues.append(self._issue('empty_choice_text', f'{number}번 선지 내용 없음', 'error'))
            if choice_image_path and not Path(choice_image_path).exists():
                issues.append(self._issue(
                    'missing_choice_image_file',
                    f'{number}번 선지 이미지 파일 없음',
                    'error'
                ))

    def _validate_image(self, question: Dict, issues: List[Dict]):
        image_state = self._image_state(question)
        image_path = image_state['image_path']
        has_image = image_state['has_image_flag']
        has_choice_image = image_state['has_choice_image']
        if has_image and not image_path and not has_choice_image:
            issues.append(self._issue('missing_image_path', '이미지 경로 없음', 'error'))
        if image_path and not Path(image_path).exists():
            issues.append(self._issue('missing_image_file', '이미지 파일 없음', 'error'))
        if self._requires_image(question) and not image_state['has_any_image']:
            issues.append(self._issue('missing_required_image', '이미지 필요 문항 이미지 없음', 'error'))

    def _image_state(self, question: Dict) -> Dict:
        choices = question.get('choices') or []
        image_path = question.get('image_path')
        has_choice_image = any(
            choice.get('choice_image_path') or choice.get('image_path')
            for choice in choices
        )
        return {
            'image_path': image_path,
            'has_image_flag': bool(question.get('has_image')),
            'has_choice_image': has_choice_image,
            'has_question_image_file': bool(image_path and Path(image_path).exists()),
            'has_any_image': bool(image_path or has_choice_image),
        }

    def _requires_image(self, question: Dict) -> bool:
        text = str(question.get('question_text') or '')
        return bool(self.IMAGE_HINT_PATTERN.search(text))

    def _validate_text_quality(self, text: str, label: str, issues: List[Dict]) -> None:
        if self.OCR_NOISE_PATTERN.search(text):
            issues.append(self._issue('ocr_noise_text', f'{label} OCR 잡문자 의심', 'error'))
        if self.BROKEN_UNIT_PATTERN.search(text):
            issues.append(self._issue('broken_unit_text', f'{label} 단위/수식 깨짐 의심', 'warning'))
        if self._has_unbalanced_delimiters(text):
            issues.append(self._issue('unbalanced_delimiter', f'{label} 괄호/대괄호 불균형', 'warning'))

    def _has_unbalanced_delimiters(self, text: str) -> bool:
        value = str(text or '')
        if not value:
            return False
        paren_depth = 0
        extra_close = 0
        for index, char in enumerate(value):
            if char == '(':
                paren_depth += 1
            elif char == ')':
                if paren_depth:
                    paren_depth -= 1
                elif not re.search(r'\d+\s*$', value[:index]):
                    extra_close += 1
        return paren_depth != 0 or extra_close != 0 or value.count('[') != value.count(']')

    def _valid_session(self, value) -> bool:
        if not isinstance(value, int):
            return False
        return self.MIN_SESSION <= value <= self.MAX_SESSION

    def _validate_tags(self, question: Dict, issues: List[Dict]):
        tags = str(question.get('tags') or '')
        if not tags.strip():
            issues.append(self._issue('empty_tags', '태그 없음', 'warning'))
            return

        exam_name = question.get('exam_name')
        if exam_name and f"#{exam_name.replace(' ', '')}" not in tags.replace(' ', ''):
            issues.append(self._issue('missing_exam_tag', '시험 태그 누락', 'warning'))

        subject_name = question.get('subject_name')
        if subject_name and f"#{subject_name}" not in tags:
            issues.append(self._issue('missing_subject_tag', '과목 태그 누락', 'warning'))

    def _severity(self, issues: List[Dict]) -> str:
        return 'error' if any(issue['severity'] == 'error' for issue in issues) else 'warning'

    def _issue(self, code: str, message: str, severity: str) -> Dict:
        return {'code': code, 'message': message, 'severity': severity}
