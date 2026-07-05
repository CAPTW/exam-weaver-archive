from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.db_mount_prototype.mount_repo import (  # noqa: E402
    MountedDatabase,
    MountedExamRepository,
    load_manifest,
    namespaced_value,
    write_manifest,
)
from src.database.repository import ExamRepository  # noqa: E402
from src.quiz.generator import MockExamGenerator  # noqa: E402


TABLES = [
    "exams",
    "subjects",
    "exam_subjects",
    "question_sources",
    "question_groups",
    "questions",
    "question_choices",
]


def _counts(path: Path) -> Dict[str, int]:
    with sqlite3.connect(path) as conn:
        return {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in TABLES
        }


def _integrity(path: Path) -> Dict[str, Any]:
    with sqlite3.connect(path) as conn:
        return {
            "integrity_check": conn.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_errors": conn.execute("PRAGMA foreign_key_check").fetchall(),
        }


def _candidate_exam_subjects(path: Path, limit: int = 20) -> List[Dict[str, Any]]:
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT
                e.code AS exam_code,
                s.code AS subject_code,
                s.name_ko AS subject_name,
                COUNT(q.id) AS question_count
            FROM questions q
            JOIN exam_subjects es ON es.id = q.exam_subject_id
            JOIN exams e ON e.id = es.exam_id
            JOIN subjects s ON s.id = es.subject_id
            GROUP BY e.code, s.code, s.name_ko
            HAVING COUNT(q.id) > 0
            ORDER BY COUNT(q.id) DESC, e.code ASC, s.code ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def _verify_individual_mount(mount: MountedDatabase, work_dir: Path) -> Dict[str, Any]:
    single_manifest = work_dir / f"{mount.id}.manifest.json"
    write_manifest(single_manifest, [mount], metadata={"purpose": "single mount verification"})
    repo = MountedExamRepository(single_manifest)
    repo.validate_mounts()
    stats = repo.get_statistics()
    sample = repo.get_questions_with_choices(limit=1)
    return {
        "manifest": str(single_manifest),
        "statistics_total_questions": stats["total_questions"],
        "sample_question_id": sample[0]["id"] if sample else None,
        "sample_choice_count": len(sample[0].get("choices") or []) if sample else 0,
    }


def _verify_mock_exam_generation(mount: MountedDatabase, work_dir: Path) -> Dict[str, Any]:
    candidates = _candidate_exam_subjects(mount.path)
    copy_path = work_dir / f"{mount.id}.{uuid.uuid4().hex}.mocktest.db"
    shutil.copy2(mount.path, copy_path)
    copy_path.chmod(0o666)

    attempts = []
    try:
        repo = ExamRepository(str(copy_path))
        generator = MockExamGenerator(repo)
        for candidate in candidates:
            exam_code = candidate["exam_code"]
            subject_code = candidate["subject_code"]
            try:
                mock_exam = generator.create(exam_code, [subject_code], count=1)
            except Exception as exc:  # keep trying; report failed candidates for diagnosis
                attempts.append({
                    **candidate,
                    "ok": False,
                    "error": str(exc),
                })
                continue

            with sqlite3.connect(copy_path) as conn:
                selected = conn.execute(
                    """
                    SELECT q.id, e.code, s.code
                    FROM mock_exam_questions meq
                    JOIN questions q ON q.id = meq.question_id
                    JOIN exam_subjects es ON es.id = q.exam_subject_id
                    JOIN exams e ON e.id = es.exam_id
                    JOIN subjects s ON s.id = es.subject_id
                    WHERE meq.mock_exam_id = ?
                    """,
                    (mock_exam["id"],),
                ).fetchall()
            attempts.append({
                **candidate,
                "ok": True,
                "mock_exam_id": mock_exam["id"],
                "total_questions": mock_exam["total_questions"],
                "selected": selected,
            })
            return {
                "ok": True,
                "db_copy": str(copy_path),
                "attempts": attempts,
            }

        return {
            "ok": False,
            "db_copy": str(copy_path),
            "attempts": attempts,
        }
    finally:
        try:
            copy_path.unlink()
        except (FileNotFoundError, PermissionError):
            pass


def verify(
    manifest_path: str | Path,
    *,
    source_snapshot_manifest: Optional[str | Path] = None,
    out_path: Optional[str | Path] = None,
) -> Dict[str, Any]:
    manifest = Path(manifest_path).resolve()
    work_dir = ROOT / "tmp" / "domain_mount_verification"
    work_dir.mkdir(parents=True, exist_ok=True)

    mounts = load_manifest(manifest)
    mounted_repo = MountedExamRepository(manifest)
    mounted_repo.validate_mounts()
    mounted_stats = mounted_repo.get_statistics()

    seen_namespaced_question_ids = set()
    local_question_ids = set()
    duplicate_local_question_ids = 0
    domain_results = {}
    sum_questions = 0
    sum_choices = 0

    for mount in mounts:
        counts = _counts(mount.path)
        integrity = _integrity(mount.path)
        sum_questions += counts["questions"]
        sum_choices += counts["question_choices"]

        with sqlite3.connect(mount.path) as conn:
            for (question_id,) in conn.execute("SELECT id FROM questions"):
                namespaced = namespaced_value(mount.id, question_id)
                if namespaced in seen_namespaced_question_ids:
                    raise AssertionError(f"duplicate namespaced question id: {namespaced}")
                seen_namespaced_question_ids.add(namespaced)
                if question_id in local_question_ids:
                    duplicate_local_question_ids += 1
                local_question_ids.add(question_id)

        if integrity["integrity_check"] != "ok" or integrity["foreign_key_errors"]:
            raise AssertionError(f"integrity failed for {mount.id}: {integrity}")

        domain_results[mount.id] = {
            "path": str(mount.path),
            "read_only": mount.read_only,
            "file_read_only": not bool(mount.path.stat().st_mode & 0o200),
            "counts": counts,
            "integrity": {
                "integrity_check": integrity["integrity_check"],
                "foreign_key_error_count": len(integrity["foreign_key_errors"]),
            },
            "individual_mount": _verify_individual_mount(mount, work_dir),
            "mock_exam_generation": _verify_mock_exam_generation(mount, work_dir),
        }

        if not domain_results[mount.id]["mock_exam_generation"]["ok"]:
            raise AssertionError(f"mock exam generation failed for mount: {mount.id}")

    expected = None
    if source_snapshot_manifest:
        payload = json.loads(Path(source_snapshot_manifest).read_text(encoding="utf-8"))
        expected = payload.get("counts", {})
        if expected.get("questions") != sum_questions:
            raise AssertionError(
                f"question count mismatch: expected {expected.get('questions')}, got {sum_questions}"
            )
        if expected.get("question_choices") != sum_choices:
            raise AssertionError(
                f"choice count mismatch: expected {expected.get('question_choices')}, got {sum_choices}"
            )

    result = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "manifest": str(manifest),
        "mount_count": len(mounts),
        "mounted_statistics_total_questions": mounted_stats["total_questions"],
        "sum_domain_questions": sum_questions,
        "sum_domain_choices": sum_choices,
        "expected_source_counts": expected,
        "namespaced_question_ids": len(seen_namespaced_question_ids),
        "duplicate_local_question_ids_across_domains": duplicate_local_question_ids,
        "domains": domain_results,
    }

    if mounted_stats["total_questions"] != sum_questions:
        raise AssertionError(
            f"mounted stats mismatch: expected {sum_questions}, got {mounted_stats['total_questions']}"
        )

    if out_path:
        out = Path(out_path).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["out_path"] = str(out)

    return result


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify split domain DB mounts and mock exam generation.")
    parser.add_argument("--manifest", default="data/domain_dbs/mount_manifest.json")
    parser.add_argument("--source-snapshot-manifest", default="data/main_snapshots/MAIN_SNAPSHOT.json")
    parser.add_argument("--out", default="tmp/domain_mount_verification_report.json")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    result = verify(
        args.manifest,
        source_snapshot_manifest=args.source_snapshot_manifest,
        out_path=args.out,
    )
    print(json.dumps({
        "mount_count": result["mount_count"],
        "mounted_statistics_total_questions": result["mounted_statistics_total_questions"],
        "sum_domain_questions": result["sum_domain_questions"],
        "sum_domain_choices": result["sum_domain_choices"],
        "namespaced_question_ids": result["namespaced_question_ids"],
        "duplicate_local_question_ids_across_domains": result["duplicate_local_question_ids_across_domains"],
        "out_path": result.get("out_path"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
