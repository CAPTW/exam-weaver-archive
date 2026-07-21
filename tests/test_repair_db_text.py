import json

from scripts.repair_db_text import has_unbalanced_delimiters, repair_text_and_format
from src.database.validator import QuestionValidator


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
