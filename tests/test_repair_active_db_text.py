import json
from pathlib import Path

import scripts.repair_active_db_text as cli
from src.database.repository import ExamRepository


def _create_cli_database(path: Path, label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    repository = ExamRepository(str(path))
    repository.init_database()
    template = repository.get_manual_question_template()
    template.update({
        "question_text": f"CLI 정상 발문 {label}",
        "correct_answer": 1,
        "choices": [
            {"choice_number": 1, "choice_symbol": "㉮", "choice_text": "A"},
            {"choice_number": 2, "choice_symbol": "㉯", "choice_text": "B"},
            {"choice_number": 3, "choice_symbol": "㉴", "choice_text": "C"},
            {"choice_number": 4, "choice_symbol": "㉵", "choice_text": "D"},
        ],
    })
    assert repository.create_manual_question(template) is not None


def _make_active_db_tree(tmp_path: Path) -> Path:
    paths = (
        Path("data/domain_dbs/exam_bank.maritime_all.db"),
        Path("data/domain_dbs/exam_bank.user_workspace.db"),
        Path("data/domain_dbs/exam_bank.Maritime.db"),
        Path("data/exam_bank.db"),
    )
    for index, relative in enumerate(paths, start=1):
        _create_cli_database(tmp_path / relative, str(index))
    return tmp_path


def _empty_repairs(tmp_path: Path) -> Path:
    repairs = tmp_path / "repairs.json"
    repairs.write_text('{"repairs": []}', encoding="utf-8")
    return repairs


def test_cli_is_dry_run_by_default_and_uses_exact_four_targets(
    tmp_path,
    monkeypatch,
):
    root = _make_active_db_tree(tmp_path)
    prepared_calls = []
    commit_calls = []
    first_repairs = _empty_repairs(tmp_path)
    second_repairs = tmp_path / "repairs-two.json"
    second_repairs.write_text('{"repairs": []}', encoding="utf-8")
    monkeypatch.setattr(
        cli,
        "prepare_repair_batch",
        lambda targets, repairs, work: (
            prepared_calls.append((tuple(targets), tuple(repairs))) or ()
        ),
    )
    monkeypatch.setattr(
        cli,
        "commit_repair_batch",
        lambda *args: commit_calls.append(args),
    )

    result = cli.main([
        "--root",
        str(root),
        "--repairs",
        str(first_repairs),
        "--repairs",
        str(second_repairs),
        "--output-dir",
        str(tmp_path / "report"),
    ])

    assert result == 0
    assert [target.name for target in prepared_calls[0][0]] == [
        "maritime_all",
        "user_workspace",
        "Maritime",
        "legacy_exam_bank",
    ]
    assert prepared_calls[0][1] == (first_repairs, second_repairs)
    assert commit_calls == []


def test_cli_apply_writes_machine_and_human_reports(tmp_path):
    root = _make_active_db_tree(tmp_path)
    output = tmp_path / "report"

    result = cli.main([
        "--root",
        str(root),
        "--repairs",
        str(_empty_repairs(tmp_path)),
        "--output-dir",
        str(output),
        "--apply",
    ])

    assert result == 0
    payload = json.loads(
        (output / "summary.json").read_text(encoding="utf-8")
    )
    assert payload["mode"] == "apply"
    assert payload["status"] == "applied"
    assert len(payload["databases"]) == 4
    assert all(
        database["surface_counts"]["choice_text"] == 4
        for database in payload["databases"]
    )
    assert (output / "summary.md").is_file()
    assert (output / "receipt.json").is_file()
