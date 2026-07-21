import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

import src.database.text_repair_batch as batch
from src.database.ocr_repairs import OcrRepairResult
from src.database.repository import ExamRepository
from src.database.text_repair_batch import (
    BatchRepairError,
    RepairTarget,
    commit_repair_batch,
    prepare_repair_batch,
)


def _create_valid_database(path: Path, label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    repository = ExamRepository(str(path))
    repository.init_database()
    template = repository.get_manual_question_template()
    template.update({
        "question_text": f"정상 발문 {label}",
        "correct_answer": 1,
        "choices": [
            {"choice_number": 1, "choice_symbol": "㉮", "choice_text": "A"},
            {"choice_number": 2, "choice_symbol": "㉯", "choice_text": "B"},
            {"choice_number": 3, "choice_symbol": "㉴", "choice_text": "C"},
            {"choice_number": 4, "choice_symbol": "㉵", "choice_text": "D"},
        ],
    })
    assert repository.create_manual_question(template) is not None


def _make_four_targets(tmp_path: Path) -> tuple[RepairTarget, ...]:
    targets = []
    for index, name in enumerate(("one", "two", "three", "four"), start=1):
        path = tmp_path / f"{name}.db"
        _create_valid_database(path, str(index))
        targets.append(RepairTarget(name, path))
    return tuple(targets)


def _repairs_path(tmp_path: Path) -> Path:
    path = tmp_path / "repairs.json"
    path.write_text(json.dumps({"repairs": []}), encoding="utf-8")
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _corrupt_format_json(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            UPDATE questions SET question_format_json = '[1, 2]'
            WHERE id = (SELECT MIN(id) FROM questions)
            """
        )


def test_prepare_batch_validates_every_staging_before_any_mount_change(
    tmp_path,
):
    targets = _make_four_targets(tmp_path)
    _corrupt_format_json(targets[-1].mounted_path)
    before = {
        target.name: _sha256(target.mounted_path) for target in targets
    }

    with pytest.raises(BatchRepairError, match="invalid_format_json"):
        prepare_repair_batch(
            targets,
            _repairs_path(tmp_path),
            tmp_path / "work",
        )

    assert {
        target.name: _sha256(target.mounted_path) for target in targets
    } == before


def test_commit_batch_rolls_back_every_replaced_database(
    tmp_path,
    monkeypatch,
):
    targets = _make_four_targets(tmp_path)
    prepared = prepare_repair_batch(
        targets,
        _repairs_path(tmp_path),
        tmp_path / "work",
    )
    before = {
        target.name: _sha256(target.mounted_path) for target in targets
    }
    real_replace = batch._atomic_replace
    mounted_calls = 0

    def fail_second_mounted(source, target):
        nonlocal mounted_calls
        if Path(target) in {item.mounted_path for item in targets}:
            mounted_calls += 1
            if mounted_calls == 2:
                raise OSError("simulated second replacement failure")
        return real_replace(source, target)

    monkeypatch.setattr(batch, "_atomic_replace", fail_second_mounted)

    with pytest.raises(
        BatchRepairError,
        match="simulated second replacement failure",
    ):
        commit_repair_batch(
            prepared,
            tmp_path / "backups",
            tmp_path / "receipt.json",
        )

    assert {
        target.name: _sha256(target.mounted_path) for target in targets
    } == before
    assert not (tmp_path / "receipt.json").exists()


def test_prepare_batch_applies_and_aggregates_multiple_repair_registries(
    tmp_path,
    monkeypatch,
):
    database = tmp_path / "one.db"
    _create_valid_database(database, "1")
    first = _repairs_path(tmp_path)
    second = tmp_path / "repairs-two.json"
    second.write_text('{"repairs": []}', encoding="utf-8")
    calls = []

    def fake_apply(staging, repairs, *, allow_unmatched):
        calls.append(Path(repairs))
        amount = len(calls)
        return OcrRepairResult(amount, amount, amount, 0, 0, 0, 0)

    monkeypatch.setattr(batch, "apply_audited_repairs", fake_apply)

    prepared = prepare_repair_batch(
        (RepairTarget("one", database),),
        (first, second),
        tmp_path / "work",
    )

    assert calls == [first, second]
    assert prepared[0].source_repair_result == OcrRepairResult(
        exact_records=3,
        applied_records=3,
        changed_source_pages=3,
        changed_stems=0,
        changed_question_formats=0,
        changed_question_images=0,
        changed_choice_sets=0,
    )


def test_prepare_batch_preserves_unconfirmed_line_breaks(tmp_path):
    database = tmp_path / "one.db"
    _create_valid_database(database, "1")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE questions SET question_text = ?",
            ("첫 줄\n둘째 줄",),
        )

    prepared = prepare_repair_batch(
        (RepairTarget("one", database),),
        _repairs_path(tmp_path),
        tmp_path / "work",
    )

    with sqlite3.connect(prepared[0].staging_path) as connection:
        stored = connection.execute(
            "SELECT question_text FROM questions"
        ).fetchone()[0]
    assert stored == "첫 줄\n둘째 줄"
    assert prepared[0].audit.changes == ()


def test_prepare_batch_limits_automatic_pass_to_confirmed_confusables(
    tmp_path,
    monkeypatch,
):
    database = tmp_path / "one.db"
    _create_valid_database(database, "1")
    calls = []
    real_collect_changes = batch.collect_changes

    def collect_changes_spy(
        connection,
        *,
        confusables_only=False,
        protected_question_ids=(),
    ):
        calls.append(confusables_only)
        return real_collect_changes(
            connection,
            confusables_only=confusables_only,
            protected_question_ids=protected_question_ids,
        )

    monkeypatch.setattr(batch, "collect_changes", collect_changes_spy)

    prepare_repair_batch(
        (RepairTarget("one", database),),
        _repairs_path(tmp_path),
        tmp_path / "work",
    )

    assert calls == [True]


def test_prepare_batch_does_not_rewrite_source_confirmed_text(tmp_path):
    database = tmp_path / "one.db"
    _create_valid_database(database, "1")
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT q.id, q.year, q.session, q.question_number,
                   e.code AS exam_code, s.code AS subject_code
            FROM questions q
            JOIN exam_subjects es ON es.id = q.exam_subject_id
            JOIN exams e ON e.id = es.exam_id
            JOIN subjects s ON s.id = es.subject_id
            """
        ).fetchone()
        connection.execute(
            "UPDATE questions SET question_text = 'HaIf source text'"
        )
    repairs = tmp_path / "source-repairs.json"
    repairs.write_text(json.dumps({
        "repairs": [{
            "exam_code": row["exam_code"],
            "subject_code": row["subject_code"],
            "year": row["year"],
            "session": row["session"],
            "question_number": row["question_number"],
            "source_page": 1,
            "source_pdf_relative_path": "source.pdf",
            "repaired_stem": "HaIf source text",
            "confidence": "exact_source",
        }]
    }, ensure_ascii=False), encoding="utf-8")

    prepared = prepare_repair_batch(
        (RepairTarget("one", database),),
        repairs,
        tmp_path / "work",
    )

    with sqlite3.connect(prepared[0].staging_path) as connection:
        stored = connection.execute(
            "SELECT question_text FROM questions"
        ).fetchone()[0]
    assert stored == "HaIf source text"
    assert prepared[0].audit.changes == ()
