from pathlib import Path

from scripts.audit_question_repo import build_parse_jobs, classify_files


def test_build_parse_jobs_pairs_modern_question_files_with_year_answer():
    root = Path("E:/repo")
    files = [
        root / "2024" / "2024_2024_answer2.pdf",
        root / "2024" / "2024_202403.pdf",
        root / "2024" / "2024_202413.zip",
        root / "2024" / "2024_4급 기관사.pdf",
        root / "2025" / "2025_202525.pdf",
        root / "2025" / "2025_202503.pdf",
        root / "2025" / "2025_202513.zip",
    ]

    classified = classify_files(root, files)
    jobs = build_parse_jobs(classified)

    pairs = {(job.question_path.name, job.answer_path.name) for job in jobs}
    assert pairs == {
        ("2024_202403.pdf", "2024_2024_answer2.pdf"),
        ("2024_202413.zip", "2024_2024_answer2.pdf"),
        ("2025_202503.pdf", "2025_202525.pdf"),
        ("2025_202513.zip", "2025_202525.pdf"),
    }


def test_classify_files_separates_unsupported_reference_pdfs():
    root = Path("E:/repo")
    files = [
        root / "2023" / "3급 항해사(상선).pdf",
        root / "2023" / "2023_2023_answer2.pdf",
    ]

    classified = classify_files(root, files)

    assert classified.answer_files == [root / "2023" / "2023_2023_answer2.pdf"]
    assert classified.unsupported_files == [root / "2023" / "3급 항해사(상선).pdf"]


def test_build_parse_jobs_prefers_modern_year_answer_bundle_over_individual_answers():
    root = Path("E:/repo")
    files = [
        root / "2020" / "2020 1급기관답안.pdf",
        root / "2020" / "2020 3급기관답안.pdf",
        root / "2020" / "2020_2020_answer.zip",
        root / "2020" / "2020_202003.zip",
    ]

    classified = classify_files(root, files)
    jobs = build_parse_jobs(classified)

    assert [(job.question_path.name, job.answer_path.name) for job in jobs] == [
        ("2020_202003.zip", "2020_2020_answer.zip")
    ]
