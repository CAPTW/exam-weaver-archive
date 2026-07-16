# src/parser/main.py
"""메인 PDF 파서"""

import logging
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

from .extractor import PDFExtractor
from .metadata import ExamMetadataParser
from .metadata import ExamMetadata
from .question import Choice, Question, QuestionParser
from .answer import AnswerParser
from .merger import DataMerger
from .patterns import EXAM_SUBJECT_ORDER, QUESTION_START

logger = logging.getLogger(__name__)


class ExamPDFParser:
    """시험 PDF 파서"""
    
    def __init__(self, work_dir: str = './data/extracted'):
        self.extractor = PDFExtractor(work_dir)
        self.metadata_parser = ExamMetadataParser()
        self.answer_parser = AnswerParser()
        self.merger = DataMerger()
    
    def parse(self, 
              question_pdf: str, 
              answer_pdf: Optional[str] = None,
              exam_type: Optional[str] = None) -> dict:
        """
        시험문제 PDF와 정답지 PDF 파싱
        
        Args:
            question_pdf: 시험문제 PDF 경로
            answer_pdf: 정답지 PDF 경로
            exam_type: 시험 종류 (자동 감지 시 None)
            
        Returns:
            {
                'metadata': ExamMetadata,
                'questions': List[Question],
                'validation': ValidationResult,
                'stats': dict
            }
        """
        logger.info(f"파싱 시작: {question_pdf}")
        
        # 1. PDF 압축 해제
        logger.info("[1/5] PDF 압축 해제...")
        question_content = self.extractor.extract(question_pdf)
        if self._should_parse_embedded_answers(question_pdf, answer_pdf, question_content):
            return self._parse_embedded_answer_pdf(question_pdf, question_content, exam_type)

        if answer_pdf is None:
            raise ValueError("정답지 PDF 경로가 필요합니다.")

        answer_content = self.extractor.extract(answer_pdf)
        
        # 2. 메타데이터 추출 (표지 여러 개 대응)
        logger.info("[2/5] 메타데이터 파싱...")
        metadata_blocks = []
        include_metadata_pages = False
        for idx, page in enumerate(question_content.pages):
            meta = self.metadata_parser.parse_cover(page.text)
            if meta:
                metadata_blocks.append((idx, meta))
        
        if not metadata_blocks:
            metadata_blocks = self._infer_scanned_metadata_blocks(
                question_pdf,
                question_content.pages,
                exam_type,
            )
            include_metadata_pages = bool(metadata_blocks)

        if not metadata_blocks:
            raise ValueError("시험 정보를 찾을 수 없습니다.")

        # exam_type 오버라이드
        if exam_type:
            for _, meta in metadata_blocks:
                meta.exam_type = exam_type

        if metadata_blocks and any(
            self._metadata_page_has_questions(question_content.pages[idx].text)
            for idx, _ in metadata_blocks
        ):
            include_metadata_pages = True
        
        # 첫 메타데이터를 대표로 사용 (하위 호환)
        metadata = metadata_blocks[0][1]
        logger.info(f"  - {metadata.year}년 제{metadata.session}회 {metadata.exam_type}")
        
        # 3. 문제 파싱 (세션별)
        logger.info("[3/5] 문제 파싱...")
        questions = []
        for block_idx, (start_idx, meta) in enumerate(metadata_blocks):
            end_idx = metadata_blocks[block_idx + 1][0] if block_idx + 1 < len(metadata_blocks) else len(question_content.pages)
            parse_start_idx = start_idx if include_metadata_pages else start_idx + 1
            block_pages = question_content.pages[parse_start_idx:end_idx]
            question_parser = QuestionParser(meta.exam_type)
            block_questions = question_parser.parse_questions(block_pages, recover_missing=False)

            # 세션 메타데이터 부여
            for q in block_questions:
                q.year = meta.year
                q.session = meta.session
                q.exam_type = meta.exam_type

            questions.extend(block_questions)

        logger.info(f"  - {len(questions)}문제 추출")
        
        # 4. 정답 파싱
        logger.info("[4/5] 정답 파싱...")
        answers = self._parse_answers_for_metadata_blocks(
            answer_content.pages,
            metadata_blocks,
        )
        logger.info(f"  - {sum(len(v) for v in answers.values())}개 정답 추출")
        
        # 5. 데이터 병합 및 검증
        logger.info("[5/5] 데이터 병합...")
        questions = self._repair_embedded_question_groups(
            questions,
            answers,
            metadata,
            drop_unexpected=True,
        )
        merged_questions = self.merger.merge(questions, answers, metadata)
        validation = self.merger.validate(merged_questions)
        
        # 통계
        stats = self._calculate_stats(merged_questions)
        
        if validation.errors:
            for err in validation.errors:
                logger.error(f"  [ERROR] {err}")
        if validation.warnings:
            for warn in validation.warnings:
                logger.warning(f"  [WARN] {warn}")
        
        logger.info(f"파싱 완료: {stats['total_questions']}문제")
        
        return {
            'metadata': metadata,
            'metadata_list': [meta for _, meta in metadata_blocks],
            'questions': merged_questions,
            'validation': validation,
            'stats': stats
        }

    def _metadata_page_has_questions(self, text: str) -> bool:
        return len(QUESTION_START.findall(text or '')) >= 2

    def _infer_scanned_metadata_blocks(
        self,
        question_pdf: str,
        pages: list,
        exam_type: Optional[str],
    ) -> list[tuple[int, ExamMetadata]]:
        if not exam_type:
            return []

        blocks = []
        for idx, page in enumerate(pages):
            match = re.search(
                r'(20\d{2})\s*년\s*도?\s*정기\s*제\s*([1-4])\s*회\s*(?:[가-힣A-Za-z]+)?시험',
                page.text or '',
            )
            if not match:
                continue
            blocks.append((
                idx,
                ExamMetadata(
                    year=int(match.group(1)),
                    session=int(match.group(2)),
                    exam_type=exam_type,
                    is_domestic='국내' in exam_type,
                )
            ))

        if blocks:
            return blocks

        year = self._extract_year_from_path(question_pdf)
        if not year:
            return []
        return [(
            0,
            ExamMetadata(
                year=year,
                session=1,
                exam_type=exam_type,
                is_domestic='국내' in exam_type,
            )
        )]

    def _parse_answers_for_metadata_blocks(self, answer_pages: list, metadata_blocks: list) -> dict:
        """Parse answer sheets once for each distinct year/exam type in a question set."""
        answers = {}
        seen = set()
        for _, meta in metadata_blocks:
            key = (meta.year, meta.exam_type)
            if key in seen:
                continue
            seen.add(key)
            parsed = self.answer_parser.parse_answers(
                answer_pages,
                exam_type=meta.exam_type,
                year_hint=meta.year,
            )
            answers.update(parsed)
        return answers

    def _should_parse_embedded_answers(self, question_pdf: str, answer_pdf: Optional[str], question_content) -> bool:
        if answer_pdf and not self._is_same_path(question_pdf, answer_pdf):
            return False
        if not question_content.pages:
            return False
        return self._is_embedded_answer_page(question_content.pages[-1].text)

    def _is_same_path(self, left: str, right: Optional[str]) -> bool:
        if not right:
            return True
        try:
            return Path(left).resolve() == Path(right).resolve()
        except Exception:
            return str(left) == str(right)

    def _is_embedded_answer_page(self, text: str) -> bool:
        compact = re.sub(r'\s+', '', text or '')
        answer_count = len(re.findall(r'[가나사아]', text or ''))
        has_number_header = bool(re.search(r'\b1\b.*\b25\b', text or '', re.DOTALL))
        return (
            '과목' in compact
            and has_number_header
            and answer_count >= 80
        )

    def _parse_embedded_answer_pdf(self, question_pdf: str, content, exam_type: Optional[str]) -> dict:
        metadata = self._infer_embedded_metadata(question_pdf, content.pages, exam_type)
        answer_page = content.pages[-1]
        body_pages = content.pages[:-1]

        answers = self.answer_parser.parse_answers(
            [
                SimpleNamespace(
                    text='',
                    source_path=content.source_path,
                    number=answer_page.number,
                )
            ],
            exam_type=metadata.exam_type,
            year_hint=metadata.year,
        )

        question_parser = QuestionParser(metadata.exam_type)
        questions = []
        current_session = metadata.session
        current_subject = None
        current_subject_idx = 0
        current_subject_count = 0
        prev_question_num = None
        subject_order = EXAM_SUBJECT_ORDER.get(metadata.exam_type, [])

        for page in body_pages:
            session = self._extract_session_from_page_text(page.text)
            if session and session != current_session:
                current_session = session
                current_subject = None
                current_subject_idx = 0
                current_subject_count = 0
                prev_question_num = None
            page_subject = self._extract_subject_from_page_text(page.text, metadata.exam_type)
            if page_subject:
                if (
                    subject_order
                    and page_subject == subject_order[0]
                    and current_subject == subject_order[-1]
                    and prev_question_num is not None
                    and prev_question_num >= 20
                    and not session
                ):
                    current_session += 1
                    current_subject_idx = 0
                    current_subject_count = 0
                    prev_question_num = None

            segments = self._subject_segments_from_page_text(
                page.text,
                current_subject,
                metadata.exam_type,
            )
            for segment_subject, segment_text in segments:
                if segment_subject and segment_subject != current_subject:
                    current_subject = segment_subject
                    if segment_subject in subject_order:
                        current_subject_idx = subject_order.index(segment_subject)
                    current_subject_count = 0
                    prev_question_num = None

                image_paths = [] if getattr(page, 'is_ocr_text', False) else page.image_paths
                image_infos = [] if getattr(page, 'is_ocr_text', False) else getattr(page, 'image_infos', None)
                page_questions = question_parser._parse_page(
                    segment_text,
                    page.number,
                    image_paths,
                    image_infos,
                    getattr(page, 'underlined_texts', None),
                    getattr(page, 'tables', None),
                    getattr(page, 'overlined_texts', None),
                    allow_subject_reset=False,
                    structured_page=getattr(page, 'structured_page', None),
                )
                for q in page_questions:
                    if not current_subject and subject_order:
                        current_subject = subject_order[current_subject_idx]
                    elif (
                        prev_question_num is not None
                        and q.number == 1
                        and prev_question_num >= 20
                        and subject_order
                        and not segment_subject
                    ):
                        current_subject_idx = min(current_subject_idx + 1, len(subject_order) - 1)
                        current_subject = subject_order[current_subject_idx]
                        current_subject_count = 0
                    elif current_subject_count >= 25 and subject_order and not segment_subject:
                        current_subject_idx = min(current_subject_idx + 1, len(subject_order) - 1)
                        current_subject = subject_order[current_subject_idx]
                        current_subject_count = 0

                    q.year = metadata.year
                    q.session = current_session
                    q.exam_type = metadata.exam_type
                    q.subject_name = current_subject
                    current_subject_count += 1
                    prev_question_num = q.number
                questions.extend(page_questions)

        questions = self._repair_embedded_question_groups(questions, answers, metadata)
        merged_questions = self.merger.merge(questions, answers, metadata)
        validation = self.merger.validate(merged_questions)
        stats = self._calculate_stats(merged_questions)
        sessions = sorted({q.session for q in merged_questions if q.session})
        metadata_list = [
            ExamMetadata(metadata.year, session, metadata.exam_type, metadata.is_domestic)
            for session in sessions
        ] or [metadata]

        logger.info(f"파싱 완료: {stats['total_questions']}문제")
        return {
            'metadata': metadata,
            'metadata_list': metadata_list,
            'questions': merged_questions,
            'validation': validation,
            'stats': stats,
        }

    def _repair_embedded_question_groups(
        self,
        questions: list,
        answers: dict,
        metadata: ExamMetadata,
        drop_unexpected: bool = False,
    ) -> list:
        subject_order = EXAM_SUBJECT_ORDER.get(metadata.exam_type, [])
        question_order = {id(q): idx for idx, q in enumerate(questions)}
        grouped = {}
        for q in questions:
            key = (q.year or metadata.year, q.session or metadata.session, q.exam_type or metadata.exam_type, q.subject_name)
            grouped.setdefault(key, []).append(q)

        expected_keys = []
        for key in sorted(answers):
            if len(key) == 4:
                year, session, exam_type, subject = key
            else:
                year, session, subject = key
                exam_type = metadata.exam_type
            if year == metadata.year and exam_type == metadata.exam_type:
                expected_keys.append((year, session, exam_type, subject))

        repaired = []
        seen_expected = set()
        for key in expected_keys:
            seen_expected.add(key)
            group = sorted(grouped.get(key, []), key=lambda q: question_order.get(id(q), 0))
            by_number = {}
            for q in group:
                if 1 <= q.number <= 25 and q.number not in by_number:
                    by_number[q.number] = q
            year, session, exam_type, subject = key
            for number in range(1, 26):
                q = by_number.get(number)
                if q is None:
                    q = self._placeholder_question(year, session, exam_type, subject, number)
                repaired.append(q)

        for key, group in grouped.items():
            if key in seen_expected:
                continue
            if drop_unexpected:
                continue
            repaired.extend(sorted(group, key=lambda q: question_order.get(id(q), 0)))

        subject_index = {subject: idx for idx, subject in enumerate(subject_order)}
        return sorted(
            repaired,
            key=lambda q: (
                q.year or metadata.year,
                q.session or metadata.session,
                subject_index.get(q.subject_name, 99),
                q.number,
            )
        )

    def _placeholder_question(
        self,
        year: int,
        session: int,
        exam_type: str,
        subject: str,
        number: int,
    ) -> Question:
        return Question(
            number=number,
            text='[OCR 누락] 원본 PDF에서 문항을 확인해 주세요.',
            choices=[
                Choice(number=1, symbol='가.', text=''),
                Choice(number=2, symbol='나.', text=''),
                Choice(number=3, symbol='사.', text=''),
                Choice(number=4, symbol='아.', text=''),
            ],
            subject_name=subject,
            year=year,
            session=session,
            exam_type=exam_type,
        )

    def _infer_embedded_metadata(self, question_pdf: str, pages: list, exam_type: Optional[str]) -> ExamMetadata:
        text = "\n".join(page.text for page in pages if getattr(page, 'text', None))
        year = self._extract_year_from_path(question_pdf) or self._extract_year_from_text(text)
        detected_exam_type = exam_type or self._extract_embedded_exam_type(text)
        if not year or not detected_exam_type:
            raise ValueError("내장 답안형 PDF의 시험 정보를 찾을 수 없습니다.")
        return ExamMetadata(
            year=year,
            session=1,
            exam_type=detected_exam_type,
            is_domestic='국내' in detected_exam_type,
        )

    def _extract_year_from_path(self, path: str) -> Optional[int]:
        stem = Path(path).stem
        match = re.search(r'(20\d{2})', stem)
        return int(match.group(1)) if match else None

    def _extract_year_from_text(self, text: str) -> Optional[int]:
        match = re.search(r'(20\d{2})', text or '')
        if match:
            return int(match.group(1))
        short_match = re.search(r"'?\s*(\d{2})\s*년", text or '')
        if short_match:
            value = int(short_match.group(1))
            return 2000 + value if value < 70 else 1900 + value
        return None

    def _extract_embedded_exam_type(self, text: str) -> Optional[str]:
        compact = re.sub(r'\s+', '', text or '')
        match = re.search(r'([1-6])급(기관사|항해사)', compact)
        if not match:
            return None
        base = f"{match.group(1)}급{match.group(2)}"
        if match.group(2) == '항해사':
            if '어선전문' in compact or '어선' in compact:
                return f"{base}(어선)"
            if '상선전문' in compact or '상선' in compact:
                return f"{base}(상선)"
        return base

    def _extract_session_from_page_text(self, text: str) -> Optional[int]:
        for line in (text or '').splitlines():
            compact = re.sub(r'\s+', '', line)
            match = re.fullmatch(r'(?:20\d{2}년?)?정기?제([1-4])회', compact)
            if match:
                return int(match.group(1))
            match = re.fullmatch(r'제([1-4])회', compact)
            if match:
                return int(match.group(1))
        return None

    def _extract_subject_from_page_text(self, text: str, exam_type: str) -> Optional[str]:
        candidates = EXAM_SUBJECT_ORDER.get(exam_type, [])
        header_match = re.search(
            r'\[?\s*제\s*(\d+)\s*과목\s*\[?\s*([가-힣0-9]+)?\s*\]?',
            text or ''
        )
        if header_match:
            subject = self._subject_from_course_marker(
                header_match.group(1),
                header_match.group(2),
                exam_type,
            )
            if subject:
                return subject

        for match in re.finditer(r'\[\s*([^\]]+?)\s*\]', text or ''):
            normalized = self._normalize_subject_text(match.group(1))
            if normalized in candidates:
                return normalized
        return None

    def _subject_segments_from_page_text(
        self,
        text: str,
        current_subject: Optional[str],
        exam_type: str,
    ) -> list[tuple[Optional[str], str]]:
        candidates = EXAM_SUBJECT_ORDER.get(exam_type, [])
        markers = []
        marker_pattern = re.compile(
            r'\[?\s*제\s*(\d+)\s*과목\s*\[?\s*([가-힣0-9]+)?\s*\]?'
        )
        for match in marker_pattern.finditer(text or ''):
            subject = self._subject_from_course_marker(match.group(1), match.group(2), exam_type)
            if subject in candidates or self._is_ignored_specialized_subject(match.group(2), exam_type):
                markers.append((match.start(), match.end(), subject))

        if not markers:
            return [(current_subject, text)]

        segments = []
        if markers[0][0] > 0:
            segments.append((current_subject, text[:markers[0][0]]))
        for idx, (_, end, subject) in enumerate(markers):
            next_start = markers[idx + 1][0] if idx + 1 < len(markers) else len(text)
            if subject:
                segments.append((subject, text[end:next_start]))
        return segments

    def _normalize_subject_text(self, value: str) -> str:
        normalized = re.sub(r'\s+', '', value or '')
        aliases = {
            '직무': '직무일반',
            '직무일반': '직무일반',
        }
        return aliases.get(normalized, normalized)

    def _subject_from_course_marker(
        self,
        course_text: Optional[str],
        raw_subject: Optional[str],
        exam_type: str,
    ) -> Optional[str]:
        subject_order = EXAM_SUBJECT_ORDER.get(exam_type, [])
        normalized = self._normalize_subject_text(raw_subject or '')
        if normalized in subject_order:
            return normalized
        if self._is_ignored_specialized_subject(raw_subject, exam_type):
            return None

        try:
            course_index = int(course_text or '0') - 1
        except ValueError:
            course_index = -1
        if 0 <= course_index < len(subject_order):
            return subject_order[course_index]

        return normalized if normalized in subject_order else None

    def _is_ignored_specialized_subject(
        self,
        raw_subject: Optional[str],
        exam_type: str,
    ) -> bool:
        normalized = self._normalize_subject_text(raw_subject or '')
        if normalized not in {'상선전문', '어선전문'}:
            return False
        subject_order = EXAM_SUBJECT_ORDER.get(exam_type, [])
        target_specialized = next(
            (subject for subject in subject_order if subject in {'상선전문', '어선전문'}),
            None,
        )
        return bool(target_specialized and normalized != target_specialized)
    
    def _calculate_stats(self, questions: list) -> dict:
        """통계 계산"""
        subject_counts = {}
        for q in questions:
            subject = q.subject_name or 'unknown'
            subject_counts[subject] = subject_counts.get(subject, 0) + 1
        
        return {
            'total_questions': len(questions),
            'by_subject': subject_counts,
            'with_images': sum(1 for q in questions if q.has_image),
            'with_answers': sum(1 for q in questions if q.correct_answer)
        }
