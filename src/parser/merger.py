# src/parser/merger.py
"""문제와 정답 병합 및 데이터베이스 저장"""

from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
import logging

from .question import Question
from .metadata import ExamMetadata

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """검증 결과"""
    is_valid: bool
    errors: List[str]
    warnings: List[str]


class DataMerger:
    """문제와 정답 병합"""
    
    def merge(self, 
              questions: List[Question], 
              answers: Dict[Tuple, List[int]],
              metadata: ExamMetadata) -> List[Question]:
        """
        문제에 정답 매칭
        
        Args:
            questions: 문제 리스트
            answers: {(연도, 회차, 과목명): [정답 리스트]} 딕셔너리
            metadata: 시험 메타데이터
            
        Returns:
            정답이 매칭된 문제 리스트
        """
        merged = []
        
        for q in questions:
            year = q.year if q.year is not None else metadata.year
            session = q.session if q.session is not None else metadata.session
            exam_type = q.exam_type or metadata.exam_type

            key_with_exam = (year, session, exam_type, q.subject_name)
            key_without_exam = (year, session, q.subject_name)

            if key_with_exam in answers:
                answer_list = answers[key_with_exam]
            elif key_without_exam in answers:
                answer_list = answers[key_without_exam]
            else:
                answer_list = None

            if answer_list:
                if 1 <= q.number <= len(answer_list):
                    q.correct_answer = answer_list[q.number - 1]
                else:
                    logger.warning(
                        f"정답 범위 초과: {(year, session, exam_type, q.subject_name)}, 문제 {q.number}"
                    )
            else:
                logger.warning(f"정답 키 없음: {(year, session, exam_type, q.subject_name)}")
            
            merged.append(q)
        
        return merged
    
    def validate(self, questions: List[Question]) -> ValidationResult:
        """
        데이터 검증
        
        검증 항목:
        - 정답 누락 확인
        - 선지 개수 확인 (4개)
        - 문제 번호 연속성
        """
        errors = []
        warnings = []
        
        subject_questions = {}
        for q in questions:
            year = q.year if q.year is not None else 'unknown'
            session = q.session if q.session is not None else 'unknown'
            exam_type = q.exam_type or 'unknown'
            subject = q.subject_name or 'unknown'
            key = (year, session, exam_type, subject)
            if key not in subject_questions:
                subject_questions[key] = []
            subject_questions[key].append(q)
        
        for (year, session, exam_type, subject), qs in subject_questions.items():
            # 정답 누락 확인
            missing_answers = [q for q in qs if q.correct_answer is None]
            if missing_answers:
                errors.append(
                    f"{year}년 {session}회 {subject}: {len(missing_answers)}개 문제 정답 누락"
                )
            
            # 선지 개수 확인
            for q in qs:
                if len(q.choices) < 4 and not q.has_image:
                    warnings.append(
                        f"{year}년 {session}회 {subject} {q.number}번: 선지 {len(q.choices)}개"
                    )
            
            # 문제 번호 연속성
            numbers = sorted([q.number for q in qs])
            duplicate_numbers = sorted({n for n in numbers if numbers.count(n) > 1})
            if duplicate_numbers:
                errors.append(
                    f"{year}년 {session}회 {subject}: 문제 번호 중복 {duplicate_numbers}"
                )

            expected = list(range(1, 26))
            if numbers != expected:
                missing = set(expected) - set(numbers)
                if missing:
                    errors.append(
                        f"{year}년 {session}회 {subject}: 문제 번호 누락 {missing}"
                    )
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings
        )
