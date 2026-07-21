from pathlib import Path

import fitz

from src.database.source_review import (
    attach_legacy_maritime_sources,
    render_source_evidence,
)
from src.database.text_repair import TextFinding


def test_render_source_evidence_deduplicates_pdf_page(tmp_path):
    pdf_path = tmp_path / "source.pdf"
    document = fitz.open()
    page = document.new_page(width=200, height=200)
    page.insert_text((20, 40), "source evidence")
    document.save(pdf_path)
    document.close()
    findings = [
        TextFinding(
            category="ocr_review",
            severity="needs_source_review",
            table="questions",
            row_id=1,
            question_id=1,
            field_path="question_text",
            text="suspect",
            metadata={"source_url": pdf_path.as_uri(), "source_page": 1},
        ),
        TextFinding(
            category="ocr_review",
            severity="needs_source_review",
            table="questions",
            row_id=1,
            question_id=1,
            field_path=(
                "question_format_json.tables[0].rows[0][0]"
            ),
            text="suspect",
            metadata={"source_url": pdf_path.as_uri(), "source_page": 1},
        ),
    ]

    evidence = render_source_evidence(findings, tmp_path / "evidence")

    assert len(evidence) == 1
    assert evidence[0].status == "rendered"
    assert evidence[0].image_path is not None
    assert evidence[0].image_path.is_file()
    assert evidence[0].finding_count == 2


def test_render_source_evidence_reports_missing_source_without_guessing(
    tmp_path,
):
    finding = TextFinding(
        category="ocr_review",
        severity="needs_source_review",
        table="questions",
        row_id=1,
        question_id=1,
        field_path="question_text",
        text="suspect",
        metadata={
            "source_url": (tmp_path / "missing.pdf").as_uri(),
            "source_page": 2,
        },
    )

    evidence = render_source_evidence([finding], tmp_path / "evidence")

    assert evidence[0].status == "source_unavailable"
    assert evidence[0].image_path is None


def test_attach_legacy_maritime_sources_maps_exam_identity_to_pdf(tmp_path):
    source_root = tmp_path / "기출문제 모음"
    pdf_path = source_root / "2019" / "2019_201903.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"source placeholder")
    finding = TextFinding(
        category="ocr_noise_text",
        severity="needs_source_review",
        table="questions",
        row_id=9,
        question_id=9,
        field_path="question_text",
        text="의심 문장",
        metadata={
            "year": 2019,
            "exam_code": "3급기관사",
            "source_page": 7,
            "source_url": None,
        },
    )

    enriched = attach_legacy_maritime_sources((finding,), source_root)

    assert enriched[0].metadata["source_url"] == pdf_path.as_uri()
    assert enriched[0].metadata["source_document"] == "2019_201903.pdf"


def test_attach_legacy_maritime_sources_preserves_registered_source(tmp_path):
    registered = (tmp_path / "registered.pdf").as_uri()
    finding = TextFinding(
        category="ocr_noise_text",
        severity="needs_source_review",
        table="questions",
        row_id=9,
        question_id=9,
        field_path="question_text",
        text="의심 문장",
        metadata={
            "year": 2018,
            "exam_code": "4급항해사(상선)",
            "source_page": 2,
            "source_url": registered,
        },
    )

    enriched = attach_legacy_maritime_sources((finding,), tmp_path)

    assert enriched[0].metadata["source_url"] == registered
