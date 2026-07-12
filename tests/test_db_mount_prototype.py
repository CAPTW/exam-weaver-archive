from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

import pytest

from experiments.db_mount_prototype.domain_split import classify_exam, split_database_by_domain
from experiments.db_mount_prototype.mount_repo import (
    MountedDatabase,
    MountedExamRepository,
    namespaced_value,
    write_manifest,
)
from src.database.repository import ExamRepository
from src.parser.question import Choice, Question
from src.quiz.generator import MockExamGenerator


def _make_db(path, question_text):
    repo = ExamRepository(str(path))
    repo.init_database()
    metadata = SimpleNamespace(year=2024, session=1, exam_type="3급기관사")
    repo.save_questions([
        Question(
            number=1,
            text=question_text,
            choices=[
                Choice(number=1, symbol="㉮", text="가"),
                Choice(number=2, symbol="㉯", text="나"),
                Choice(number=3, symbol="㉴", text="사"),
                Choice(number=4, symbol="㉵", text="아"),
            ],
            correct_answer=2,
            subject_name="기관1",
            year=2024,
            session=1,
            exam_type="3급기관사",
        )
    ], metadata)
    return repo


def _add_question(repo, exam_type, subject_name, question_text, *, session=1):
    metadata = SimpleNamespace(year=2024, session=session, exam_type=exam_type)
    repo.save_questions([
        Question(
            number=1,
            text=question_text,
            choices=[
                Choice(number=1, symbol="㉮", text="가"),
                Choice(number=2, symbol="㉯", text="나"),
                Choice(number=3, symbol="㉴", text="사"),
                Choice(number=4, symbol="㉵", text="아"),
            ],
            correct_answer=1,
            subject_name=subject_name,
            year=2024,
            session=session,
            exam_type=exam_type,
        )
    ], metadata)


def test_mounted_repository_namespaces_filter_options_and_questions(tmp_path):
    first_db = tmp_path / "first.db"
    second_db = tmp_path / "second.db"
    _make_db(first_db, "첫 번째 mounted DB 문제")
    _make_db(second_db, "두 번째 mounted DB 문제")
    manifest = tmp_path / "mounts.json"
    write_manifest(
        manifest,
        [
            MountedDatabase(id="first", label="First", domain="alpha", path=first_db),
            MountedDatabase(id="second", label="Second", domain="beta", path=second_db),
        ],
    )

    repo = MountedExamRepository(manifest)
    options = repo.get_filter_options()
    exam_codes = {row["code"] for row in options["exams"]}

    assert namespaced_value("first", "3급기관사") in exam_codes
    assert namespaced_value("second", "3급기관사") in exam_codes
    assert {row["id"] for row in options["mounts"]} == {"first", "second"}

    first_subjects = repo.get_subject_options(namespaced_value("first", "3급기관사"))
    assert namespaced_value("first", "engine1") in {row["code"] for row in first_subjects}

    first_questions = repo.get_questions_with_choices(
        exam_code=namespaced_value("first", "3급기관사"),
        subject_code=namespaced_value("first", "engine1"),
        limit=None,
    )
    assert len(first_questions) == 1
    assert first_questions[0]["id"].startswith("first::")
    assert first_questions[0]["local_id"] == 1
    assert first_questions[0]["mount_id"] == "first"
    assert first_questions[0]["mounted_exam_code"] == "first::3급기관사"
    assert len(first_questions[0]["choices"]) == 4
    assert first_questions[0]["choices"][0]["question_id"] == first_questions[0]["id"]

    all_questions = repo.get_questions_with_choices(exam_code="3급기관사", limit=None)
    assert [row["mount_id"] for row in all_questions] == ["first", "second"]


def test_mounted_repository_get_question_uses_namespaced_id(tmp_path):
    db_path = tmp_path / "main.db"
    _make_db(db_path, "단건 조회 문제")
    manifest = tmp_path / "mounts.json"
    write_manifest(
        manifest,
        [MountedDatabase(id="main", label="Main", domain="all", path=db_path)],
    )

    repo = MountedExamRepository(manifest)
    question = repo.get_question("main::1")

    assert question is not None
    assert question["id"] == "main::1"
    assert question["question_text"] == "단건 조회 문제"
    assert [choice["text"] for choice in question["choices"]] == ["가", "나", "사", "아"]
    assert question["mounted_exam_code"] == "main::3급기관사"
    assert question["mounted_subject_code"] == "main::engine1"
    assert question["mount_label"] == "Main"
    assert question["choices"][0]["id"].startswith("main::")


def test_mounted_repository_routes_writes_to_read_only_marked_owner(tmp_path):
    first_db = tmp_path / "first.db"
    second_db = tmp_path / "second.db"
    _make_db(first_db, "첫 원본")
    _make_db(second_db, "둘 원본")
    manifest = tmp_path / "mounts.json"
    write_manifest(
        manifest,
        [
            MountedDatabase(id="first", label="First", path=first_db, read_only=True),
            MountedDatabase(id="second", label="Second", path=second_db, read_only=True),
        ],
    )
    mounted = MountedExamRepository(manifest)

    assert mounted.update_question("first::1", {
        "exam_code": "first::3급기관사",
        "subject_code": "first::engine1",
        "question_text": "수정됨",
        "correct_answer": 2,
        "tags": "#custom",
    })
    assert ExamRepository(str(first_db)).get_question(1)["question_text"] == "수정됨"
    assert ExamRepository(str(second_db)).get_question(1)["question_text"] == "둘 원본"

    assert mounted.update_question_explanation("first::1", "사용자 해설")
    assert ExamRepository(str(first_db)).get_question(1)["explanation"] == "사용자 해설"

    assert mounted.delete_question("first::1")
    assert ExamRepository(str(first_db)).get_question(1) is None
    assert ExamRepository(str(second_db)).get_question(1) is not None


def test_mounted_crud_rejects_invalid_available_answer_pair(tmp_path):
    db_path = tmp_path / "main.db"
    _make_db(db_path, "보존할 문제")
    manifest = tmp_path / "mounts.json"
    write_manifest(
        manifest,
        [MountedDatabase(id="main", label="Main", path=db_path)],
    )

    with pytest.raises(RuntimeError, match="수정하지 못했습니다"):
        MountedExamRepository(manifest).update_question("main::1", {
            "question_text": "저장되면 안 되는 문제",
            "answer_available": True,
            "correct_answer": 5,
        })

    assert ExamRepository(str(db_path)).get_question(1)["question_text"] == "보존할 문제"


def test_mounted_repository_bulk_delete_groups_ids_by_owner(tmp_path):
    first_db = tmp_path / "first.db"
    second_db = tmp_path / "second.db"
    _make_db(first_db, "첫 문제")
    _make_db(second_db, "둘 문제")
    manifest = tmp_path / "mounts.json"
    write_manifest(
        manifest,
        [
            MountedDatabase(id="first", label="First", path=first_db),
            MountedDatabase(id="second", label="Second", path=second_db),
        ],
    )

    assert MountedExamRepository(manifest).delete_questions(["first::1", "second::1"]) == 2
    assert ExamRepository(str(first_db)).get_question(1) is None
    assert ExamRepository(str(second_db)).get_question(1) is None


@pytest.mark.parametrize("question_id", [1, "missing::1", "disabled::1", "first::bad"])
def test_mounted_repository_rejects_unsafe_write_ids_without_changes(tmp_path, question_id):
    first_db = tmp_path / "first.db"
    disabled_db = tmp_path / "disabled.db"
    _make_db(first_db, "보존할 문제")
    _make_db(disabled_db, "비활성 문제")
    manifest = tmp_path / "mounts.json"
    write_manifest(
        manifest,
        [
            MountedDatabase(id="first", label="First", path=first_db),
            MountedDatabase(id="disabled", label="Disabled", path=disabled_db, enabled=False),
        ],
    )
    mounted = MountedExamRepository(manifest)

    with pytest.raises(ValueError):
        mounted.delete_questions(["first::1", question_id])

    assert ExamRepository(str(first_db)).get_question(1)["question_text"] == "보존할 문제"
    assert ExamRepository(str(disabled_db)).get_question(1)["question_text"] == "비활성 문제"


def test_mounted_repository_applies_limit_after_global_sort(tmp_path):
    first_db = tmp_path / "first.db"
    second_db = tmp_path / "second.db"
    _make_db(first_db, "older")
    _make_db(second_db, "newest")
    with sqlite3.connect(second_db) as conn:
        conn.execute("UPDATE questions SET session = 2")
    manifest = tmp_path / "mounts.json"
    write_manifest(
        manifest,
        [
            MountedDatabase(id="first", label="First", path=first_db),
            MountedDatabase(id="second", label="Second", path=second_db),
        ],
    )

    rows = MountedExamRepository(manifest).search_questions(limit=1)

    assert len(rows) == 1
    assert rows[0]["question_text"] == "newest"
    assert rows[0]["id"].startswith("second::")


def test_domain_classifier_keeps_maritime_and_diat_separate():
    assert classify_exam("3급기관사", "3급 기관사") == "maritime"
    assert classify_exam("DIAT 정보통신상식", "DIAT 정보통신상식") == "computer_it"
    assert classify_exam("9급 국가직 공무원 컴퓨터일반", "9급 국가직 공무원 컴퓨터일반") == "public_service"
    assert classify_exam("알수없는시험", "알수없는시험") == "other"


def test_split_database_by_domain_creates_mountable_domain_dbs(tmp_path):
    source_db = tmp_path / "source.db"
    repo = ExamRepository(str(source_db))
    repo.init_database()
    _add_question(repo, "3급기관사", "기관1", "기관 문제")
    _add_question(repo, "DIAT 정보통신상식", "컴퓨터 이해", "DIAT 문제", session=41)
    with sqlite3.connect(source_db) as conn:
        conn.execute(
            "UPDATE questions SET source_id = 0 WHERE question_text = ?",
            ("기관 문제",),
        )
        conn.commit()

    manifest = tmp_path / "domain_mounts.json"
    result = split_database_by_domain(
        source_db,
        tmp_path / "domains",
        domains=["maritime", "computer_it"],
        manifest_out=manifest,
    )

    assert result["domains"]["maritime"]["counts"]["questions"] == 1
    assert result["domains"]["maritime"]["counts"]["question_sources"] == 1
    assert result["domains"]["computer_it"]["counts"]["questions"] == 1
    assert manifest.exists()
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert {mount["read_only"] for mount in manifest_payload["mounts"]} == {False}

    mounted = MountedExamRepository(manifest)
    maritime_questions = mounted.get_questions_with_choices(
        exam_code="maritime::3급기관사",
        limit=None,
    )
    diat_questions = mounted.get_questions_with_choices(
        exam_code="computer_it::DIAT 정보통신상식",
        limit=None,
    )

    assert [question["question_text"] for question in maritime_questions] == ["기관 문제"]
    assert [question["question_text"] for question in diat_questions] == ["DIAT 문제"]

    maritime_repo = ExamRepository(result["domains"]["maritime"]["path"])
    mock_exam = MockExamGenerator(maritime_repo).create("3급기관사", ["engine1"], count=1)
    assert mock_exam["total_questions"] == 1

    diat_repo = ExamRepository(result["domains"]["computer_it"]["path"])
    diat_subject = diat_repo.get_subject_options("DIAT 정보통신상식")[0]["code"]
    diat_mock_exam = MockExamGenerator(diat_repo).create(
        "DIAT 정보통신상식",
        [diat_subject],
        count=1,
    )
    assert diat_mock_exam["total_questions"] == 1

    with sqlite3.connect(result["domains"]["computer_it"]["path"]) as conn:
        assert conn.execute("SELECT COUNT(*) FROM mock_exams").fetchone()[0] == 1
