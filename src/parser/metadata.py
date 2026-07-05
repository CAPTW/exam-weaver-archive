# src/parser/metadata.py
"""표지에서 시험 정보 추출"""

import re
from typing import Optional, Dict
from dataclasses import dataclass
from .patterns import COVER_INFO_LIST, EXAM_TYPE_LIST, COVER_INDICATORS


@dataclass
class ExamMetadata:
    """시험 메타데이터"""
    year: int
    session: int
    exam_type: str
    is_domestic: bool = False


class ExamMetadataParser:
    """표지에서 시험 정보 추출"""
    
    def is_cover_page(self, text: str) -> bool:
        """표지 페이지 판별"""
        # "문 제 지"는 띄어쓰기 변형이 많아 정규식으로 처리
        if re.search(r'문\s*제\s*지', text):
            return True
        return any(ind in text for ind in COVER_INDICATORS)
    
    def parse_cover(self, text: str) -> Optional[ExamMetadata]:
        """
        표지 텍스트에서 메타데이터 추출
        """
        year, session = self._extract_year_session(text)
        exam_type = self._extract_exam_type(text)
        
        # 국내한정 여부
        is_domestic = '국내한정' in text or '국내' in text

        # 표지 판별: 메타데이터가 없으면 표지로 간주하지 않음
        if not (year and session and exam_type):
            return None

        # 자격 구분 보정
        if '항해사' in exam_type:
            base_exam_type = exam_type.split('(', 1)[0]
            qualifiers = []
            if is_domestic:
                qualifiers.append('국내')
            if '상선' in text:
                qualifiers.append('상선')
            elif '어선' in text:
                qualifiers.append('어선')
            if qualifiers:
                exam_type = f"{base_exam_type}({' '.join(qualifiers)})"
        elif is_domestic and '(국내)' not in exam_type:
            exam_type = f"{exam_type}(국내)"
        
        if year and session and exam_type:
            return ExamMetadata(
                year=year,
                session=session,
                exam_type=exam_type,
                is_domestic=is_domestic
            )
        
        return None

    def _extract_year_session(self, text: str):
        for pattern in COVER_INFO_LIST:
            match = pattern.search(text)
            if match:
                return int(match.group(1)), int(match.group(2))

        fallback_patterns = [
            re.compile(r'(\d{4})\s*년\s*정기.*?제\s*회\s*(\d+)', re.DOTALL),
            re.compile(r'(\d{4})\s*년\s*정기.*?제\s*(\d+)\s*회', re.DOTALL),
            re.compile(r'년\s*정기\s*제\s*회\s*(\d{4})\s*(\d+)'),
            re.compile(r'년\s*제\s*회\s*정기시험\s*(\d{4})\s*(\d+)'),
        ]
        for pattern in fallback_patterns:
            match = pattern.search(text)
            if match:
                return int(match.group(1)), int(match.group(2))

        return None, None

    def _extract_exam_type(self, text: str) -> Optional[str]:
        if '소형선박조종사' in text:
            return '소형선박조종사'

        for pattern in EXAM_TYPE_LIST:
            match = pattern.search(text)
            if not match:
                continue

            # 1. (\d)급 (\w+사)
            if match.re.pattern.startswith(r'(\d)급'):
                return f"{match.group(1)}급{match.group(2)}".replace(' ', '')

            # 2. 급 (\w+사)(\d)
            return f"{match.group(2)}급{match.group(1)}".replace(' ', '')

        # Some older PDFs extract "3급항해사(상선)" as "급항해사 상선3 ( )".
        reversed_match = re.search(
            r'급\s*([가-힣]+사)\s*(?:(상선|어선|국내한정|국내)\s*)?(\d)',
            text
        )
        if reversed_match:
            grade = reversed_match.group(3)
            role = reversed_match.group(1)
            return f"{grade}급{role}".replace(' ', '')

        split_cover_match = re.search(
            r'([1-6])\s*문\s*제.*?급\s*([가-힣]+사)',
            text,
            re.DOTALL
        )
        if split_cover_match:
            return f"{split_cover_match.group(1)}급{split_cover_match.group(2)}".replace(' ', '')

        return None
