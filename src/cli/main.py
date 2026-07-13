# src/cli/main.py
"""CLI 엔트리포인트"""

import click
import logging
from pathlib import Path

from ..parser.question import ALL_CHOICES_CORRECT

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)


@click.group()
@click.version_option(version='2.1.0')
def cli():
    """문제은행 관리 시스템"""
    pass


# ============ 데이터베이스 명령어 ============

@cli.group()
def db():
    """데이터베이스 관리"""
    pass


@db.command()
@click.option('--db-path', default='./data/exam_bank.db', help='DB 파일 경로')
def init(db_path):
    """데이터베이스 초기화"""
    from ..database.repository import ExamRepository
    
    # Ensure directory exists
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    
    repo = ExamRepository(db_path)
    repo.init_database()
    click.echo(f"[OK] 데이터베이스 초기화 완료: {db_path}")


@db.command()
@click.option('--db-path', default='./data/exam_bank.db')
@click.option('--output', '-o', default='./backup')
def backup(db_path, output):
    """데이터베이스 백업"""
    import shutil
    from datetime import datetime
    
    Path(output).mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = Path(output) / f'exam_bank_{timestamp}.db'
    
    if Path(db_path).exists():
        shutil.copy2(db_path, backup_path)
        click.echo(f"[OK] 백업 완료: {backup_path}")
    else:
        click.echo(f"[ERROR] DB 파일을 찾을 수 없습니다: {db_path}")


# ============ PDF 임포트 명령어 ============

@cli.command(name='import')
@click.argument('question_pdf', type=click.Path(exists=True))
@click.argument('answer_pdf', type=click.Path(exists=True))
@click.option('--exam-type', help='시험 종류 (자동 감지 시 생략)')
@click.option('--db-path', default='./data/exam_bank.db')
@click.option('--dry-run', is_flag=True, help='DB 저장 없이 파싱만 실행')
def import_pdf(question_pdf, answer_pdf, exam_type, db_path, dry_run):
    """PDF에서 문제 임포트
    
    예시:
        exam-bank import ./2022_exam.pdf ./2022_answer.pdf
        exam-bank import ./exam.pdf ./answer.pdf --exam-type 3급기관사
    """
    from ..parser.main import ExamPDFParser
    from ..database.repository import ExamRepository
    
    # 파싱
    parser = ExamPDFParser()
    try:
        result = parser.parse(question_pdf, answer_pdf, exam_type)
    except Exception as e:
        click.echo(f"[ERROR] 파싱 중 오류 발생: {e}")
        return
    
    # 결과 출력
    click.echo("\n" + "=" * 60)
    click.echo("파싱 결과")
    click.echo("=" * 60)
    
    meta = result['metadata']
    meta_list = result.get('metadata_list') or [meta]

    exam_types = sorted({m.exam_type for m in meta_list if m})
    click.echo(f"시험: {', '.join(exam_types)}")

    if len(meta_list) > 1:
        click.echo("회차:")
        for m in meta_list:
            click.echo(f"  - {m.year}년 제{m.session}회")
    else:
        click.echo(f"연도: {meta.year}년 제{meta.session}회")
    
    click.echo(f"\n문제 수: {result['stats']['total_questions']}")
    click.echo("과목별:")
    for subject, count in result['stats']['by_subject'].items():
        click.echo(f"  - {subject}: {count}문제")
    
    click.echo(f"\n이미지 포함: {result['stats']['with_images']}문제")
    click.echo(f"정답 매칭: {result['stats']['with_answers']}문제")
    
    # 검증 결과
    val = result['validation']
    if val.errors:
        click.echo("\n[ERROR]")
        for err in val.errors:
            click.echo(f"  - {err}")
    
    if val.warnings:
        click.echo("\n[WARN]")
        for warn in val.warnings:
            click.echo(f"  - {warn}")
    
    # DB 저장
    if not dry_run and val.is_valid:
        # Create DB dir if not exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        
        repo = ExamRepository(db_path)
        # Ensure DB is initialized
        repo.init_database()
        
        saved_count = repo.save_questions(result['questions'], meta)
        click.echo(f"\n[OK] {saved_count}문제 저장 완료")
    elif dry_run:
        click.echo("\n[Dry Run] DB 저장 생략")
    else:
        click.echo("\n[ERROR] 오류로 인해 DB 저장 생략")


# ============ 문제 조회 명령어 ============

@cli.group()
def question():
    """문제 관리"""
    pass


@question.command('list')
@click.option('--exam', help='시험 코드')
@click.option('--subject', help='과목 코드')
@click.option('--year', type=int, help='출제 연도')
@click.option('--session', type=int, help='회차')
@click.option('--limit', default=20, help='출력 개수')
@click.option('--db-path', default='./data/exam_bank.db')
def list_questions(exam, subject, year, session, limit, db_path):
    """문제 목록 조회"""
    from ..database.repository import ExamRepository
    
    repo = ExamRepository(db_path)
    questions = repo.search_questions(
        exam_code=exam,
        subject_code=subject,
        year=year,
        session=session,
        limit=limit
    )
    
    if not questions:
        click.echo("조회된 문제가 없습니다.")
        return
    
    for q in questions:
        click.echo(f"\n[{q['id']}] {q['subject_name']} {q['year']}년 {q['session']}회 {q['question_number']}번")
        click.echo(f"  {q['question_text'][:80]}...")


@question.command('show')
@click.argument('question_id', type=int)
@click.option('--db-path', default='./data/exam_bank.db')
def show_question(question_id, db_path):
    """문제 상세 조회"""
    from ..database.repository import ExamRepository
    
    repo = ExamRepository(db_path)
    q = repo.get_question(question_id)
    
    if not q:
        click.echo(f"문제 ID {question_id}를 찾을 수 없습니다.")
        return
    
    click.echo(f"\n{'=' * 60}")
    click.echo(f"[{q['id']}] {q['subject_name']} {q['year']}년 {q['session']}회 {q['question_number']}번")
    click.echo(f"{'=' * 60}")
    click.echo(f"\n{q['question_text']}\n")
    
    all_choices_correct = q['correct_answer'] == ALL_CHOICES_CORRECT
    for choice in q['choices']:
        marker = "*" if all_choices_correct or choice['number'] == q['correct_answer'] else " "
        click.echo(f"  {marker} {choice['symbol']} {choice['text']}")

    answer_label = "전원 정답" if all_choices_correct else f"{q['correct_answer']}번"
    click.echo(f"\n정답: {answer_label}")


# ============ 모의고사 명령어 ============

@cli.group()
def mock():
    """모의고사 관리"""
    pass


@mock.command('create')
@click.option('--exam', required=True, help='시험 코드')
@click.option('--subjects', help='과목 코드 (쉼표 구분)')
@click.option('--count', default=25, help='과목당 문제 수')
@click.option('--db-path', default='./data/exam_bank.db')
def create_mock(exam, subjects, count, db_path):
    """모의고사 생성"""
    from ..database.repository import ExamRepository
    from ..quiz.generator import MockExamGenerator
    
    repo = ExamRepository(db_path)
    generator = MockExamGenerator(repo)
    
    subject_list = subjects.split(',') if subjects else None
    
    try:
        mock_exam = generator.create(exam, subject_list, count)
        click.echo(f"[OK] 모의고사 생성 완료: ID {mock_exam['id']}")
        click.echo(f"  총 {mock_exam['total_questions']}문제")
    except ValueError as e:
        click.echo(f"[ERROR] 오류: {e}")


@mock.command('start')
@click.argument('mock_id', type=int)
@click.option('--db-path', default='./data/exam_bank.db')
def start_mock(mock_id, db_path):
    """모의고사 시작 (CLI 퀴즈 모드)"""
    from ..database.repository import ExamRepository
    from ..quiz.runner import CLIQuizRunner
    
    repo = ExamRepository(db_path)
    runner = CLIQuizRunner(repo)
    
    try:
        result = runner.run(mock_id)
        if result['total'] > 0:
            click.echo(f"\n{'=' * 60}")
            click.echo(f"결과: {result['score']}점 ({result['correct']}/{result['total']})")
            click.echo(f"{'=' * 60}")
    except ValueError as e:
         click.echo(f"[ERROR] 오류: {e}")


# ============ 통계 명령어 ============

@cli.command()
@click.option('--exam', help='시험 코드')
@click.option('--year', type=int, help='연도')
@click.option('--db-path', default='./data/exam_bank.db')
def stats(exam, year, db_path):
    """통계 조회"""
    from ..database.repository import ExamRepository
    
    repo = ExamRepository(db_path)
    statistics = repo.get_statistics(exam_code=exam, year=year)
    
    click.echo("\n문제은행 통계")
    click.echo("=" * 40)
    click.echo(f"총 문제 수: {statistics['total_questions']}")
    click.echo(f"시험 종류: {statistics['exam_count']}")
    click.echo(f"과목 수: {statistics['subject_count']}")
    
    if 'by_year' in statistics:
        click.echo("\n연도별 문제 수:")
        for year, count in statistics['by_year'].items():
            click.echo(f"  {year}년: {count}문제")


if __name__ == '__main__':
    cli()
