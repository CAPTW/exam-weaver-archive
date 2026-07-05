# src/quiz/runner.py

import click
import time
from typing import Dict, List
from datetime import datetime

class CLIQuizRunner:
    def __init__(self, repository):
        self.repo = repository

    def run(self, mock_id: int) -> Dict:
        """Run the quiz in CLI"""
        self.repo.init_database()
        
        # 1. Load questions
        with self.repo._get_connection() as conn:
            conn.row_factory = None
            cursor = conn.cursor()
            
            # Verify mock exam exists
            cursor.execute("SELECT name FROM mock_exams WHERE id = ?", (mock_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Mock exam ID {mock_id} not found.")
            mock_name = row[0]
            
            # Get questions
            cursor.execute("""
                SELECT
                    q.id,
                    q.question_text,
                    q.correct_answer,
                    s.name_ko,
                    es.id,
                    q.group_id,
                    qg.shared_text
                FROM mock_exam_questions meq
                JOIN questions q ON meq.question_id = q.id
                JOIN exam_subjects es ON q.exam_subject_id = es.id
                JOIN subjects s ON es.subject_id = s.id
                LEFT JOIN question_groups qg ON q.group_id = qg.id
                WHERE meq.mock_exam_id = ?
                ORDER BY meq.display_order
            """, (mock_id,))
            questions = cursor.fetchall()

        if not questions:
            click.echo("This mock exam has no questions.")
            return {'score': 0, 'correct': 0, 'total': 0}

        click.echo(f"\nStarting Exam: {mock_name}")
        click.echo(f"Total Questions: {len(questions)}\n")
        
        start_time = time.time()
        correct_count = 0
        total = len(questions)
        subject_stats = {}
        last_group_id = None
        
        for idx, (
            q_id,
            q_text,
            correct_answer,
            subject,
            exam_subject_id,
            group_id,
            shared_passage,
        ) in enumerate(questions, 1):
            click.echo(f"\n{'='*40}")
            click.echo(f"Question {idx}/{total} [{subject}]")
            click.echo(f"{'='*40}")
            if group_id is not None and shared_passage and group_id != last_group_id:
                click.echo("[공통지문]")
                click.echo(f"{shared_passage}\n")
            click.echo(f"{q_text}\n")
            last_group_id = group_id if group_id is not None else None
            
            # Get choices
            q_data = self.repo.get_question(q_id)
            for choice in q_data['choices']:
                click.echo(f"  {choice['symbol']} {choice['text']}")
            
            # Get user answer
            while True:
                user_input = click.prompt("\nAnswer (1-4)", type=int)
                if 1 <= user_input <= 4:
                    break
                click.echo("Invalid input. Please enter 1-4.")
            
            if user_input == correct_answer:
                click.echo("\n[OK] Correct!")
                correct_count += 1
                subject_stats.setdefault(exam_subject_id, {'subject': subject, 'total': 0, 'correct': 0})
                subject_stats[exam_subject_id]['correct'] += 1
            else:
                correct = next((c for c in q_data['choices'] if c['number'] == correct_answer), None)
                correct_symbol = correct['symbol'] if correct else str(correct_answer)
                click.echo(f"\n[WRONG] Correct answer: {correct_symbol}") # Should ideally show text too

            subject_stats.setdefault(exam_subject_id, {'subject': subject, 'total': 0, 'correct': 0})
            subject_stats[exam_subject_id]['total'] += 1
            
            # Pause slightly for UX
            time.sleep(0.5)

        end_time = time.time()
        duration = int(end_time - start_time)
        score = (correct_count / total) * 100

        # Save result
        with self.repo._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO exam_results (mock_exam_id, total_questions, correct_count, score, time_spent_seconds)
                VALUES (?, ?, ?, ?, ?)
            """, (mock_id, total, correct_count, score, duration))
            for exam_subject_id, stats in subject_stats.items():
                subject_score = (stats['correct'] / stats['total']) * 100 if stats['total'] else 0
                cursor.execute("""
                    INSERT INTO exam_results (
                        mock_exam_id,
                        exam_subject_id,
                        total_questions,
                        correct_count,
                        score,
                        time_spent_seconds
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    mock_id,
                    exam_subject_id,
                    stats['total'],
                    stats['correct'],
                    subject_score,
                    duration
                ))

        return {
            'score': round(score, 1),
            'correct': correct_count,
            'total': total,
            'duration_seconds': duration
        }
