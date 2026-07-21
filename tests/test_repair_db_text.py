import json
import sqlite3

import pytest

from scripts.repair_db_text import has_unbalanced_delimiters, repair_text_and_format
from src.database.text_repair import (
    TextChange,
    apply_changes,
    collect_findings,
    collect_surface_counts,
)
from src.database.validator import QuestionValidator


@pytest.fixture()
def audit_connection(repo, sample_metadata, sample_question):
    sample_question.text = "발문 HaIf token"
    repo.save_questions([sample_question], sample_metadata)
    connection = sqlite3.connect(repo.db_path)
    connection.row_factory = sqlite3.Row
    question = connection.execute(
        "SELECT id, exam_subject_id FROM questions ORDER BY id LIMIT 1"
    ).fetchone()
    question_table = json.dumps({"tables": [{
        "rows": [["@ Beach row"]],
        "cells": [{"row": 0, "col": 0, "text": "@ Beach row"}],
    }]}, ensure_ascii=False)
    choice_table = json.dumps({"tables": [{
        "rows": [["Da•elict row"]],
        "cells": [{"row": 0, "col": 0, "text": "Da•elict row"}],
    }]}, ensure_ascii=False)
    group_id = connection.execute(
        """
        INSERT INTO question_groups (
            exam_subject_id, year, session, group_number, shared_text
        ) VALUES (?, 2024, 1, 1, ?)
        """,
        (question["exam_subject_id"], "공유 지문 f01그r token"),
    ).lastrowid
    connection.execute(
        """
        UPDATE questions
        SET question_format_json = ?, group_id = ?
        WHERE id = ?
        """,
        (question_table, group_id, question["id"]),
    )
    connection.execute(
        """
        UPDATE question_choices
        SET choice_text = '선지 설명으로 을지 않은 것은',
            choice_format_json = ?
        WHERE question_id = ? AND choice_number = 1
        """,
        (choice_table, question["id"]),
    )
    connection.commit()
    try:
        yield connection
    finally:
        connection.close()


def test_collect_findings_audits_all_rich_text_surfaces(audit_connection):
    findings = collect_findings(audit_connection)
    paths = {finding.field_path for finding in findings}

    assert "question_text" in paths
    assert "question_format_json.tables[0].rows[0][0]" in paths
    assert "question_format_json.tables[0].cells[0].text" in paths
    assert "choice_text" in paths
    assert "choice_format_json.tables[0].rows[0][0]" in paths
    assert "choice_format_json.tables[0].cells[0].text" in paths
    assert "shared_text" in paths

    counts = collect_surface_counts(audit_connection)
    assert counts == {
        "question_text": 1,
        "question_format_rows": 1,
        "question_format_cells": 1,
        "choice_text": 4,
        "choice_format_rows": 1,
        "choice_format_cells": 1,
        "shared_text": 1,
    }


def test_collect_findings_routes_unconfirmed_text_noise_to_source_review(
    audit_connection,
):
    findings = collect_findings(audit_connection)
    text_findings = [
        finding
        for finding in findings
        if finding.category in {
            "ocr_noise_text",
            "broken_unit_text",
            "unbalanced_paren_or_bracket",
            "damaged_list_marker",
        }
    ]

    assert text_findings
    assert {finding.severity for finding in text_findings} == {
        "needs_source_review"
    }


def test_collect_findings_keeps_rich_text_structure_errors_blocking(
    audit_connection,
):
    audit_connection.execute(
        "UPDATE questions SET question_format_json = '[1, 2]'"
    )
    audit_connection.commit()

    findings = collect_findings(audit_connection)
    structural = [
        finding
        for finding in findings
        if finding.category == "invalid_format_json"
    ]

    assert structural
    assert {finding.severity for finding in structural} == {
        "blocked_quality"
    }


def test_apply_changes_rejects_expected_value_mismatch(audit_connection):
    change = TextChange(
        table="question_groups",
        row_id=1,
        field="shared_text",
        before="다른 현재값",
        after="교정값",
        metadata={},
    )

    with pytest.raises(ValueError, match="expected current value mismatch"):
        apply_changes(audit_connection, [change])


def test_has_unbalanced_delimiters_ignores_fraction_parentheses():
    assert not has_unbalanced_delimiters("(1/2)배")
    assert not has_unbalanced_delimiters("축전지 전해액의 레벨은 (1/2)을 유지한다.")
    assert not has_unbalanced_delimiters("(P × N) / (1,852 × 60)")
    assert not has_unbalanced_delimiters(
        "배수량 6,560톤인 선박이 해수(비중: 1.025)에 떠있는 경우 수면 밑에 잠긴 선체의 용적은?"
    )
    assert not has_unbalanced_delimiters(
        "Pointed out (   ) by PSC officer as follows; 1) Annual survey not conducted for safety construction cert.2) The incinerator not working."
    )
    example = '"Ex.) In spite of the rough weather, we finished loading cargoes."'
    assert not has_unbalanced_delimiters(example)
    assert not QuestionValidator(None)._has_unbalanced_delimiters(example)


def test_has_unbalanced_delimiters_ignores_common_enumerator_labels():
    assert not has_unbalanced_delimiters("a) port side b) starboard side")
    assert not has_unbalanced_delimiters("i) first condition ii) second condition")
    assert not has_unbalanced_delimiters("K) Kelvin V) voltage")


def test_has_unbalanced_delimiters_detects_real_imbalance():
    assert has_unbalanced_delimiters("함수 f(t)의 라플라스 변환은? (단, s는 복소수이다.")
    assert has_unbalanced_delimiters("배수량 6,560톤인 선박이 해수(비중: 1.025에 떠있는 경우")
    assert has_unbalanced_delimiters("This token is broken) inside a sentence.")


def test_repair_text_and_format_can_limit_changes_to_ocr_confusables():
    repaired, format_json, skipped = repair_text_and_format(
        "CIearance가 작을때",
        None,
        confusables_only=True,
    )

    assert repaired == "Clearance가 작을때"
    assert format_json is None
    assert skipped is False

    untouched, untouched_format, skipped = repair_text_and_format(
        "상전압은 √3배이다.",
        None,
        confusables_only=True,
    )
    assert untouched == "상전압은 √3배이다."
    assert untouched_format is None
    assert skipped is False


def test_repair_text_and_format_regenerates_stale_format_json():
    repaired, format_json, skipped = repair_text_and_format(
        "¯π\\sqrt{2}",
        '{"spans": [{"start": 2, "end": 10, "latex": "\\\\sqrt{2}"}]}',
    )

    assert repaired == r"\sqrt{2}/π"
    assert not skipped
    assert json.loads(format_json)["spans"] == [{"start": 0, "end": 8, "latex": r"\sqrt{2}"}]


def test_repair_text_and_format_repairs_table_rows_and_cells_without_losing_layout():
    payload = {
        "schema_version": 2,
        "tables": [{
            "id": "view-table-1",
            "rows": [["ArticIe 33.\nThe coastal State may exerclse control."]],
            "cells": [{
                "row": 0,
                "col": 0,
                "text": "ArticIe 33.\nThe coastal State may exerclse control.",
                "row_span": 1,
                "col_span": 1,
            }],
            "layout": {"width_mode": "auto"},
        }],
    }

    repaired, format_json, skipped = repair_text_and_format(
        "다음 <보기>를 읽고 답하시오.",
        json.dumps(payload, ensure_ascii=False),
        confusables_only=True,
    )

    repaired_payload = json.loads(format_json)
    assert repaired == "다음 <보기>를 읽고 답하시오."
    assert repaired_payload["tables"][0]["rows"] == [[
        "Article 33.\nThe coastal State may exercise control."
    ]]
    assert repaired_payload["tables"][0]["cells"][0]["text"] == (
        "Article 33.\nThe coastal State may exercise control."
    )
    assert repaired_payload["tables"][0]["layout"] == {"width_mode": "auto"}
    assert skipped is False
