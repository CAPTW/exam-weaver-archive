"""Extract page-level text from exam PDFs into a JSONL cache.

Usage:
    python scripts/extract_pdf_text.py <input_pdf_dir> <output_dir>

The script is intentionally read-only with respect to the input folder. OCR cache,
inventory CSV, and page JSONL files are written only under the output directory.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.parser.extractor import PDFExtractor  # noqa: E402


@dataclass
class NativeTextProbe:
    page_count: int
    non_empty_pages: int
    total_chars: int


def native_text_probe(pdf_path: Path) -> NativeTextProbe:
    doc = fitz.open(pdf_path)
    try:
        total_chars = 0
        non_empty_pages = 0
        for page in doc:
            text = page.get_text("text") or ""
            chars = len(text.strip())
            total_chars += chars
            if chars >= 50:
                non_empty_pages += 1
        return NativeTextProbe(
            page_count=doc.page_count,
            non_empty_pages=non_empty_pages,
            total_chars=total_chars,
        )
    finally:
        doc.close()


def infer_year_label(filename: str, sample_text: str) -> str:
    haystack = f"{filename} {sample_text}"
    years = sorted({int(y) for y in re.findall(r"20\d{2}", haystack)})
    short_years = re.findall(r"(?<!\d)(\d{2})\s*년", haystack)
    for value in short_years:
        year = 2000 + int(value)
        if 2010 <= year <= 2035:
            years.append(year)
    years = sorted(set(years))
    if not years:
        return "unknown"
    if len(years) == 1:
        return str(years[0])
    return f"{years[0]}-{years[-1]}"


def infer_subject(filename: str) -> str:
    if "해사법규" in filename:
        return "해사법규"
    if "해사영어" in filename:
        return "해사영어"
    if "항해학" in filename:
        return "항해학"
    if "기관학" in filename or "기관술" in filename:
        return "기관학"
    return "unknown"


def infer_exam(filename: str) -> str:
    subject = infer_subject(filename)
    if subject == "unknown":
        subject = "해사"
    if "기출정답" in filename:
        return f"해양경찰 채용 {subject} 정답"
    if "기출문제" in filename:
        return f"해양경찰 채용 {subject} 기출문제"
    return f"해양경찰 채용 {subject}"


def short_sample(pages: list) -> str:
    chunks = []
    for page in pages[:3]:
        chunks.append(getattr(page, "text", "") or "")
    return " ".join(" ".join(chunks).split())[:1000]


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: python scripts/extract_pdf_text.py <input_pdf_dir> <output_dir>", file=sys.stderr)
        return 2

    input_dir = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])
    extracted_dir = output_dir / "extracted_text"
    extracted_dir.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(input_dir.rglob("*.pdf"))
    if not pdfs:
        raise FileNotFoundError(f"No PDF files found under {input_dir}")

    extractor = PDFExtractor(str(extracted_dir / "cache"))
    inventory_rows = []
    page_jsonl_path = extracted_dir / "pages.jsonl"
    manifest_path = extracted_dir / "manifest.json"

    with page_jsonl_path.open("w", encoding="utf-8") as jsonl:
        for idx, pdf_path in enumerate(pdfs, start=1):
            pdf_id = f"PDF{idx:03d}"
            rel_path = str(pdf_path.relative_to(input_dir))
            print(f"[{idx}/{len(pdfs)}] extracting {rel_path}", flush=True)

            probe = native_text_probe(pdf_path)
            text_extractable = probe.non_empty_pages >= max(1, int(probe.page_count * 0.5))
            content = extractor.extract(str(pdf_path))
            sample = short_sample(content.pages)
            ocr_pages = sum(1 for page in content.pages if getattr(page, "is_ocr_text", False))
            extracted_non_empty_pages = sum(1 for page in content.pages if (page.text or "").strip())

            for page in content.pages:
                record = {
                    "pdf_id": pdf_id,
                    "filename": pdf_path.name,
                    "relative_path": rel_path,
                    "source_path": str(pdf_path),
                    "page": page.number,
                    "text": page.text or "",
                    "is_ocr_text": bool(getattr(page, "is_ocr_text", False)),
                    "has_visual_content": bool(getattr(page, "has_visual_content", False)),
                    "char_count": len((page.text or "").strip()),
                }
                jsonl.write(json.dumps(record, ensure_ascii=False) + "\n")

            notes = []
            if not text_extractable:
                notes.append("native text extraction was poor; OCR cache used")
            if extracted_non_empty_pages < probe.page_count:
                notes.append(f"{probe.page_count - extracted_non_empty_pages} page(s) still empty after extraction")
            if "기출정답" in pdf_path.name:
                notes.append("answer sheet, not a primary question source")

            inventory_rows.append({
                "pdf_id": pdf_id,
                "filename": pdf_path.name,
                "relative_path": rel_path,
                "page_count": probe.page_count,
                "text_extractable": str(text_extractable).lower(),
                "ocr_required": str(ocr_pages > 0 or not text_extractable).lower(),
                "inferred_exam": infer_exam(pdf_path.name),
                "inferred_year": infer_year_label(pdf_path.name, sample),
                "inferred_subject": infer_subject(pdf_path.name),
                "notes": "; ".join(notes),
            })

    inventory_path = output_dir / "01_pdf_inventory.csv"
    with inventory_path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(
            fp,
            fieldnames=[
                "pdf_id",
                "filename",
                "relative_path",
                "page_count",
                "text_extractable",
                "ocr_required",
                "inferred_exam",
                "inferred_year",
                "inferred_subject",
                "notes",
            ],
        )
        writer.writeheader()
        writer.writerows(inventory_rows)

    manifest = {
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "pdf_count": len(pdfs),
        "page_jsonl": str(page_jsonl_path),
        "inventory_csv": str(inventory_path),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {inventory_path}")
    print(f"Wrote {page_jsonl_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
