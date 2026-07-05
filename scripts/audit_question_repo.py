"""Audit a local question-file repository without touching the production DB."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.database.repository import ExamRepository
from src.database.validator import QuestionValidator
from src.parser.main import ExamPDFParser


SUPPORTED_SUFFIXES = {".pdf", ".zip"}


@dataclass
class ClassifiedFiles:
    root: Path
    all_files: list[Path]
    answer_files: list[Path]
    question_files: list[Path]
    unsupported_files: list[Path]


@dataclass
class ParseJob:
    year: int
    question_path: Path
    answer_path: Path


@dataclass
class ParseJobResult:
    question_path: str
    answer_path: str
    status: str
    saved_count: int = 0
    metadata: list[dict] | None = None
    stats: dict | None = None
    errors: list[str] | None = None
    warnings: list[str] | None = None
    exception: str | None = None


def iter_supported_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    )


def classify_files(root: Path, files: Optional[Iterable[Path]] = None) -> ClassifiedFiles:
    all_files = sorted(files if files is not None else iter_supported_files(root))
    answer_files = []
    question_files = []
    unsupported_files = []

    for path in all_files:
        if is_answer_file(path):
            answer_files.append(path)
        elif is_modern_question_file(path):
            question_files.append(path)
        else:
            unsupported_files.append(path)

    return ClassifiedFiles(
        root=root,
        all_files=all_files,
        answer_files=answer_files,
        question_files=question_files,
        unsupported_files=unsupported_files,
    )


def is_answer_file(path: Path) -> bool:
    name = path.name.lower()
    year = year_from_path(path)
    if "answer" in name or "답안" in name:
        return True
    if year and path.suffix.lower() == ".pdf" and name == f"{year}_{year}25.pdf":
        return True
    if year and path.suffix.lower() == ".zip" and name == f"{year}_{year}_answer.zip":
        return True
    return False


def is_modern_question_file(path: Path) -> bool:
    year = year_from_path(path)
    if not year:
        return False
    name = path.stem
    if not name.startswith(f"{year}_{year}"):
        return False
    if is_answer_file(path):
        return False
    suffix_code = name.removeprefix(f"{year}_{year}")
    return suffix_code.isdigit() and len(suffix_code) == 2


def year_from_path(path: Path) -> Optional[int]:
    for part in path.parts:
        if part.isdigit() and len(part) == 4:
            year = int(part)
            if 1900 <= year <= 2100:
                return year

    stem = path.stem
    if len(stem) >= 4 and stem[:4].isdigit():
        year = int(stem[:4])
        if 1900 <= year <= 2100:
            return year
    return None


def build_parse_jobs(
    classified: ClassifiedFiles,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
) -> list[ParseJob]:
    answers_by_year = defaultdict(list)
    for answer in classified.answer_files:
        year = year_from_path(answer)
        if year is not None:
            answers_by_year[year].append(answer)

    jobs = []
    for question in classified.question_files:
        year = year_from_path(question)
        if year is None:
            continue
        if year_from is not None and year < year_from:
            continue
        if year_to is not None and year > year_to:
            continue

        answer = preferred_answer_file(answers_by_year.get(year, []))
        if answer is None:
            continue
        jobs.append(ParseJob(year=year, question_path=question, answer_path=answer))

    return sorted(jobs, key=lambda job: (job.year, str(job.question_path)))


def preferred_answer_file(files: list[Path]) -> Optional[Path]:
    if not files:
        return None

    def priority(path: Path) -> tuple[int, str]:
        name = path.name.lower()
        year = year_from_path(path)
        if year and name == f"{year}_{year}_answer.zip":
            return (0, name)
        if "answer2" in name:
            return (1, name)
        if "answer" in name or "답안" in name:
            return (2, name)
        if name.endswith("25.pdf"):
            return (3, name)
        return (9, name)

    return sorted(files, key=priority)[0]


def run_audit(
    source_root: Path,
    output_dir: Path,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    max_jobs: Optional[int] = None,
    parse: bool = True,
) -> dict:
    source_root = source_root.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    classified = classify_files(source_root)
    jobs = build_parse_jobs(classified, year_from=year_from, year_to=year_to)
    if max_jobs is not None:
        jobs = jobs[:max_jobs]

    staging_db = output_dir / "staging_exam_bank.db"
    if staging_db.exists():
        staging_db.unlink()
    repo = ExamRepository(str(staging_db))
    repo.init_database()

    results = []
    if parse:
        previous_parser_level = logging.getLogger("src.parser").level
        previous_pypdf_level = logging.getLogger("pypdf").level
        logging.getLogger("src.parser").setLevel(logging.CRITICAL)
        logging.getLogger("pypdf").setLevel(logging.CRITICAL)
        try:
            parser = ExamPDFParser(work_dir=str(output_dir / "extracted"))
            for job in jobs:
                results.append(parse_one_job(parser, repo, job))
        finally:
            logging.getLogger("src.parser").setLevel(previous_parser_level)
            logging.getLogger("pypdf").setLevel(previous_pypdf_level)

    findings = []
    if parse:
        findings = QuestionValidator(repo).scan(limit=None)

    report = {
        "source_root": str(source_root),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "staging_db": str(staging_db),
        "inventory": inventory_summary(classified),
        "parse_jobs": [serialize_job(job) for job in jobs],
        "parse_results": [asdict(result) for result in results],
        "validator_summary": validator_summary(findings),
        "validator_findings": serialize_findings(findings),
    }

    json_path = output_dir / "audit_report.json"
    markdown_path = output_dir / "audit_report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(render_markdown_report(report), encoding="utf-8")
    report["json_report"] = str(json_path)
    report["markdown_report"] = str(markdown_path)
    return report


def parse_one_job(parser: ExamPDFParser, repo: ExamRepository, job: ParseJob) -> ParseJobResult:
    try:
        result = parser.parse(str(job.question_path), str(job.answer_path))
        validation = result["validation"]
        saved_count = 0
        status = "parsed"
        if validation.errors:
            status = "validation_failed"
        else:
            saved_count = repo.save_questions(result["questions"], result["metadata"])
        metadata = [
            {
                "year": meta.year,
                "session": meta.session,
                "exam_type": meta.exam_type,
                "is_domestic": meta.is_domestic,
            }
            for meta in result.get("metadata_list") or [result["metadata"]]
        ]
        return ParseJobResult(
            question_path=str(job.question_path),
            answer_path=str(job.answer_path),
            status=status,
            saved_count=saved_count,
            metadata=metadata,
            stats=result.get("stats"),
            errors=list(validation.errors),
            warnings=list(validation.warnings),
        )
    except Exception as exc:
        return ParseJobResult(
            question_path=str(job.question_path),
            answer_path=str(job.answer_path),
            status="failed",
            errors=[],
            warnings=[],
            exception=f"{type(exc).__name__}: {exc}",
        )


def inventory_summary(classified: ClassifiedFiles) -> dict:
    by_suffix = Counter(path.suffix.lower() for path in classified.all_files)
    by_year = defaultdict(Counter)
    for path in classified.all_files:
        year = year_from_path(path) or "unknown"
        by_year[str(year)][path.suffix.lower()] += 1

    return {
        "total_files": len(classified.all_files),
        "by_suffix": dict(sorted(by_suffix.items())),
        "by_year": {
            year: dict(sorted(counter.items()))
            for year, counter in sorted(by_year.items())
        },
        "answer_file_count": len(classified.answer_files),
        "modern_question_file_count": len(classified.question_files),
        "unsupported_file_count": len(classified.unsupported_files),
        "unsupported_samples": [str(path) for path in classified.unsupported_files[:50]],
    }


def validator_summary(findings: list[dict]) -> dict:
    by_code = Counter()
    by_severity = Counter()
    for finding in findings:
        by_severity[finding["severity"]] += 1
        for issue in finding["issues"]:
            by_code[issue["code"]] += 1
    return {
        "finding_count": len(findings),
        "by_severity": dict(sorted(by_severity.items())),
        "by_issue_code": dict(sorted(by_code.items())),
    }


def serialize_findings(findings: list[dict]) -> list[dict]:
    serialized = []
    for finding in findings:
        question = finding["question"]
        serialized.append({
            "question_id": finding["question_id"],
            "severity": finding["severity"],
            "summary": finding["summary"],
            "issues": finding["issues"],
            "question": {
                "id": question.get("id"),
                "year": question.get("year"),
                "session": question.get("session"),
                "exam_name": question.get("exam_name"),
                "subject_name": question.get("subject_name"),
                "question_number": question.get("question_number"),
                "question_text": question.get("question_text"),
            },
        })
    return serialized


def serialize_job(job: ParseJob) -> dict:
    return {
        "year": job.year,
        "question_path": str(job.question_path),
        "answer_path": str(job.answer_path),
    }


def render_markdown_report(report: dict) -> str:
    parsed = [item for item in report["parse_results"] if item["status"] in {"parsed", "validation_failed"}]
    failed = [item for item in report["parse_results"] if item["status"] == "failed"]
    validation_error_jobs = [
        item for item in report["parse_results"]
        if item.get("errors")
    ]

    lines = [
        "# Question Repository Audit",
        "",
        f"- Source: `{report['source_root']}`",
        f"- Staging DB: `{report['staging_db']}`",
        f"- Files: {report['inventory']['total_files']}",
        f"- Modern parse jobs: {len(report['parse_jobs'])}",
        f"- Parsed jobs: {len(parsed)}",
        f"- Saved jobs: {sum(1 for item in parsed if item['status'] == 'parsed')}",
        f"- Failed jobs: {len(failed)}",
        f"- Jobs with validation errors: {len(validation_error_jobs)}",
        f"- Validator findings: {report['validator_summary']['finding_count']}",
        "",
        "## Inventory",
        "",
        f"- Answer files: {report['inventory']['answer_file_count']}",
        f"- Modern question files: {report['inventory']['modern_question_file_count']}",
        f"- Unsupported/reference files: {report['inventory']['unsupported_file_count']}",
        "",
        "## Parse Failures",
        "",
    ]

    if failed:
        for item in failed:
            lines.append(f"- `{item['question_path']}`: {item.get('exception')}")
    else:
        lines.append("- None")

    lines.extend(["", "## Validation Errors", ""])
    if validation_error_jobs:
        for item in validation_error_jobs:
            lines.append(f"- `{item['question_path']}`")
            for error in item.get("errors") or []:
                lines.append(f"  - {error}")
    else:
        lines.append("- None")

    lines.extend(["", "## Validator Issue Counts", ""])
    issue_counts = report["validator_summary"].get("by_issue_code") or {}
    if issue_counts:
        for code, count in issue_counts.items():
            lines.append(f"- `{code}`: {count}")
    else:
        lines.append("- None")

    return "\n".join(lines) + "\n"


def default_output_dir() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return PROJECT_ROOT / "tmp" / f"repo_audit_{timestamp}"


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--year-from", type=int, default=None)
    parser.add_argument("--year-to", type=int, default=None)
    parser.add_argument("--max-jobs", type=int, default=None)
    parser.add_argument("--no-parse", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    output_dir = args.output_dir or default_output_dir()
    report = run_audit(
        args.source_root,
        output_dir,
        year_from=args.year_from,
        year_to=args.year_to,
        max_jobs=args.max_jobs,
        parse=not args.no_parse,
    )
    print(f"JSON report: {report['json_report']}")
    print(f"Markdown report: {report['markdown_report']}")
    print(f"Staging DB: {report['staging_db']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
