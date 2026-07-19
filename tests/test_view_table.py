import json

from src.parser.view_table import (
    add_one_cell_table,
    has_misplaced_view_boundary,
    promote_view_block,
    remove_table_and_restore,
)


def _payload(encoded):
    return json.loads(encoded) if encoded else {}


def test_last_view_marker_becomes_one_cell_table():
    text, encoded, changed = promote_view_block(
        "다음 <보기>에서 옳은 것은? <보기> ① A ② B"
    )

    table = _payload(encoded)["tables"][0]
    assert changed is True
    assert text == "다음 <보기>에서 옳은 것은?"
    assert table["id"] == "view-table-1"
    assert table["rows"] == [["<보기>\n① A ② B"]]
    assert table["cells"][0]["text"] == "<보기>\n① A ② B"
    assert table["anchor"]["offset"] == len(text)
    assert table["source"]["kind"] == "view_block_text"
    assert table["render_mode"] == "native"


def test_single_fullwidth_view_marker_is_promoted():
    text, encoded, changed = promote_view_block(
        "질문? 〈 보 기 〉 ㄱ. A ㄴ. B"
    )

    assert changed is True
    assert text == "질문?"
    assert _payload(encoded)["tables"][0]["rows"] == [
        ["〈 보 기 〉\nㄱ. A ㄴ. B"]
    ]


def test_empty_view_marker_is_promoted_as_marker_only_table():
    text, encoded, changed = promote_view_block("질문? <보기>   ")

    assert changed is True
    assert text == "질문?"
    assert _payload(encoded)["tables"][0]["rows"] == [["<보기>"]]


def test_reference_marker_stays_in_stem_when_block_header_lost_closing_bracket():
    text, encoded, changed = promote_view_block(
        "다음 <보기> 중 법률상 해당하는 것을 모두 고른 것은9 "
        "< 보기 ㉠ 첫째 ㉡ 둘째"
    )

    table = _payload(encoded)["tables"][0]
    assert changed is True
    assert text == "다음 <보기> 중 법률상 해당하는 것을 모두 고른 것은?"
    assert table["rows"] == [["<보기>\n㉠ 첫째 ㉡ 둘째"]]
    assert table["confidence"]["reasons"] == ["recovered_broken_view_marker"]


def test_reference_marker_stays_in_stem_when_second_header_is_missing():
    text, encoded, changed = promote_view_block(
        "다음 <보기>에서 옳은 것을 고른 것은? ㉠ 첫째 ㉡ 둘째"
    )

    table = _payload(encoded)["tables"][0]
    assert changed is True
    assert text == "다음 <보기>에서 옳은 것을 고른 것은?"
    assert table["rows"] == [["<보기>\n㉠ 첫째 ㉡ 둘째"]]
    assert "recovered_view_reference_boundary" in table["confidence"]["reasons"]


def test_existing_misplaced_view_table_is_repaired_idempotently():
    misplaced = add_one_cell_table(
        "다음",
        None,
        "<보기>\n중 법률상 해당하는 것은? 보 기 > ㉠ 첫째 ㉡ 둘째",
        len("다음"),
        reason="explicit_view_marker",
    )
    assert has_misplaced_view_boundary("다음", misplaced) is True

    text, encoded, changed = promote_view_block("다음", misplaced)
    table = _payload(encoded)["tables"][0]

    assert changed is True
    assert text == "다음 <보기> 중 법률상 해당하는 것은?"
    assert table["rows"] == [["<보기>\n㉠ 첫째 ㉡ 둘째"]]
    assert table["anchor"]["offset"] == len(text)
    assert "recovered_view_reference_boundary" in table["confidence"]["reasons"]

    second_text, second_encoded, second_changed = promote_view_block(text, encoded)
    assert second_changed is False
    assert (second_text, second_encoded) == (text, encoded)
    assert has_misplaced_view_boundary(text, encoded) is False


def test_plain_prose_after_question_tail_stays_in_view_table():
    text, encoded, changed = promote_view_block(
        "다음 <보기>의 상황을 설명한 것은? "
        "When ship A approaches ship B from abaft her beam."
    )

    assert changed is True
    assert text == "다음 <보기>의 상황을 설명한 것은?"
    assert _payload(encoded)["tables"][0]["rows"] == [[
        "<보기>\nWhen ship A approaches ship B from abaft her beam."
    ]]


def test_prompt_proposition_reference_does_not_hide_later_view_header():
    text, encoded, changed = promote_view_block(
        "다음 <보기>의 ㉠부터 ㉣까지 빈칸의 합은? "
        "보 기 > The first statement. The second statement."
    )

    assert changed is True
    assert text == "다음 <보기>의 ㉠부터 ㉣까지 빈칸의 합은?"
    assert _payload(encoded)["tables"][0]["rows"] == [[
        "<보기>\nThe first statement. The second statement."
    ]]


def test_legitimate_view_body_starting_with_similar_word_is_not_rewritten():
    text, encoded, changed = promote_view_block("질문? <보기> 중량은 10톤이다.")
    second_text, second_encoded, second_changed = promote_view_block(text, encoded)

    assert changed is True
    assert second_changed is False
    assert second_text == text == "질문?"
    assert second_encoded == encoded


def test_promotion_preserves_spans_and_existing_tables():
    existing = json.dumps(
        {
            "schema_version": 2,
            "spans": [{"start": 0, "end": 2, "underline": True}],
            "tables": [
                {
                    "id": "table-1",
                    "rows": [["기존"]],
                    "anchor": {"offset": 0},
                    "render_mode": "native",
                }
            ],
            "future_field": {"keep": True},
        },
        ensure_ascii=False,
    )

    _, encoded, changed = promote_view_block("질문? <보기> ㄱ. A", existing)
    payload = _payload(encoded)

    assert changed is True
    assert payload["spans"][0]["underline"] is True
    assert payload["future_field"] == {"keep": True}
    assert [table["id"] for table in payload["tables"]] == [
        "table-1",
        "view-table-1",
    ]


def test_promotion_is_idempotent():
    first_text, first_json, first_changed = promote_view_block(
        "질문? <보기> ㄱ. A"
    )
    second_text, second_json, second_changed = promote_view_block(
        first_text,
        first_json,
    )

    assert first_changed is True
    assert second_changed is False
    assert (second_text, second_json) == (first_text, first_json)


def test_manual_one_cell_table_uses_unique_id_and_requested_anchor():
    first = add_one_cell_table("앞 뒤", None, "첫 표", 1)
    second = add_one_cell_table("앞 뒤", first, "둘째 표", 2)
    tables = _payload(second)["tables"]

    assert [table["id"] for table in tables] == [
        "view-table-1",
        "view-table-2",
    ]
    assert tables[1]["anchor"]["offset"] == 2
    assert tables[1]["confidence"]["reasons"] == ["manual_editor"]


def test_remove_restores_cell_at_anchor_without_losing_other_payload():
    text, encoded, _ = promote_view_block("질문? <보기> ① A")
    payload = _payload(encoded)
    payload["spans"] = [{"start": 0, "end": 2, "underline": True}]

    restored, encoded, removed = remove_table_and_restore(
        text,
        json.dumps(payload, ensure_ascii=False),
        "view-table-1",
    )

    assert removed is True
    assert restored == "질문?\n<보기>\n① A"
    assert not _payload(encoded).get("tables")
    assert _payload(encoded)["spans"][0]["underline"] is True


def test_remove_unknown_table_is_a_noop():
    text, encoded, _ = promote_view_block("질문? <보기> ① A")

    restored, after, removed = remove_table_and_restore(
        text,
        encoded,
        "missing-table",
    )

    assert removed is False
    assert restored == text
    assert after == encoded
