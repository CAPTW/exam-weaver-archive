from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .mount_repo import MountedDatabase, write_manifest


DOMAIN_KEYWORDS: Dict[str, List[str]] = {
    "maritime": [
        "항해사", "기관사", "자격", "상선", "어선", "소형선박", "운항사", "해양",
        "항로표지",
    ],
    "public_service": [
        "공무원", "경찰", "소방공무원", "군무원", "교정", "보호직", "검찰직",
        "세무직", "관세직", "행정직", "교육행정", "법원직", "PSAT",
    ],
    "computer_it": [
        "DIAT", "정보통신", "정보처리", "정보기기", "정보보안", "컴퓨터", "컴활",
        "워드", "리눅스", "네트워크", "사무자동화", "ITQ", "PC정비", "웹디자인",
        "전산", "멀티미디어", "전자상거래", "인터넷정보", "방송통신", "무선설비",
        "인터넷보안", "통신설비", "전파전자통신", "육상무선통신", "전자계산기",
        "전자캐드", "전자산업", "전자기사", "전자기능", "임베디드", "프로그래밍",
        "지능형홈", "통신선로", "영상정보",
    ],
    "accounting_business": [
        "회계", "세무", "ERP", "전산세무", "전산회계", "기업회계", "유통관리",
        "물류관리", "무역영어", "텔레마케팅", "사회조사분석",
    ],
    "professional_services": [
        "가맹거래사", "경영지도사", "감정평가사", "공인중개사", "주택관리사",
        "경비지도사", "직업상담사", "청소년상담사", "소비자전문상담사",
        "사회복지사", "비서", "변리사", "노무사", "손해평가사", "관광통역안내사",
        "국내여행안내사", "검량사", "행정사", "컨벤션기획사",
    ],
    "construction_real_estate": [
        "건축", "토목", "측량", "지형공간", "지적", "도시계획", "콘크리트",
        "건설재료", "응용지질", "조경",
    ],
    "transport_aviation": [
        "교통", "철도", "항공", "항공기체", "항공기관", "항공장비",
    ],
    "agriculture_environment": [
        "자연생태", "수산", "어로", "양식", "식물보호", "축산", "산림",
        "임업", "유기농업", "종자", "화훼", "버섯종균", "농산물품질", "수산물품질",
        "임산", "원예", "어업", "생물분류", "환경", "수질", "대기", "폐기물",
        "정수시설", "소음진동", "기상",
    ],
    "industrial_technical": [
        "산업안전", "건설안전", "소방", "위험물", "가스", "전기", "전기공사",
        "기계", "건설기계", "공조냉동", "에너지관리", "용접", "자동차정비",
        "화공", "화학분석", "바이오화학", "화약류", "비파괴검사", "금속재료",
        "원자력", "신재생에너지", "생산자동화", "공유압", "자동차보수도장",
        "자동차차체수리", "압연", "제강", "제선", "연삭", "광학", "배관",
        "금형", "잠수", "방재", "화약취급", "지게차", "굴삭기", "승강기",
        "품질경영", "산업위생", "인간공학", "화재감식",
    ],
    "medical_health": [
        "간호", "보건", "의료", "임상", "물리치료", "치위생", "응급구조",
        "영양사", "위생사", "방사선", "작업치료", "의공",
    ],
    "education_language_history": [
        "한국사", "한자", "영어", "일본어", "중국어", "한국어", "교육", "교원",
        "문해교육",
    ],
    "design_media_food": [
        "시각디자인", "컬러리스트", "제품디자인", "실내건축", "컴퓨터그래픽스",
        "사진", "인쇄", "전자출판", "식품", "조주", "제과", "제빵", "미용",
        "조리", "바리스타", "패션", "보석감정", "세탁", "식육", "여성복",
        "의류", "영사",
    ],
}


@dataclass(frozen=True)
class ExamDomainRow:
    exam_id: int
    code: str
    name: str
    domain: str
    question_count: int


def classify_exam(code: str, name: str) -> str:
    haystack = f"{code} {name}".upper()
    for domain, keywords in DOMAIN_KEYWORDS.items():
        for keyword in keywords:
            if keyword.upper() in haystack:
                return domain
    return "other"


def scan_domains(db_path: str | Path) -> List[ExamDomainRow]:
    path = Path(db_path).resolve()
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT
                e.id AS exam_id,
                e.code,
                e.name,
                COUNT(q.id) AS question_count
            FROM exams e
            LEFT JOIN exam_subjects es ON es.exam_id = e.id
            LEFT JOIN questions q ON q.exam_subject_id = es.id
            GROUP BY e.id, e.code, e.name
            ORDER BY e.name, e.code
            """
        ).fetchall()
    return [
        ExamDomainRow(
            exam_id=int(row["exam_id"]),
            code=str(row["code"]),
            name=str(row["name"]),
            domain=classify_exam(str(row["code"]), str(row["name"])),
            question_count=int(row["question_count"] or 0),
        )
        for row in rows
    ]


def summarize_plan(rows: Iterable[ExamDomainRow]) -> Dict[str, Any]:
    summary: Dict[str, Any] = defaultdict(lambda: {
        "exam_count": 0,
        "question_count": 0,
        "examples": [],
    })
    for row in rows:
        bucket = summary[row.domain]
        bucket["exam_count"] += 1
        bucket["question_count"] += row.question_count
        if len(bucket["examples"]) < 12:
            bucket["examples"].append({
                "code": row.code,
                "name": row.name,
                "questions": row.question_count,
            })
    return dict(sorted(summary.items()))


def write_plan(db_path: str | Path, out_path: str | Path) -> Path:
    rows = scan_domains(db_path)
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_db": str(Path(db_path).resolve()),
        "domains": summarize_plan(rows),
        "exams": [
            {
                "exam_id": row.exam_id,
                "code": row.code,
                "name": row.name,
                "domain": row.domain,
                "question_count": row.question_count,
            }
            for row in rows
        ],
    }
    out = Path(out_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def write_single_snapshot_manifest(
    snapshot_path: str | Path,
    out_path: str | Path,
    *,
    mount_id: str = "main",
    label: str = "Main snapshot",
) -> Path:
    snapshot = Path(snapshot_path).resolve()
    mount = MountedDatabase(
        id=mount_id,
        label=label,
        domain="all",
        path=snapshot,
        enabled=True,
        read_only=True,
    )
    return write_manifest(
        out_path,
        [mount],
        metadata={
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "purpose": "Experimental DB mount prototype over the frozen Main snapshot.",
        },
    )


def split_database_by_domain(
    db_path: str | Path,
    out_dir: str | Path,
    *,
    domains: Optional[List[str]] = None,
    overwrite: bool = False,
    manifest_out: Optional[str | Path] = None,
) -> Dict[str, Any]:
    source = Path(db_path).resolve()
    output = Path(out_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)

    rows = scan_domains(source)
    selected_domains = set(domains or sorted({row.domain for row in rows}))
    rows_by_domain: Dict[str, List[ExamDomainRow]] = defaultdict(list)
    for row in rows:
        if row.domain in selected_domains:
            rows_by_domain[row.domain].append(row)

    results = {}
    mounts = []
    for domain, domain_rows in sorted(rows_by_domain.items()):
        target = output / f"exam_bank.{domain}.db"
        if target.exists():
            if not overwrite:
                raise FileExistsError(f"target exists; pass --overwrite to replace: {target}")
            target.unlink()

        _copy_domain_database(source, target, [row.exam_id for row in domain_rows])
        result = _database_counts(target)
        result["path"] = str(target)
        result["exam_ids"] = [row.exam_id for row in domain_rows]
        results[domain] = result
        mounts.append(MountedDatabase(
            id=domain,
            label=f"{domain} domain",
            domain=domain,
            path=target,
            enabled=True,
            read_only=False,
        ))

    if manifest_out:
        write_manifest(
            manifest_out,
            mounts,
            metadata={
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "source_db": str(source),
                "purpose": "Domain-split mount manifest generated by prototype script.",
            },
        )

    return {
        "source_db": str(source),
        "out_dir": str(output),
        "domains": results,
    }


def _copy_domain_database(source: Path, target: Path, exam_ids: List[int]) -> None:
    root = Path(__file__).resolve().parents[2]
    schema_path = root / "src" / "database" / "schema.sql"
    if not schema_path.exists():
        raise FileNotFoundError(f"schema not found: {schema_path}")

    with sqlite3.connect(target) as conn:
        conn.executescript(schema_path.read_text(encoding="utf-8"))
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("ATTACH DATABASE ? AS src", (str(source),))
        conn.execute("CREATE TEMP TABLE selected_exam_ids (id INTEGER PRIMARY KEY)")
        conn.executemany(
            "INSERT INTO selected_exam_ids (id) VALUES (?)",
            [(exam_id,) for exam_id in exam_ids],
        )
        conn.execute("""
            CREATE TEMP TABLE selected_exam_subject_ids AS
            SELECT es.id
            FROM src.exam_subjects es
            JOIN selected_exam_ids selected ON selected.id = es.exam_id
        """)
        conn.execute("""
            CREATE TEMP TABLE selected_question_ids AS
            SELECT q.id
            FROM src.questions q
            JOIN selected_exam_subject_ids selected ON selected.id = q.exam_subject_id
        """)
        conn.execute("""
            CREATE TEMP TABLE selected_group_ids AS
            SELECT DISTINCT q.group_id AS id
            FROM src.questions q
            JOIN selected_question_ids selected ON selected.id = q.id
            WHERE q.group_id IS NOT NULL
            UNION
            SELECT qg.id
            FROM src.question_groups qg
            JOIN selected_exam_subject_ids selected ON selected.id = qg.exam_subject_id
        """)
        conn.execute("""
            CREATE TEMP TABLE selected_source_ids AS
            SELECT DISTINCT q.source_id AS id
            FROM src.questions q
            JOIN selected_question_ids selected ON selected.id = q.id
            WHERE q.source_id IS NOT NULL
            UNION
            SELECT DISTINCT qg.source_id
            FROM src.question_groups qg
            JOIN selected_group_ids selected ON selected.id = qg.id
            WHERE qg.source_id IS NOT NULL
        """)

        conn.execute("""
            INSERT INTO exams (
                id, code, name, is_domestic_only, created_at
            )
            SELECT
                e.id, e.code, e.name, e.is_domestic_only, e.created_at
            FROM src.exams e
            JOIN selected_exam_ids selected ON selected.id = e.id
        """)
        conn.execute("""
            INSERT INTO subjects (
                id, code, name_ko, name_en, created_at
            )
            SELECT DISTINCT
                s.id, s.code, s.name_ko, s.name_en, s.created_at
            FROM src.subjects s
            JOIN src.exam_subjects es ON es.subject_id = s.id
            JOIN selected_exam_subject_ids selected ON selected.id = es.id
        """)
        conn.execute("""
            INSERT INTO exam_subjects (
                id, exam_id, subject_id, display_order, questions_count
            )
            SELECT
                es.id, es.exam_id, es.subject_id, es.display_order, es.questions_count
            FROM src.exam_subjects es
            JOIN selected_exam_subject_ids selected ON selected.id = es.id
        """)
        conn.execute("""
            INSERT INTO question_sources (
                id,
                provider,
                source_url,
                document_id,
                attachment_url,
                attachment_filename,
                content_hash,
                fetched_at
            )
            SELECT
                qs.id,
                qs.provider,
                qs.source_url,
                qs.document_id,
                qs.attachment_url,
                qs.attachment_filename,
                qs.content_hash,
                qs.fetched_at
            FROM src.question_sources qs
            JOIN selected_source_ids selected ON selected.id = qs.id
        """)
        conn.execute("""
            INSERT INTO question_sources (
                id,
                provider,
                source_url,
                document_id,
                attachment_url,
                attachment_filename,
                content_hash,
                fetched_at
            )
            SELECT
                selected.id,
                'legacy_missing_source',
                'missing-source:' || selected.id,
                NULL,
                NULL,
                NULL,
                'missing-source:' || selected.id,
                CURRENT_TIMESTAMP
            FROM selected_source_ids selected
            LEFT JOIN src.question_sources qs ON qs.id = selected.id
            WHERE qs.id IS NULL
        """)
        conn.execute("""
            INSERT INTO question_groups (
                id,
                exam_subject_id,
                year,
                session,
                group_number,
                group_type,
                shared_text,
                shared_image_path,
                source_id,
                source_page,
                tags,
                created_at
            )
            SELECT
                qg.id,
                qg.exam_subject_id,
                qg.year,
                qg.session,
                qg.group_number,
                qg.group_type,
                qg.shared_text,
                qg.shared_image_path,
                qg.source_id,
                qg.source_page,
                qg.tags,
                qg.created_at
            FROM src.question_groups qg
            JOIN selected_group_ids selected ON selected.id = qg.id
        """)
        conn.execute("""
            INSERT INTO questions (
                id,
                exam_subject_id,
                year,
                session,
                question_number,
                question_text,
                question_format_json,
                has_image,
                image_path,
                correct_answer,
                source_page,
                tags,
                group_id,
                group_order,
                source_id,
                source_question_id,
                created_at
            )
            SELECT
                q.id,
                q.exam_subject_id,
                q.year,
                q.session,
                q.question_number,
                q.question_text,
                q.question_format_json,
                q.has_image,
                q.image_path,
                q.correct_answer,
                q.source_page,
                q.tags,
                q.group_id,
                q.group_order,
                q.source_id,
                q.source_question_id,
                q.created_at
            FROM src.questions q
            JOIN selected_question_ids selected ON selected.id = q.id
        """)
        conn.execute("""
            INSERT INTO question_choices (
                id,
                question_id,
                choice_number,
                choice_symbol,
                choice_text,
                choice_format_json,
                choice_image_path
            )
            SELECT
                qc.id,
                qc.question_id,
                qc.choice_number,
                qc.choice_symbol,
                qc.choice_text,
                qc.choice_format_json,
                qc.choice_image_path
            FROM src.question_choices qc
            JOIN selected_question_ids selected ON selected.id = qc.question_id
        """)

        for table in [
            "exams", "subjects", "exam_subjects", "question_sources",
            "question_groups", "questions", "question_choices",
        ]:
            max_id = conn.execute(f"SELECT COALESCE(MAX(id), 0) FROM {table}").fetchone()[0]
            conn.execute(
                "INSERT OR REPLACE INTO sqlite_sequence(name, seq) VALUES (?, ?)",
                (table, max_id),
            )
        conn.commit()

        foreign_key_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_errors:
            raise sqlite3.IntegrityError(f"foreign key errors in {target}: {foreign_key_errors[:5]}")
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise sqlite3.IntegrityError(f"integrity_check failed in {target}: {integrity}")

    target.chmod(0o666)


def _database_counts(path: Path) -> Dict[str, Any]:
    with sqlite3.connect(path) as conn:
        counts = {}
        for table in [
            "exams", "subjects", "exam_subjects", "question_sources",
            "question_groups", "questions", "question_choices",
        ]:
            counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    return {
        "integrity_check": integrity,
        "counts": counts,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prototype domain split and mount helpers.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="Classify exams and write a dry-run split plan.")
    plan.add_argument("--db", default="data/exam_bank.db")
    plan.add_argument("--out", default="tmp/db_mount_domain_plan.json")

    manifest = subparsers.add_parser("manifest", help="Create a one-mount manifest for a snapshot DB.")
    manifest.add_argument("--snapshot", required=True)
    manifest.add_argument("--out", default="experiments/db_mount_prototype/mount_manifest.local.json")
    manifest.add_argument("--id", default="main")
    manifest.add_argument("--label", default="Main snapshot")

    split = subparsers.add_parser("split", help="Split a DB into domain DBs.")
    split.add_argument("--db", default="data/exam_bank.db")
    split.add_argument("--out-dir", default="data/domain_dbs")
    split.add_argument("--domain", action="append", dest="domains")
    split.add_argument("--overwrite", action="store_true")
    split.add_argument("--manifest-out", default="data/domain_dbs/mount_manifest.json")
    split.add_argument("--apply", action="store_true", help="Actually write split DBs.")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.command == "plan":
        out = write_plan(args.db, args.out)
        print(f"wrote domain plan: {out}")
        return 0
    if args.command == "manifest":
        out = write_single_snapshot_manifest(
            args.snapshot,
            args.out,
            mount_id=args.id,
            label=args.label,
        )
        print(f"wrote mount manifest: {out}")
        return 0
    if args.command == "split":
        if not args.apply:
            out = write_plan(args.db, Path(args.out_dir) / "domain_split_plan.json")
            print(f"dry-run only; wrote plan: {out}")
            print("pass --apply to create domain DB files")
            return 0
        result = split_database_by_domain(
            args.db,
            args.out_dir,
            domains=args.domains,
            overwrite=args.overwrite,
            manifest_out=args.manifest_out,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
