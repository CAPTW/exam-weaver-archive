import hashlib
import json

from src.parser.table_format import (
    AUTO_RENDER_THRESHOLD,
    effective_table_render_mode,
    merge_format_spans,
    normalize_table_spec,
    parse_format_payload,
    resolve_table_anchor,
    serialize_format_payload,
    validate_table_spec,
)


def test_legacy_rows_are_upgraded_without_data_loss():
    payload = parse_format_payload(
        '{"tables":[{"rows":[["구분","값"],["A","10"]]}]}'
    )

    table = payload["tables"][0]
    assert payload["schema_version"] == 2
    assert table["id"] == "table-1"
    assert table["rows"] == [["구분", "값"], ["A", "10"]]
    assert table["render_mode"] == "auto"
    assert table["recommended_render"] == "image"


def test_invalid_json_becomes_an_empty_versioned_payload():
    assert parse_format_payload("not-json") == {"schema_version": 2}
    assert serialize_format_payload({"schema_version": 2}) is None


def test_unknown_fields_survive_normalization_and_span_merge():
    existing = {
        "schema_version": 2,
        "custom": {"keep": True},
        "tables": [{"id": "source", "rows": [["A"]], "custom_table": 7}],
    }

    encoded = merge_format_spans(existing, [{"start": 0, "end": 1, "underline": True}])
    payload = json.loads(encoded)

    assert payload["custom"] == {"keep": True}
    assert payload["tables"][0]["custom_table"] == 7
    assert payload["spans"] == [{"start": 0, "end": 1, "underline": True}]


def test_empty_spans_do_not_delete_tables():
    encoded = merge_format_spans({"tables": [{"rows": [["A"]]}]}, [])
    payload = json.loads(encoded)

    assert "spans" not in payload
    assert payload["tables"][0]["rows"] == [["A"]]


def test_auto_render_mode_uses_threshold_and_complexity():
    table = normalize_table_spec(
        {"rows": [["A"]], "confidence": {"score": AUTO_RENDER_THRESHOLD}}
    )
    assert effective_table_render_mode(table, "auto") == "native"

    table["confidence"]["score"] = AUTO_RENDER_THRESHOLD - 0.01
    assert effective_table_render_mode(table, "auto") == "image"

    table["confidence"]["score"] = 1.0
    table["complexity"]["has_formula"] = True
    assert effective_table_render_mode(table, "auto") == "image"


def test_per_table_explicit_mode_overrides_document_mode():
    assert effective_table_render_mode({"render_mode": "native"}, "image") == "native"
    assert effective_table_render_mode({"render_mode": "image"}, "native") == "image"


def test_context_recovers_stale_anchor():
    text = "앞 문장이 늘어남 다음 표를 보고 옳은 것은"
    offset, recovered = resolve_table_anchor(
        text,
        {
            "offset": 1,
            "before_context": "다음 표를 보고",
            "after_context": "옳은 것은",
        },
    )

    assert recovered is True
    assert offset == text.index("옳은 것은")


def test_valid_anchor_offset_does_not_require_context_recovery():
    assert resolve_table_anchor("abcdef", {"offset": 3}) == (3, False)


def test_anchor_falls_back_to_text_end_when_context_is_missing():
    assert resolve_table_anchor("abcdef", {"offset": 99, "before_context": "x"}) == (
        6,
        True,
    )


def test_table_validation_reports_hash_bbox_cells_and_anchor(tmp_path):
    image_path = tmp_path / "table.png"
    image_path.write_bytes(b"table-image")
    table = normalize_table_spec(
        {
            "rows": [["A"]],
            "cells": [{"row": 1, "col": 0, "text": "bad", "row_span": 1, "col_span": 1}],
            "source": {
                "image_path": str(image_path),
                "sha256": hashlib.sha256(b"different").hexdigest(),
                "bbox": [-1, 0, 900, 100],
            },
            "anchor": {"offset": 99},
        }
    )

    errors = validate_table_spec(table, text="abc", page_size=(800, 600))

    assert "source_hash_mismatch" in errors
    assert "bbox_out_of_page" in errors
    assert "cell_out_of_bounds" in errors
    assert "anchor_unresolved" in errors


def test_low_confidence_table_requires_source_or_legacy_rows():
    table = normalize_table_spec(
        {
            "rows": [],
            "confidence": {"score": 0.2},
            "source": {"missing_reason": "crop_failed"},
        }
    )

    assert "low_confidence_without_source" in validate_table_spec(table)


def test_normalization_clamps_confidence_and_positive_cell_spans():
    table = normalize_table_spec(
        {
            "rows": [["A"]],
            "confidence": {"score": 4},
            "cells": [{"row": 0, "col": 0, "row_span": 0, "col_span": -2}],
        }
    )

    assert table["confidence"]["score"] == 1.0
    assert table["cells"][0]["row_span"] == 1
    assert table["cells"][0]["col_span"] == 1
