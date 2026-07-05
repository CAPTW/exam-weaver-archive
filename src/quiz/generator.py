# src/quiz/generator.py

from typing import List, Optional, Dict
import random
import logging

from ..database.selection import (
    count_group_aware_questions,
    dedupe_group_aware_questions_by_content,
    filter_group_aware_random_eligible_questions,
    selection_content_keys,
    select_group_aware_questions,
)
from ..database.validator import QuestionValidator

logger = logging.getLogger(__name__)

class MockExamGenerator:
    def __init__(self, repository):
        self.repo = repository

    def create(self, exam_code: str, subject_codes: Optional[List[str]] = None, count: int = 25) -> Dict:
        """Create a mock exam"""
        if count <= 0:
            raise ValueError("Question count must be greater than 0.")

        self.repo.init_database()
        validator = QuestionValidator(self.repo)

        # 1. Verify exam exists
        with self.repo._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name FROM exams WHERE code = ?", (exam_code,))
            exam_row = cursor.fetchone()
            if not exam_row:
                raise ValueError(f"Unknown exam code: {exam_code}")
            exam_id, exam_name = exam_row

            cursor.execute("""
                SELECT s.code
                FROM exam_subjects es
                JOIN subjects s ON es.subject_id = s.id
                WHERE es.exam_id = ?
                ORDER BY es.display_order
            """, (exam_id,))
            available_subjects = [row[0] for row in cursor.fetchall()]

            if not available_subjects:
                raise ValueError(f"No subjects configured for exam code: {exam_code}")

            if subject_codes:
                subject_codes = [code.strip() for code in subject_codes if code.strip()]
                invalid_subjects = sorted(set(subject_codes) - set(available_subjects))
                if invalid_subjects:
                    raise ValueError(
                        f"Unknown subject code(s) for {exam_code}: {', '.join(invalid_subjects)}"
                    )
            else:
                subject_codes = available_subjects

            eligible_pools = {}
            availability = {}
            for subject_code in subject_codes:
                questions = self.repo.get_questions_with_choices(
                    exam_code=exam_code,
                    subject_code=subject_code,
                    limit=None,
                )
                questions = filter_group_aware_random_eligible_questions(
                    questions,
                    validator,
                )
                eligible_pools[subject_code] = dedupe_group_aware_questions_by_content(
                    questions
                )
                availability[subject_code] = len(eligible_pools[subject_code])

            selected_by_subject = {}
            selected_keys = set()
            for subject_code in subject_codes:
                availability[subject_code] = count_group_aware_questions(
                    eligible_pools[subject_code],
                    excluded_keys=selected_keys,
                )
                try:
                    selected_questions = select_group_aware_questions(
                        eligible_pools[subject_code],
                        count,
                        rng=random,
                        excluded_keys=selected_keys,
                    )
                except ValueError as exc:
                    raise ValueError(
                        f"Not enough questions available: {subject_code} ({availability[subject_code]}/{count})"
                    ) from exc
                selected_by_subject[subject_code] = selected_questions
                selected_keys.update(selection_content_keys(selected_questions))

        # 2. Create mock exam entry
        mock_name = f"{exam_name} Mock Exam"
        with self.repo._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO mock_exams (exam_id, name) VALUES (?, ?)", (exam_id, mock_name))
            mock_id = cursor.lastrowid
            
            # 3. Select questions
            total_questions = 0

            display_order = 1
            for subject_code in subject_codes:
                question_ids = [
                    question['id']
                    for question in selected_by_subject[subject_code]
                ]
                
                for q_id in question_ids:
                    cursor.execute("""
                        INSERT INTO mock_exam_questions (mock_exam_id, question_id, display_order)
                        VALUES (?, ?, ?)
                    """, (mock_id, q_id, display_order))
                    display_order += 1
                
                total_questions += len(question_ids)

        return {
            'id': mock_id,
            'name': mock_name,
            'total_questions': total_questions
        }
