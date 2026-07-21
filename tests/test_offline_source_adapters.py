from __future__ import annotations

import importlib
import inspect
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.parser.layout import LayoutLine, LayoutWord, StructuredPage


CORPUS_RELATIVE_PATHS = [
    "(공고)_2026년_해양경찰청_소속_공무원_연간채용계획_등_공고.pdf",
    "2023 2차 - 물리 정답 & 해설.pdf",
    "2023 2차 - 물리.pdf",
    "2023 2차 - 항해.pdf",
    "2023 2차 - 확정답안.pdf",
    "25년 하반기 해양경찰공무원 채용시험 공고.pdf",
    "해양경찰청 교육훈련담당관_25년 하반기 해양경찰공무원 채용시험 공고.pdf",
    "[론박]경찰직 기관학(25년 하반기 포함)/[기출문제]경찰직 기관술(학)(24-13년).pdf",
    "[론박]경찰직 기관학(25년 하반기 포함)/[기출문제]경찰직 기관학(24년 하반기-25년 하반기).pdf",
    "[론박]경찰직 기관학(25년 하반기 포함)/[기출정답]경찰직 기관술(학)(24-13년).pdf",
    "[론박]경찰직 기관학(25년 하반기 포함)/[기출정답]경찰직 기관학(24년 하반기-25년 상반기).pdf",
    "[론박]경찰직 기관학(25년 하반기 포함)/[기출정답]경찰직 기관학(25년 하반기).pdf",
    "[론박]경찰직 항해학(25년 하반기 포함)/[기출문제]경찰직 항해학(24년 하반기-25년 하반기).pdf",
    "[론박]경찰직 항해학(25년 하반기 포함)/[기출문제]경찰직 항해학(24년-13년).pdf",
    "[론박]경찰직 항해학(25년 하반기 포함)/[기출정답]경찰직 항해학(24년 하반기-25년 상반기).pdf",
    "[론박]경찰직 항해학(25년 하반기 포함)/[기출정답]경찰직 항해학(24년-13년).pdf",
    "[론박]경찰직 항해학(25년 하반기 포함)/[기출정답]경찰직 항해학(25년 하반기).pdf",
    "[론박]해사법규(26년 승진 포함)/[기출문제]해사법규(21년 경사-13년).pdf",
    "[론박]해사법규(26년 승진 포함)/[기출문제]해사법규(24년 하반기-25년 하반기).pdf",
    "[론박]해사법규(26년 승진 포함)/[기출문제]해사법규(24년-21년 경장).pdf",
    "[론박]해사법규(26년 승진 포함)/[기출문제]해사법규(26년 승진).pdf",
    "[론박]해사법규(26년 승진 포함)/정답안/[기출정답]해사법규(24년 하반기-25년 상반기).pdf",
    "[론박]해사법규(26년 승진 포함)/정답안/[기출정답]해사법규(24년-13년).pdf",
    "[론박]해사법규(26년 승진 포함)/정답안/[기출정답]해사법규(25년 하반기).pdf",
    "[론박]해사법규(26년 승진 포함)/정답안/[기출정답]해사법규(26년 승진).pdf",
    "[론박]해사영어(25년 하반기 포함)/[기출문제]해사영어(24년 하반기-25년 하반기).pdf",
    "[론박]해사영어(25년 하반기 포함)/[기출문제]해사영어(24년-13년).pdf",
    "[론박]해사영어(25년 하반기 포함)/[기출정답]해사영어(24년 하반기-25년 상반기).pdf",
    "[론박]해사영어(25년 하반기 포함)/[기출정답]해사영어(24년-13년).pdf",
    "[론박]해사영어(25년 하반기 포함)/[기출정답]해사영어(25년 하반기).pdf",
]


def _line(texts: list[str], y: float) -> LayoutLine:
    words = tuple(
        LayoutWord(text, (0.08 + index * 0.12, y, 0.16 + index * 0.12, y + 0.03), 0.99)
        for index, text in enumerate(texts)
    )
    return LayoutLine(words, (0.08, y, words[-1].bbox[2], y + 0.03), 1, 0)


def _page_with_question(choice_count: int = 4) -> StructuredPage:
    lines = [_line(["1.", "옳은", "것은?"], 0.10)]
    for index, marker in enumerate(("①", "②", "③", "④")[:choice_count], start=1):
        lines.append(_line([marker, f"선택지{index}"], 0.10 + index * 0.08))
    return StructuredPage(1, 1, 1, "scanned", tuple(lines), ())


def test_grouping_keeps_late_header_metadata_inside_a_continuing_exam():
    from scripts.analyze_maritime_english_pdfs import build_groups

    filename = "[기출문제]해사영어(24년-13년).pdf"
    records = [
        {
            "filename": filename,
            "pdf_id": "english-archive",
            "page": 1,
            "text": (
                "2018년 해사영어\n"
                "1. 다음 중 옳은 것을 고르시오. 충분한 문제 본문입니다.\n"
                "7. 다음 중 옳은 것을 고르시오. 충분한 문제 본문입니다.\n"
                "13. 다음 중 옳은 것을 고르시오. 충분한 문제 본문입니다."
            ),
            "source_path": filename,
        },
        {
            "filename": filename,
            "pdf_id": "english-archive",
            "page": 2,
            "text": (
                "2018년 제3차 해사영어\n"
                "14. 다음 중 옳은 것을 고르시오. 충분한 문제 본문입니다.\n"
                "20. 다음 중 옳은 것을 고르시오. 충분한 문제 본문입니다."
            ),
            "source_path": filename,
        },
    ]

    groups = build_groups(records)

    assert len(groups) == 1
    assert [page["page"] for page in groups[0]["pages"]] == [1, 2]


def test_engineering_registered_source_repairs_are_explicit_and_importable():
    from scripts.import_police_engineering_pdf import repair_registered_source_candidate
    from src.parser.offline_exam import ParsedOfflineQuestion
    from src.parser.offline_quality import validate_offline_question

    damaged = ParsedOfflineQuestion(
        18,
        "필터 도면기호는?",
        [],
        24,
        1.0,
        ("invalid_choice_count",),
    )
    repaired = repair_registered_source_candidate(
        damaged,
        Path("[기출문제]경찰직 기관술(학)(24-13년).pdf"),
    )

    assert len(repaired.choices) == 4
    assert "source_choice_repair" in repaired.diagnostics
    assert validate_offline_question(repaired).importable is True


def test_engineering_truncated_source_is_marked_unavailable_without_hallucination():
    from scripts.import_police_engineering_pdf import repair_registered_source_candidate
    from src.parser.offline_exam import ParsedOfflineQuestion
    from src.parser.offline_quality import validate_offline_question

    truncated = ParsedOfflineQuestion(
        11,
        "변압기의 1차 및 2차 전압",
        [],
        64,
        1.0,
        ("invalid_choice_count",),
    )
    repaired = repair_registered_source_candidate(
        truncated,
        Path("[기출문제]경찰직 기관술(학)(24-13년).pdf"),
    )

    assert repaired.choices == [
        "원본 PDF에서 잘린 선지 1",
        "원본 PDF에서 잘린 선지 2",
        "원본 PDF에서 잘린 선지 3",
        "원본 PDF에서 잘린 선지 4",
    ]
    assert "source_unavailable_choices" in repaired.diagnostics
    assert validate_offline_question(repaired).importable is True


def test_audited_source_repair_replaces_exact_stem_and_choices():
    from src.parser.offline_exam import ParsedOfflineQuestion
    from src.parser.offline_repairs import apply_audited_source_repair
    from src.parser.offline_quality import validate_offline_question

    damaged = ParsedOfflineQuestion(
        9,
        "깨진 발문",
        ["오염된 선지"],
        12,
        0.91,
        ("invalid_choice_count",),
    )
    repairs = {
        ("questions.pdf", 12, 9): {
            "repaired_stem": "원문에서 확인한 발문은?",
            "repaired_choices": ["선지 1", "선지 2", "선지 3", "선지 4"],
            "confidence": "exact_source",
        }
    }

    repaired = apply_audited_source_repair(
        damaged, Path("questions.pdf"), repairs=repairs
    )

    assert repaired.stem == "원문에서 확인한 발문은?"
    assert repaired.choices == ["선지 1", "선지 2", "선지 3", "선지 4"]
    assert "source_text_repair" in repaired.diagnostics
    assert validate_offline_question(repaired).importable is True


def test_exact_source_choices_can_preserve_intentional_slash_separated_values():
    from src.parser.offline_exam import ParsedOfflineQuestion
    from src.parser.offline_repairs import apply_audited_source_repair
    from src.parser.offline_quality import validate_offline_question

    candidate = ParsedOfflineQuestion(
        16,
        "선회권 값은?",
        ["깨진 선지"],
        28,
        0.95,
        ("invalid_choice_count",),
    )
    repairs = {
        ("navigation.pdf", 28, 16): {
            "repaired_stem": None,
            "repaired_choices": [
                "90 / 5 / 90 / 180 / 4.5",
                "90 / 4.5 / 180 / 90 / 5",
                "90 / 5 / 180 / 90 / 4.5",
                "90 / 4.5 / 90 / 180 / 5",
            ],
            "confidence": "exact_source",
        }
    }

    repaired = apply_audited_source_repair(
        candidate, Path("navigation.pdf"), repairs=repairs
    )

    assert validate_offline_question(repaired).importable is True


def test_bundled_audit_repairs_reported_engineering_screenshot_stem():
    from src.parser.offline_exam import ParsedOfflineQuestion
    from src.parser.offline_repairs import apply_audited_source_repair

    damaged = ParsedOfflineQuestion(
        9,
        "다음 중 내연기관 윤활유의 기능으로 가장 옳지\n0 V으 거 으7",
        ["산화작용", "냉각작용", "기밀작용", "방청작용"],
        12,
        0.91,
        (),
    )

    repaired = apply_audited_source_repair(
        damaged,
        Path("[기출문제]경찰직 기관학(24년 하반기-25년 하반기).pdf"),
    )

    assert repaired.stem == "다음 중 내연기관 윤활유의 기능으로 가장 옳지 않은 것은?"


def test_bundled_audit_repairs_reported_echo_sounder_stem_and_choices():
    from src.parser.offline_exam import ParsedOfflineQuestion
    from src.parser.offline_repairs import apply_audited_source_repair

    damaged = ParsedOfflineQuestion(
        38,
        "음향 측심기(Echo sounder)에 대한 설명으로 가장 옳은 것은?",
        ["파가 해저에서 되 도 근 }~= 0 느 시간을 측정한다.", "?으로 계산", "정상", "깨짐"],
        11,
        0.91,
        (),
    )

    repaired = apply_audited_source_repair(
        damaged,
        Path("[기출문제]경찰직 항해학(24년 하반기-25년 하반기).pdf"),
    )

    assert repaired.stem == "음향 측심기(Echo sounder)에 대한 설명으로 가장 옳은 것은?"
    assert repaired.choices == [
        "음향 측심기는 지속파의 초음파를 해저로 발사한 후, 발사한 초음파가 해저에서 되돌아오는 시간을 측정하여 수심을 측정한다.",
        "수심의 측정은 음파의 속도와 해저에 반사되어 돌아오는 시간의 곱으로 계산되므로, 수신시간이 0.1초였다면 수심은 약 150m가 된다.",
        "음향 측심기는 측심 범위에 따라 사용 주파수가 달라진다.",
        "해수에서 수심, 온도, 염도 등에 따른 음파 속도의 변화는 거의 없기 때문에 1,500m/s를 사용한다.",
    ]


def test_bundled_audit_repairs_law_question_with_merged_leading_choices():
    from src.parser.offline_exam import ParsedOfflineQuestion
    from src.parser.offline_quality import validate_offline_question
    from src.parser.offline_repairs import apply_audited_source_repair

    damaged = ParsedOfflineQuestion(
        5,
        "다음 중 수상레저 운항규칙은? ① OCR 잡음",
        ["합쳐진 선지 3", "합쳐진 선지 4"],
        2,
        0.91,
        ("invalid_choice_sequence", "invalid_choice_count"),
    )

    repaired = apply_audited_source_repair(
        damaged,
        Path("[기출문제]해사법규(21년 경사-13년).pdf"),
    )

    assert repaired.stem.endswith("가장 옳지 않은 것은?")
    assert len(repaired.choices) == 4
    assert repaired.choices[0].startswith("다이빙대·계류장")
    assert repaired.choices[3].endswith("진로를 피하여야 한다.")
    assert validate_offline_question(repaired).importable is True


def test_exact_source_repair_marks_confidence_as_source_verified():
    from src.parser.offline_exam import ParsedOfflineQuestion
    from src.parser.offline_repairs import apply_audited_source_repair
    from src.parser.offline_quality import validate_offline_question

    candidate = ParsedOfflineQuestion(
        19,
        "깨진 발문",
        ["가", "나", "다", "라"],
        5,
        0.4,
        (),
    )
    repaired = apply_audited_source_repair(
        candidate,
        Path("english.pdf"),
        repairs={
            ("english.pdf", 5, 19): {
                "confidence": "exact_source",
                "repaired_stem": "원문에서 확인한 정상 발문은?",
                "repaired_choices": ["하나", "둘", "셋", "넷"],
            }
        },
    )

    assert repaired.confidence == 1.0
    assert validate_offline_question(repaired).importable is True


def test_unapplicable_exact_choice_override_stays_rejectable_for_baseline_recovery():
    from src.parser.offline_exam import ParsedOfflineQuestion
    from src.parser.offline_repairs import apply_audited_source_repair

    candidate = ParsedOfflineQuestion(
        17,
        "발문",
        ["한 선지만 인식됨"],
        67,
        0.8,
        ("invalid_choice_count",),
    )
    repaired = apply_audited_source_repair(
        candidate,
        Path("english.pdf"),
        repairs={
            ("english.pdf", 67, 17): {
                "confidence": "exact_source",
                "repaired_choice_overrides": {"2": "원문 둘째 선지"},
            }
        },
    )

    assert "audited_choice_override_unapplied" in repaired.diagnostics


def test_exact_source_repair_carries_verified_question_image_path():
    from src.parser.offline_exam import ParsedOfflineQuestion
    from src.parser.offline_repairs import apply_audited_source_repair

    candidate = ParsedOfflineQuestion(
        3,
        "그림을 보고 답하시오.",
        ["가", "나", "다", "라"],
        1,
        0.9,
        (),
    )
    repaired = apply_audited_source_repair(
        candidate,
        Path("physics.pdf"),
        repairs={
            ("physics.pdf", 1, 3): {
                "confidence": "exact_source",
                "repaired_question_image_path": "data/question_images/physics_q3.png",
            }
        },
    )

    assert repaired.image_path == "data/question_images/physics_q3.png"
    assert repaired.confidence == 1.0


def test_exact_source_repair_carries_verified_question_spans():
    import json

    from src.parser.offline_exam import ParsedOfflineQuestion
    from src.parser.offline_repairs import apply_audited_source_repair

    candidate = ParsedOfflineQuestion(
        18,
        "깨진 본문",
        ["가", "나", "다", "라"],
        20,
        0.4,
        (),
    )
    repaired = apply_audited_source_repair(
        candidate,
        Path("english.pdf"),
        repairs={
            ("english.pdf", 20, 18): {
                "confidence": "exact_source",
                "repaired_stem": "This and This",
                "repaired_question_spans": [
                    {"start": 0, "end": 4, "underline": True},
                    {"start": 9, "end": 13, "underline": True},
                ],
            }
        },
    )

    assert json.loads(repaired.question_format_json)["spans"] == [
        {"start": 0, "end": 4, "underline": True},
        {"start": 9, "end": 13, "underline": True},
    ]


def test_bundled_audit_repairs_residual_ohm_unit_corruption():
    from src.parser.offline_exam import ParsedOfflineQuestion
    from src.parser.offline_repairs import apply_audited_source_repair
    from src.parser.text_quality import text_quality_issue_codes

    damaged = ParsedOfflineQuestion(
        18,
        "2 [이, 3 [이, 6 [이의 저항을 병렬로 연결했을 때 합성저항 값은 얼마인가?",
        ["5 [Q]", "3 [0]", "2[Q]", "11[Q]"],
        10,
        0.91,
        (),
    )

    repaired = apply_audited_source_repair(
        damaged,
        Path("[기출문제]경찰직 기관술(학)(24-13년).pdf"),
    )

    assert repaired.stem == "2[Ω], 3[Ω], 6[Ω]의 저항을 병렬로 연결했을 때 합성저항 값은 얼마인가?"
    assert repaired.choices == ["5[Ω]", "3[Ω]", "2[Ω]", "1[Ω]"]
    assert text_quality_issue_codes(repaired.stem) == ()
    assert all(text_quality_issue_codes(choice) == () for choice in repaired.choices)


def test_bundled_audit_repairs_structurally_broken_english_table_choices():
    from src.parser.offline_exam import ParsedOfflineQuestion
    from src.parser.offline_repairs import apply_audited_source_repair
    from src.parser.offline_quality import validate_offline_question

    damaged = ParsedOfflineQuestion(
        9,
        "깨진 SMCP 발문",
        ["Windward", "Backing", "Variable"],
        16,
        0.91,
        ("invalid_choice_count",),
    )

    repaired = apply_audited_source_repair(
        damaged,
        Path("[기출문제]해사영어(24년 하반기-25년 하반기).pdf"),
    )

    assert len(repaired.choices) == 4
    assert repaired.choices[0].startswith("㉠ Windward ㉡ Veering")
    assert validate_offline_question(repaired).importable is True


def test_bundled_logic_choice_repair_preserves_source_overline_as_latex():
    import json

    from src.parser.offline_exam import ParsedOfflineQuestion
    from src.parser.offline_repairs import apply_audited_source_repair

    damaged = ParsedOfflineQuestion(
        10,
        "다음의 진리표와 같이 출력하는 논리 함수는?",
        ["X=A·B", "X=A+B", "X=¬(A·B)", "X=A⊕B"],
        42,
        0.91,
        (),
    )

    repaired = apply_audited_source_repair(
        damaged,
        Path("[기출문제]경찰직 기관술(학)(24-13년).pdf"),
    )

    assert repaired.choices[2] == r"X=\overline{A \cdot B}"
    payload = json.loads(repaired.choice_format_jsons[2])
    assert payload["spans"] == [{
        "start": 2,
        "end": len(repaired.choices[2]),
        "latex": r"\overline{A \cdot B}",
    }]


def test_audited_source_repair_can_replace_only_confirmed_choices():
    from src.parser.offline_exam import ParsedOfflineQuestion
    from src.parser.offline_repairs import apply_audited_source_repair

    damaged = ParsedOfflineQuestion(
        9,
        "정상 발문",
        ["정상 1", "깨진 2", "정상 3", "깨진 4"],
        12,
        0.91,
        (),
    )
    repairs = {
        ("questions.pdf", 12, 9): {
            "repaired_choice_overrides": {"2": "원문 2", "4": "원문 4"},
            "confidence": "exact_source",
        }
    }

    repaired = apply_audited_source_repair(
        damaged, Path("questions.pdf"), repairs=repairs
    )

    assert repaired.stem == "정상 발문"
    assert repaired.choices == ["정상 1", "원문 2", "정상 3", "원문 4"]
    assert "source_text_repair" in repaired.diagnostics


def test_bundled_audit_repairs_recent_english_colregs_ocr_noise():
    from src.parser.offline_exam import ParsedOfflineQuestion
    from src.parser.offline_repairs import apply_audited_source_repair
    from src.parser.text_quality import text_quality_issue_codes

    damaged = ParsedOfflineQuestion(
        13,
        "다음 중 COLREGs상 C011isions 유지선의 동작은?",
        ["Where 011e Of two vessels", "S0011 as", "gwe-way", "CC)Llrse"],
        3,
        0.91,
        (),
    )

    repaired = apply_audited_source_repair(
        damaged,
        Path("[기출문제]해사영어(24년 하반기-25년 하반기).pdf"),
    )

    assert "Collisions at Sea" in repaired.stem
    assert repaired.choices[0].startswith("Where one of two vessels")
    assert repaired.choices[2].startswith("When, from any cause")
    assert all(text_quality_issue_codes(choice) == () for choice in repaired.choices)


def test_bundled_audit_repairs_recent_english_choice_order_from_source_table():
    from src.parser.offline_exam import ParsedOfflineQuestion
    from src.parser.offline_repairs import apply_audited_source_repair

    damaged = ParsedOfflineQuestion(
        2,
        "깨진 COLREG 정의 발문",
        [
            "vessel restricted in her ability to manoeuvre",
            "vessel not under command",
            "vessel constrained by her draught",
            "vessel engaged in fishing",
        ],
        2,
        0.91,
        (),
    )

    repaired = apply_audited_source_repair(
        damaged,
        Path("[기출문제]해사영어(24년-13년).pdf"),
    )

    assert repaired.choices == [
        "vessel engaged in fishing",
        "vessel restricted in her ability to manoeuvre",
        "vessel not under command",
        "vessel constrained by her draught",
    ]


def test_bundled_audit_repairs_recent_navigation_table_into_four_choices():
    from src.parser.offline_exam import ParsedOfflineQuestion
    from src.parser.offline_repairs import apply_audited_source_repair

    damaged = ParsedOfflineQuestion(
        8,
        "GM 선폭 표가 발문과 합쳐짐",
        ["2", "15", "1", "14"],
        13,
        0.91,
        (),
    )

    repaired = apply_audited_source_repair(
        damaged,
        Path("[기출문제]경찰직 항해학(24년 하반기-25년 하반기).pdf"),
    )

    assert repaired.choices == [
        "GM 2m / 선폭 14m",
        "GM 1m / 선폭 15m",
        "GM 2m / 선폭 15m",
        "GM 1m / 선폭 14m",
    ]


def test_registered_group_applies_audited_repair_before_quality_gate(monkeypatch):
    from dataclasses import replace

    from src.parser import offline_sources as sources

    page = _page_with_question(choice_count=1)
    parsed = sources.OfflineParseResult(
        Path("questions.pdf"),
        sources.DocumentRole.QUESTION,
        {},
        (),
        (),
        (page,),
    )

    def exact_repair(candidate, source_path):
        assert source_path == Path("questions.pdf")
        return replace(
            candidate,
            choices=["선지 1", "선지 2", "선지 3", "선지 4"],
            diagnostics=("source_text_repair",),
        )

    monkeypatch.setattr(
        sources, "apply_audited_source_repair", exact_repair, raising=False
    )
    group = {"pages": [{"page": 1, "source_path": "questions.pdf"}]}

    selected, rejected_count = sources.select_group_questions(
        group, lambda path, metadata: parsed, {}
    )

    assert selected[1].choices == ["선지 1", "선지 2", "선지 3", "선지 4"]
    assert rejected_count == 0


def test_registered_group_ignores_out_of_range_footer_candidate(monkeypatch):
    from src.parser import offline_sources as sources
    from src.parser.offline_exam import ParsedOfflineQuestion

    valid = ParsedOfflineQuestion(
        1, "정상 문제는?", ["가", "나", "다", "라"], 1, 0.99, ()
    )
    footer = ParsedOfflineQuestion(
        21,
        "하단 광고를 잘못 읽은 내용",
        [],
        1,
        0.0,
        ("invalid_choice_count", "ambiguous_bottom_margin"),
    )

    class FakeParser:
        def parse_pages(self, pages):
            return [valid, footer]

    monkeypatch.setattr(sources, "OfflineExamParser", FakeParser)
    parsed = sources.OfflineParseResult(
        Path("questions.pdf"),
        sources.DocumentRole.QUESTION,
        {},
        (),
        (),
        (StructuredPage(1, 1, 1, "scanned", (), ()),),
    )
    group = {
        "question_count": 20,
        "pages": [{"page": 1, "source_path": "questions.pdf"}],
    }

    selected, rejected_count = sources.select_group_questions(
        group, lambda path, metadata: parsed, {}
    )

    assert selected == {1: valid}
    assert rejected_count == 0


def test_classifies_exact_corpus_as_12_questions_15_answers_and_3_notices():
    from src.parser.offline_sources import DocumentRole, classify_offline_document

    roles = Counter(
        classify_offline_document(Path(relative), probe=None)
        for relative in CORPUS_RELATIVE_PATHS
    )

    assert roles == {
        DocumentRole.QUESTION: 12,
        DocumentRole.ANSWER: 15,
        DocumentRole.NOTICE: 3,
    }


def test_probe_classifies_ambiguous_question_answer_and_notice_documents():
    from src.parser.offline_sources import DocumentRole, classify_offline_document

    assert classify_offline_document(
        Path("ambiguous.pdf"),
        {"question_marker_count": 20, "choice_marker_count": 80},
    ) is DocumentRole.QUESTION
    assert classify_offline_document(
        Path("ambiguous.pdf"), {"text": "정답 및 해설", "answer_marker_count": 20}
    ) is DocumentRole.ANSWER
    assert classify_offline_document(
        Path("ambiguous.pdf"), {"text": "2026년도 채용시험 시행 공고"}
    ) is DocumentRole.NOTICE


def test_public_importer_question_role_probe_accepts_material_filename():
    from src.parser.offline_sources import DocumentRole, classify_offline_document

    assert classify_offline_document(
        Path("2025_해경_항해학_자료_100.pdf"), {"role": "자료"}
    ) is DocumentRole.QUESTION


def test_notices_never_invoke_extraction_or_create_question_candidates(monkeypatch):
    import src.parser.offline_sources as sources

    class FailExtractor:
        def __init__(self, *args, **kwargs):
            raise AssertionError("notices must be filtered before extraction")

    monkeypatch.setattr(sources, "PDFExtractor", FailExtractor)

    result = sources.parse_offline_question_pdf(
        Path("25년 하반기 해양경찰공무원 채용시험 공고.pdf"),
        {"subject_name": "항해학"},
    )

    assert result.role is sources.DocumentRole.NOTICE
    assert result.questions == ()
    assert result.rejected == ()


def test_shared_adapter_returns_only_quality_checked_common_parser_questions(monkeypatch):
    import src.parser.offline_sources as sources

    class FakeExtractor:
        def __init__(self, *args, **kwargs):
            pass

        def extract(self, path):
            return SimpleNamespace(
                pages=[SimpleNamespace(structured_page=_page_with_question())]
            )

    monkeypatch.setattr(sources, "PDFExtractor", FakeExtractor)

    result = sources.parse_offline_question_pdf(
        Path("[기출문제]항해학.pdf"), {"subject_name": "항해학"}
    )

    assert [question.choices for question in result.questions] == [
        ["선택지1", "선택지2", "선택지3", "선택지4"]
    ]
    assert result.rejected == ()
    assert result.metadata["subject_name"] == "항해학"


def test_shared_adapter_rejects_incomplete_candidates_without_generic_choice_synthesis(monkeypatch):
    import src.parser.offline_sources as sources

    class FakeExtractor:
        def __init__(self, *args, **kwargs):
            pass

        def extract(self, path):
            return SimpleNamespace(
                pages=[SimpleNamespace(structured_page=_page_with_question(choice_count=3))]
            )

    monkeypatch.setattr(sources, "PDFExtractor", FakeExtractor)

    result = sources.parse_offline_question_pdf(Path("[기출문제]기관학.pdf"), {})

    assert result.questions == ()
    assert len(result.rejected) == 1
    assert "invalid_choice_count" in result.rejected[0].reason_codes
    assert "원문 보기 참조" not in repr(result)


def test_group_selector_fails_closed_and_reuses_cache_without_registered_structured_page():
    from src.parser.offline_exam import ParsedOfflineQuestion
    from src.parser.offline_sources import (
        DocumentRole,
        OfflineParseResult,
        OfflineSetValidationError,
        RejectedOfflineQuestion,
        select_group_questions,
    )

    page_one = ParsedOfflineQuestion(1, "old", ["a", "b", "c", "d"], 1, 0.9, ())
    page_two = ParsedOfflineQuestion(1, "selected", ["a", "b", "c", "d"], 2, 0.9, ())
    rejected = RejectedOfflineQuestion(
        ParsedOfflineQuestion(2, "bad", ["a"], 2, 0.4, ("invalid_choice_count",)),
        ("invalid_choice_count",),
    )
    result = OfflineParseResult(
        Path("questions.pdf"),
        DocumentRole.QUESTION,
        {},
        (page_one, page_two),
        (rejected,),
    )
    calls = []

    def parse_source(path, metadata):
        calls.append((path, metadata))
        return result

    group = {"pages": [{"page": 2, "source_path": "questions.pdf"}]}
    cache = {}

    with pytest.raises(OfflineSetValidationError, match="structured_scope_incomplete"):
        select_group_questions(group, parse_source, cache)
    with pytest.raises(OfflineSetValidationError, match="structured_scope_incomplete"):
        select_group_questions(group, parse_source, cache)

    assert calls == [(Path("questions.pdf"), None)]


def test_registered_group_never_accepts_polluted_full_document_fallback():
    from src.parser.offline_exam import ParsedOfflineQuestion
    from src.parser.offline_sources import (
        DocumentRole,
        OfflineParseResult,
        OfflineSetValidationError,
        select_group_questions,
    )

    polluted = ParsedOfflineQuestion(
        40,
        "Q40 법률 문제\n다음 페이지 모두 몇 개인가?",
        ["법률 선택지1", "법률 선택지2", "법률 선택지3", "법률 선택지4"],
        7,
        0.99,
        (),
    )
    result = OfflineParseResult(
        Path("questions.pdf"),
        DocumentRole.QUESTION,
        {},
        (polluted,),
        (),
    )
    group = {"pages": [{"page": 7, "source_path": "questions.pdf"}]}

    with pytest.raises(OfflineSetValidationError, match="structured_scope_incomplete"):
        select_group_questions(group, lambda path, metadata: result, {})


@pytest.mark.parametrize(
    ("questions", "answers", "rejected_count", "reason"),
    [
        ({1: object()}, [1, 2], 0, "missing_questions"),
        ({1: object(), 2: object()}, [1, 2], 1, "rejected_questions"),
        ({1: object(), 2: object()}, [1, 0], 0, "invalid_answers"),
        ({1: object(), 2: object()}, [1, 5], 0, "invalid_answers"),
    ],
)
def test_complete_set_gate_rejects_partial_rejected_or_invalid_answer_sets(
    questions, answers, rejected_count, reason
):
    from src.parser.offline_sources import OfflineSetValidationError, require_complete_offline_set

    with pytest.raises(OfflineSetValidationError, match=reason):
        require_complete_offline_set(
            questions,
            expected_numbers=[1, 2],
            answers=answers,
            rejected_count=rejected_count,
            choice_counts={1: 4, 2: 4},
        )


def test_persistence_gate_rejects_zero_answer_question():
    from src.parser.offline_sources import OfflineSetValidationError, require_persistable_offline_questions
    from src.parser.question import Choice, Question

    question = Question(
        number=1,
        text="본문",
        choices=[Choice(number, str(number), str(number)) for number in range(1, 5)],
        correct_answer=0,
    )

    with pytest.raises(OfflineSetValidationError, match="invalid_answers"):
        require_persistable_offline_questions([SimpleNamespace(question=question)])


def test_complete_set_gate_accepts_explicit_official_unavailable_answer():
    from src.parser.offline_sources import require_complete_offline_set

    require_complete_offline_set(
        {1: object(), 2: object()},
        expected_numbers=[1, 2],
        answers=[3, 0],
        rejected_count=0,
        choice_counts={1: 4, 2: 4},
        unavailable_answer_numbers={2},
    )


def test_persistence_gate_accepts_explicit_official_unavailable_answer():
    from src.parser.offline_sources import require_persistable_offline_questions
    from src.parser.question import Choice, Question

    question = Question(
        number=5,
        text="본문",
        choices=[Choice(number, str(number), str(number)) for number in range(1, 5)],
        correct_answer=0,
        answer_available=False,
    )

    require_persistable_offline_questions([SimpleNamespace(question=question)])


def test_complete_and_persistence_gates_accept_explicit_all_choices_answer():
    from src.parser.offline_sources import (
        require_complete_offline_set,
        require_persistable_offline_questions,
    )
    from src.parser.question import Choice, Question

    require_complete_offline_set(
        {1: object()},
        expected_numbers=[1],
        answers=[-1],
        rejected_count=0,
        choice_counts={1: 4},
    )
    question = Question(
        number=1,
        text="본문",
        choices=[Choice(number, str(number), str(number)) for number in range(1, 5)],
        correct_answer=-1,
    )

    require_persistable_offline_questions([SimpleNamespace(question=question)])


def test_maritime_english_builder_preserves_official_unavailable_answer(
    monkeypatch, tmp_path
):
    import scripts.import_maritime_english_pdf as provider
    from src.parser.offline_exam import ParsedOfflineQuestion

    groups = [
        {
            "year": 2025 - (index // 2),
            "period": "fixture",
            "category": "fixture",
            "pdf_id": f"fixture-{index:03d}",
            "filename": f"fixture-{index:03d}.pdf",
            "pages": [{"page": index, "source_path": f"fixture-{index:03d}.pdf"}],
        }
        for index in range(1, 31)
    ]
    answer_map = {index: [1] * 20 for index in range(1, 31)}
    answer_map[29][4] = 0
    questions = {
        number: ParsedOfflineQuestion(
            number,
            f"문제 {number}",
            [f"선지 {choice}" for choice in range(1, 5)],
            1,
            0.99,
            (),
        )
        for number in range(1, 21)
    }

    monkeypatch.setattr(provider, "build_groups", lambda records: groups)
    monkeypatch.setattr(provider, "build_answer_map", lambda input_dir: answer_map)
    monkeypatch.setattr(provider, "read_analysis_rows", lambda output_dir: {})
    monkeypatch.setattr(provider, "group_label", lambda group, index: f"G{index:03d}")
    monkeypatch.setattr(
        provider,
        "select_group_questions",
        lambda group, parse_source, cache: (questions, 0),
    )

    parsed, summary = provider.build_questions([{}], tmp_path, tmp_path)

    target = next(
        item for item in parsed if item.group_index == 29 and item.question.number == 5
    )
    assert target.question.correct_answer == 0
    assert target.question.answer_available is False
    assert "answer_missing_in_source" in target.parser_tags
    assert summary["answer_missing_in_source"] == 1


@pytest.mark.parametrize(
    "module_name",
    [
        "scripts.import_maritime_law_pdf",
        "scripts.import_maritime_english_pdf",
        "scripts.import_police_navigation_pdf",
        "scripts.import_police_engineering_pdf",
    ],
)
def test_every_subject_builder_applies_complete_set_gate(module_name):
    module = importlib.import_module(module_name)
    source = inspect.getsource(module.build_questions)

    assert "require_complete_offline_set" in source
    assert source.count("format_json=") >= 2
    assert "require_persistable_offline_questions" in inspect.getsource(module.import_into_db)


@pytest.mark.parametrize(
    ("module_name", "subject_name", "exam_type"),
    [
        ("scripts.import_maritime_law_pdf", "해사법규", "해양경찰 해사법규"),
        ("scripts.import_maritime_english_pdf", "해사영어", "해양경찰 해사영어"),
        ("scripts.import_police_navigation_pdf", "항해학", "해양경찰 경찰직 항해학"),
        ("scripts.import_police_engineering_pdf", "기관학", "해양경찰 경찰직 기관학"),
    ],
)
def test_subject_adapters_delegate_to_shared_parser_without_placeholders(
    monkeypatch, module_name, subject_name, exam_type
):
    module = importlib.import_module(module_name)
    sentinel = object()
    calls = []

    def fake_parse(path, metadata):
        calls.append((path, metadata))
        return sentinel

    monkeypatch.setattr(module, "parse_offline_question_pdf", fake_parse)

    result = module.parse_subject_question_pdf(Path("questions.pdf"), {"year": 2025})

    assert result is sentinel
    assert calls == [
        (
            Path("questions.pdf"),
            {"subject_name": subject_name, "exam_type": exam_type, "year": 2025},
        )
    ]
    assert "원문 보기 참조" not in inspect.getsource(module)


def test_maritime_provider_reparses_registered_group_pages_with_hard_end_boundary(monkeypatch, tmp_path):
    import scripts.import_maritime_law_pdf as provider
    from src.parser.offline_exam import OfflineExamParser, ParsedOfflineQuestion
    from src.parser.offline_sources import (
        DocumentRole,
        OfflineParseResult,
        RejectedOfflineQuestion,
    )

    def layout_line(texts, y, page_number):
        words = tuple(
            LayoutWord(text, (0.06 + index * 0.12, y, 0.15 + index * 0.12, y + 0.012), 0.99)
            for index, text in enumerate(texts)
        )
        return LayoutLine(words, (words[0].bbox[0], y, words[-1].bbox[2], y + 0.012), page_number, 0)

    expected_q40_choices = [
        "해양경찰청이 단독 소관 하는 법률은 모두 다이다.",
        "유선 및 도선 사업법은 해양수산부 소관 법률이다.",
        "선박교통관제법은 제정되었으나 시행되지 않고 있다.",
        "내수면과 해수면은 모두 해양경찰 관할이다.",
    ]
    pages = []
    question_number = 1
    for page_number, count in zip(range(2, 8), (7, 7, 7, 7, 6, 6)):
        lines = []
        for slot in range(count):
            y = 0.08 + slot * 0.115
            lines.append(layout_line([f"{question_number}.", f"문제 {question_number}"], y, page_number))
            choices = (
                expected_q40_choices
                if question_number == 40
                else [f"{question_number}번 선택지 {index}" for index in range(1, 5)]
            )
            for offset, (marker, choice) in enumerate(zip(("①", "②", "③", "④"), choices), start=1):
                lines.append(layout_line([marker, choice], y + offset * 0.018, page_number))
            question_number += 1
        pages.append(StructuredPage(page_number, 1, 1, "scanned", tuple(lines), ()))

    scoped_questions = OfflineExamParser().parse_pages(pages)
    assert [question.number for question in scoped_questions] == list(range(1, 41))
    polluted_q40 = ParsedOfflineQuestion(
        40,
        scoped_questions[-1].stem + "\n모두 몇 개인가?\n<보기>\n3개 4개 5개 6개",
        [],
        7,
        0.99,
        ("invalid_choice_count",),
    )
    source_path = "questions.pdf"
    full_result = OfflineParseResult(
        Path(source_path),
        DocumentRole.QUESTION,
        {},
        tuple(scoped_questions[:-1]),
        (RejectedOfflineQuestion(polluted_q40, ("invalid_choice_count", "parser_diagnostic")),),
        tuple(pages),
    )
    group = {
        "answer_key": "2021|승진|경사",
        "question_count": 40,
        "year": 2021,
        "period": "승진",
        "session": "경사",
        "category": "경사",
        "pdf_id": "fixture",
        "filename": source_path,
        "pages": [
            {"page": page_number, "source_path": source_path}
            for page_number in range(2, 8)
        ],
    }

    monkeypatch.setattr(provider, "KNOWN_GROUPS", {"fixture": [object()]})
    monkeypatch.setattr(provider, "build_groups", lambda records: [group])
    monkeypatch.setattr(provider, "build_answer_map", lambda input_dir: {group["answer_key"]: [1] * 40})
    monkeypatch.setattr(provider, "read_analysis_rows", lambda output_dir: {})
    monkeypatch.setattr(provider, "parse_subject_question_pdf", lambda path, metadata=None: full_result)

    parsed, summary = provider.build_questions([{}], tmp_path, tmp_path)
    q40 = next(item.question for item in parsed if item.question.number == 40)

    assert len(parsed) == 40
    assert summary["choice_split_review"] == 0
    assert [choice.text for choice in q40.choices] == expected_q40_choices
    assert "모두 몇 개인가?" not in q40.text


def test_public_importer_ocr_required_adapter_uses_shared_parser(monkeypatch):
    import scripts.import_public_exam_pdf_folder as public_importer
    from src.parser.offline_exam import ParsedOfflineQuestion
    from src.parser.offline_sources import DocumentRole, OfflineParseResult

    calls = []

    def fake_parse(path, metadata):
        calls.append((path, metadata))
        question = ParsedOfflineQuestion(1, "본문", ["가", "나", "다", "라"], 2, 0.99, ())
        return OfflineParseResult(path, DocumentRole.QUESTION, metadata, (question,), ())

    monkeypatch.setattr(public_importer, "parse_offline_question_pdf", fake_parse)
    meta = public_importer.PdfMeta(
        path=Path("scanned.pdf"),
        relative_path="scanned.pdf",
        role="문제",
        exam_type="해경",
        subject_name="항해학",
        year=2025,
        session=1,
        document_id="doc",
        top_category="해경",
    )

    parsed, answer_key = public_importer.build_ocr_required_exam(
        Path("scanned.pdf"), meta, None, "file:///scanned.pdf"
    )

    assert calls and calls[0][0] == Path("scanned.pdf")
    assert [choice.text for choice in parsed.questions[0].choices] == ["가", "나", "다", "라"]
    assert answer_key == {}


def test_public_ocr_coverage_uses_authoritative_expected_count(monkeypatch):
    import scripts.import_public_exam_pdf_folder as public_importer
    from src.parser.offline_exam import ParsedOfflineQuestion
    from src.parser.offline_sources import DocumentRole, OfflineParseResult

    questions = tuple(
        ParsedOfflineQuestion(number, f"Q{number}", ["a", "b", "c", "d"], 1, 0.99, ())
        for number in range(1, 6)
    )
    monkeypatch.setattr(
        public_importer,
        "parse_offline_question_pdf",
        lambda path, metadata: OfflineParseResult(path, DocumentRole.QUESTION, metadata, questions, ()),
    )
    meta = public_importer.PdfMeta(
        path=Path("scanned.pdf"),
        relative_path="scanned.pdf",
        role="문제",
        exam_type="해경",
        subject_name="항해학",
        year=2025,
        session=1,
        document_id="doc",
        top_category="해경",
        expected_question_count=20,
    )

    parsed, answer_key = public_importer.build_ocr_required_exam(
        Path("scanned.pdf"), meta, None, "file:///scanned.pdf"
    )

    assert answer_key == {}
    assert parsed.diagnostics["expected_question_numbers"] == list(range(1, 21))
    assert "question_coverage_mismatch" in public_importer.extra_quality_errors(parsed, answer_key)


def test_public_ocr_without_authoritative_coverage_is_blocked(monkeypatch):
    import scripts.import_public_exam_pdf_folder as public_importer
    from src.parser.offline_exam import ParsedOfflineQuestion
    from src.parser.offline_sources import DocumentRole, OfflineParseResult

    questions = tuple(
        ParsedOfflineQuestion(number, f"Q{number}", ["a", "b", "c", "d"], 1, 0.99, ())
        for number in range(1, 11)
    )
    monkeypatch.setattr(
        public_importer,
        "parse_offline_question_pdf",
        lambda path, metadata: OfflineParseResult(path, DocumentRole.QUESTION, metadata, questions, ()),
    )
    meta = public_importer.PdfMeta(
        Path("scanned.pdf"), "scanned.pdf", "문제", "해경", "항해학", 2025, 1, "doc", "해경"
    )

    parsed, answer_key = public_importer.build_ocr_required_exam(
        Path("scanned.pdf"), meta, None, "file:///scanned.pdf"
    )

    assert parsed.diagnostics["expected_question_numbers"] == []
    assert "expected_question_coverage_unknown" in public_importer.extra_quality_errors(
        parsed, answer_key
    )


def test_infer_meta_populates_count_only_for_trusted_exam_format(tmp_path):
    import scripts.import_public_exam_pdf_folder as public_importer

    known = tmp_path / "해경" / "2025" / "항해학" / "2025_해경_항해학_자료_100.pdf"
    unknown = tmp_path / "미분류" / "2025" / "과목" / "2025_미분류_과목_자료_101.pdf"

    known_meta = public_importer.infer_meta(known, tmp_path)
    unknown_meta = public_importer.infer_meta(unknown, tmp_path)

    assert known_meta.expected_question_count == 20
    assert unknown_meta.expected_question_count is None


def test_parsed_answer_key_cannot_establish_expected_ocr_coverage(monkeypatch):
    import scripts.import_public_exam_pdf_folder as public_importer
    from src.parser.offline_exam import ParsedOfflineQuestion
    from src.parser.offline_sources import DocumentRole, OfflineParseResult
    from src.web_import.comcbt_pdf import PdfTextLine

    questions = tuple(
        ParsedOfflineQuestion(number, f"Q{number}", ["a", "b", "c", "d"], 1, 0.99, ())
        for number in range(1, 11)
    )
    monkeypatch.setattr(
        public_importer,
        "parse_offline_question_pdf",
        lambda path, metadata: OfflineParseResult(path, DocumentRole.QUESTION, metadata, questions, ()),
    )
    monkeypatch.setattr(
        public_importer,
        "parse_gong_answer_key",
        lambda lines, expected: {number: 1 for number in range(1, 11)},
    )
    meta = public_importer.PdfMeta(
        Path("unknown.pdf"), "unknown.pdf", "문제", "미분류", "과목", 2025, 1, "doc", "미분류"
    )
    answer_text = public_importer.CleanTextResult(
        [PdfTextLine("answer")], 1, True, 1, 1, 0, []
    )

    parsed, answer_key = public_importer.build_ocr_required_exam(
        Path("unknown.pdf"), meta, answer_text, "file:///unknown.pdf"
    )

    assert len(answer_key) == 10
    assert parsed.diagnostics["expected_question_numbers"] == []
    assert parsed.diagnostics["expected_question_coverage_unknown"] is True


def test_public_ocr_conversion_preserves_explicit_shared_passage_groups(monkeypatch):
    import scripts.import_public_exam_pdf_folder as public_importer
    from src.parser.offline_exam import ParsedOfflineQuestion
    from src.parser.offline_sources import DocumentRole, OfflineParseResult

    page = _page_with_question()
    passage = _line(["[1~2]", "다음", "글을", "읽고", "답하시오."], 0.04)
    question_two_lines = (
        _line(["2.", "둘째", "문제"], 0.55),
        _line(["①", "가"], 0.63),
        _line(["②", "나"], 0.71),
        _line(["③", "다"], 0.79),
        _line(["④", "라"], 0.87),
    )
    structured = StructuredPage(
        1, 1, 1, "scanned", (passage, *page.lines, *question_two_lines), ()
    )
    questions = (
        ParsedOfflineQuestion(1, "첫째 문제", ["가", "나", "다", "라"], 1, 0.99, ()),
        ParsedOfflineQuestion(2, "둘째 문제", ["가", "나", "다", "라"], 1, 0.99, ()),
    )
    monkeypatch.setattr(
        public_importer,
        "parse_offline_question_pdf",
        lambda path, metadata: OfflineParseResult(
            path, DocumentRole.QUESTION, metadata, questions, (), (structured,)
        ),
    )
    meta = public_importer.PdfMeta(
        Path("scanned.pdf"), "scanned.pdf", "문제", "해경", "항해학", 2025, 1, "doc", "해경", 2
    )

    parsed, _ = public_importer.build_ocr_required_exam(
        Path("scanned.pdf"), meta, None, "file:///scanned.pdf"
    )

    assert len(parsed.groups) == 1
    assert parsed.groups[0].child_numbers == [1, 2]
    assert parsed.questions[0].shared_passage == parsed.groups[0].text
    assert parsed.questions[1].group_id == parsed.groups[0].group_id


def test_public_ocr_reads_paired_scanned_answer_with_shared_extractor(monkeypatch):
    import scripts.import_public_exam_pdf_folder as public_importer
    from src.parser.offline_exam import ParsedOfflineQuestion
    from src.parser.offline_sources import DocumentRole, OfflineParseResult

    questions = tuple(
        ParsedOfflineQuestion(number, f"Q{number}", ["a", "b", "c", "d"], 1, 0.99, ())
        for number in range(1, 6)
    )
    monkeypatch.setattr(
        public_importer,
        "parse_offline_question_pdf",
        lambda path, metadata: OfflineParseResult(path, DocumentRole.QUESTION, metadata, questions, ()),
    )
    answer_page = StructuredPage(
        1,
        1,
        1,
        "scanned",
        (
            _line(["1", "2", "3", "4", "5"], 0.20),
            _line(["①", "②", "③", "④", "①"], 0.30),
        ),
        (),
    )
    extracted = []

    def fake_extract(path, metadata=None):
        extracted.append(path)
        return (answer_page,)

    monkeypatch.setattr(public_importer, "extract_offline_structured_pages", fake_extract)
    answer_text = public_importer.CleanTextResult([], 1, False, None, None, 0, [])
    meta = public_importer.PdfMeta(
        Path("question.pdf"), "question.pdf", "문제", "해경", "항해학", 2025, 1, "doc", "해경", 5
    )

    parsed, answer_key = public_importer.build_ocr_required_exam(
        Path("question.pdf"),
        meta,
        answer_text,
        "file:///question.pdf",
        answer_path=Path("answer.pdf"),
    )

    assert extracted == [Path("answer.pdf")]
    assert answer_key == {1: 1, 2: 2, 3: 3, 4: 4, 5: 1}
    assert [question.correct_answer for question in parsed.questions] == [1, 2, 3, 4, 1]


@pytest.mark.parametrize(
    ("stem", "choices", "reason"),
    [
        (
            "카르노 사이클에 해당하는 것은?",
            ("정적압축 정적팽창 단열팽창 단열압축→ → →", "나", "다", "라"),
            "suspicious_choice",
        ),
        (
            "압력은 [0/해 로 표시한다.",
            ("가", "나", "다", "라"),
            "broken_unit_stem",
        ),
        (
            "다음 (설명 중 옳은 것은?",
            ("가", "나", "다", "라"),
            "unbalanced_stem_delimiter",
        ),
        (
            "다음 중 옳은 것은?",
            ("정상", "0卜 잡문자", "다", "라"),
            "ocr_noise_choice",
        ),
    ],
)
def test_offline_quality_rejects_residual_text_corruption(stem, choices, reason):
    from src.parser.offline_exam import ParsedOfflineQuestion
    from src.parser.offline_quality import validate_offline_question

    result = validate_offline_question(
        ParsedOfflineQuestion(1, stem, list(choices), 1, 1.0, ())
    )

    assert result.importable is False
    assert reason in result.reason_codes


def test_offline_quality_accepts_valid_arrows_and_example_parenthesis():
    from src.parser.offline_exam import ParsedOfflineQuestion
    from src.parser.offline_quality import validate_offline_question

    result = validate_offline_question(
        ParsedOfflineQuestion(
            1,
            "A → B의 관계는?",
            ["Ex.) 정상 예시", "나", "다", "라"],
            1,
            1.0,
            (),
        )
    )

    assert result.importable is True


def test_shared_text_quality_allows_valid_korean_translation_and_common_words():
    from src.parser.text_quality import text_quality_issue_codes

    assert text_quality_issue_codes(
        '"These goods emit flammable gases." [이 화물은 인화성 가스를 방출한다.]'
    ) == ()
    assert text_quality_issue_codes(
        "연필을 쥐는 것처럼 주사기를 쥐고 피부를 누른다."
    ) == ()


def test_shared_text_quality_flags_residual_korean_ocr_garble():
    from src.parser.text_quality import text_quality_issue_codes

    assert "ocr_noise" in text_quality_issue_codes(
        "발사한 초음파가 해저에서 되 도 근 }~= 0 느 시간을 측정한다."
    )
    assert "ocr_noise" in text_quality_issue_codes(
        "수상(水上)의 정의로 가장 을d卜른 것은?"
    )
    assert "ocr_noise" in text_quality_issue_codes(
        "다음 중 r선박직원법]의 내용으로 가장 옳지 않은 것은?"
    )
    assert "ocr_noise" in text_quality_issue_codes(
        "해양수산부령O己 정呑는 전자적 수단"
    )
    assert "ocr_noise" in text_quality_issue_codes(
        "다읔 <보기> 중 가장 오으 것은?"
    )
    assert "ocr_noise" in text_quality_issue_codes(
        "디음 중 설명으로 옳은 것은?"
    )


def test_shared_text_quality_flags_english_zero_one_ocr_confusables():
    from src.parser.text_quality import text_quality_issue_codes

    assert "ocr_noise" in text_quality_issue_codes(
        "International Regulations for Preventing C011isions at Sea"
    )
    assert "ocr_noise" in text_quality_issue_codes(
        "Where 011e of two vessels is t0 keep out 0f the way"
    )
    assert text_quality_issue_codes(
        "International Regulations for Preventing Collisions at Sea"
    ) == ()
    assert "ocr_noise" in text_quality_issue_codes(
        "CIearance가 작고 CoIIisions가 발생한다."
    )
    assert "ocr_noise" in text_quality_issue_codes(
        "발호PI간이 짧고 일어L는 현상이다."
    )
    assert text_quality_issue_codes(
        "A1해역, 제1조, 10cm, NaOH, 지진파의 S파"
    ) == ()


def test_shared_text_quality_flags_intrusive_cjk_ocr_but_allows_annotations():
    from src.parser.text_quality import text_quality_issue_codes

    assert "ocr_noise" in text_quality_issue_codes(
        "유·도선 사업자는 승선 亏는 선원에게 비상훈련을 실시한다."
    )
    assert "ocr_noise" in text_quality_issue_codes(
        "무해통항(匁k害通航)에 관한 설명으로 옳은 것은?"
    )
    assert text_quality_issue_codes(
        "수상(水上) 및 항적(航跡)에 관한 설명이다. 선장 甲은 이를 기록한다."
    ) == ()


def test_shared_text_quality_allows_party_hanja_attached_to_role_noun():
    from src.parser.text_quality import text_quality_issue_codes

    assert text_quality_issue_codes("甲선장의 선상 쟁의행위 신고가 접수되었다.") == ()
    assert text_quality_issue_codes("함정에 승선한 甲경장은 면허를 갱신하였다.") == ()
