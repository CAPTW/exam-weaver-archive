import json

from scripts.repair_db_text import has_unbalanced_delimiters, repair_text_and_format


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


def test_has_unbalanced_delimiters_detects_real_imbalance():
    assert has_unbalanced_delimiters("함수 f(t)의 라플라스 변환은? (단, s는 복소수이다.")
    assert has_unbalanced_delimiters("배수량 6,560톤인 선박이 해수(비중: 1.025에 떠있는 경우")


def test_repair_text_and_format_regenerates_stale_format_json():
    repaired, format_json, skipped = repair_text_and_format(
        "¯π\\sqrt{2}",
        '{"spans": [{"start": 2, "end": 10, "latex": "\\\\sqrt{2}"}]}',
    )

    assert repaired == r"\sqrt{2}/π"
    assert not skipped
    assert json.loads(format_json)["spans"] == [{"start": 0, "end": 8, "latex": r"\sqrt{2}"}]
