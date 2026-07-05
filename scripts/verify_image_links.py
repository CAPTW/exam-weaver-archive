import sys
import os

sys.path.append(os.getcwd())

from src.parser.main import ExamPDFParser
from src.parser.question import QuestionParser
from src.parser.extractor import PDFExtractor
from src.parser.metadata import ExamMetadataParser


def needs_image(question) -> bool:
    if len(question.choices) < 4:
        return True
    return any(
        token in question.text
        for token in ["그림", "도표", "사진", "Fig", "Figure", "diagram", "chart", "graph"]
    )


def verify(question_pdf: str, answer_pdf: str):
    parser = ExamPDFParser()
    result = parser.parse(question_pdf, answer_pdf)
    questions = result["questions"]

    total = len(questions)
    needs = [q for q in questions if needs_image(q)]
    linked = [q for q in needs if q.image_path]

    print("Total questions:", total)
    print("Needs image:", len(needs))
    print("Linked images:", len(linked))
    print("Missing links:", len(needs) - len(linked))

    # show a few missing samples
    if needs and len(linked) < len(needs):
        print("\nMissing samples (up to 5):")
        for q in needs[:5]:
            if not q.image_path:
                print(
                    f"- {q.year}년 {q.session}회 {q.subject_name} {q.number}번 (page {q.source_page})"
                )

    # page-level candidate image stats
    extractor = PDFExtractor()
    content = extractor.extract(question_pdf)
    meta_parser = ExamMetadataParser()
    # find first exam type for parser instantiation
    exam_type = None
    for page in content.pages:
        meta = meta_parser.parse_cover(page.text)
        if meta:
            exam_type = meta.exam_type
            break
    question_parser = QuestionParser(exam_type or "")

    pages_with_candidates = 0
    total_candidates = 0
    for page in content.pages:
        if question_parser._is_cover_page(page.text):
            continue
        candidates = question_parser._filter_image_candidates(page.image_paths)
        if candidates:
            pages_with_candidates += 1
            total_candidates += len(candidates)

    print("\nCandidate images (filtered):")
    print("Pages with candidates:", pages_with_candidates)
    print("Total candidates:", total_candidates)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python scripts/verify_image_links.py <question_pdf> <answer_pdf>")
        raise SystemExit(1)
    verify(sys.argv[1], sys.argv[2])
