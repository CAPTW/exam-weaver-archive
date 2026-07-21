# src/parser/extractor.py
"""PDF(ZIP) 파일에서 텍스트 추출"""

import zipfile
import csv
import json
import os
import io
import contextlib
import hashlib
import unicodedata
import re
import math
import itertools
from difflib import SequenceMatcher
import queue
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence
from dataclasses import dataclass, field, replace
import pypdf
import logging

from src.parser.layout import (
    LayoutLine,
    LayoutWord,
    StructuredPage,
    TextDecoration,
    build_structured_page,
)
from src.parser.formatting import has_suspicious_text_artifact
from src.parser.text_quality import text_quality_issue_codes

logging.getLogger("pypdf").setLevel(logging.ERROR)


_VISUAL_QUESTION_START = re.compile(
    r"^\s*\d{1,3}\s*(?:[.)•]|\s+(?=(?:다음|[「\[]|r[가-힣])))"
)
_VISUAL_QUESTION_LEAD = re.compile(r"^\s*(?:다음|아래|[「\[]|r(?=[가-힣\[]))")
_VISUAL_HANGING_NUMBER = re.compile(r"^\s*\d{1,3}\s+")
_VISUAL_NUMBERED_CHOICE = re.compile(r"^\s*\d{1,3}\s*[.)]\s*[①-⑤㉠-㉭@]")
_VISUAL_EMBEDDED_QUESTION_START = re.compile(r".*?\d{1,3}\s*[.)]\s*다음")
_VISUAL_LEADING_NUMBER = re.compile(r"^\s*(\d{1,3})")
_VISUAL_DAMAGED_MARKERS = {"㉦": 1, "㉨": 2, "㉩": 2, "㉭": 3}
_VISUAL_EXPLICIT_MARKERS = {"①": 1, "②": 2, "③": 3, "④": 4}
_VISUAL_CHOICE_SYMBOLS = ("①", "②", "③", "④")
_VISUAL_PROPOSITION_MARKERS = set("㉠㉡㉢㉣㉤㉥")
_VISUAL_QUESTION_TERMINATOR = re.compile(
    r"(?:[?？]|고려하지\s*아니한다[.)]|"
    r"(?:것\s*은|것인가|무엇인가|있는가|거\s*은)\s*\d?"
    r"|고르시오[.]?)\s*$"
)
_VISUAL_DAMAGED_PREFIX = re.compile(r"^\(?[0O1-59@①-⑤㉦㉨㉩㉭年]\)?\s*")
_MUPDF_RENDER_LOCK = threading.RLock()
_TARGETED_OCR_STATE_LOCK = threading.Lock()
_TARGETED_OCR_ACTIVE_TOKEN: object | None = None
_TARGETED_OCR_CIRCUIT_OPEN = False


class _TargetedOcrTimeout(TimeoutError):
    """The sole targeted OCR worker exceeded its caller deadline."""


class _TargetedOcrUnavailable(RuntimeError):
    """Targeted OCR is busy or disabled after an earlier timeout."""


def _reset_targeted_ocr_circuit_for_tests() -> None:
    """Reset process-global OCR state after a test has released its worker."""
    global _TARGETED_OCR_CIRCUIT_OPEN
    with _TARGETED_OCR_STATE_LOCK:
        if _TARGETED_OCR_ACTIVE_TOKEN is not None:
            raise RuntimeError("cannot reset targeted OCR while a worker is running")
        _TARGETED_OCR_CIRCUIT_OPEN = False


def _run_with_timeout(
    worker: Callable[[], Any], *, timeout_seconds: float
) -> Any:
    """Run one process-wide OCR worker without waiting on a stalled shutdown.

    Some WinRT OCR operations cannot be synchronously cancelled once entered.
    The first timeout opens a process-wide circuit so subsequent attempts fail
    closed without allocating more threads. Successful results and ordinary
    exceptions release the single worker slot for later attempts.
    """
    global _TARGETED_OCR_ACTIVE_TOKEN, _TARGETED_OCR_CIRCUIT_OPEN
    token = object()
    with _TARGETED_OCR_STATE_LOCK:
        if _TARGETED_OCR_CIRCUIT_OPEN:
            raise _TargetedOcrUnavailable(
                "targeted OCR disabled after an earlier timeout"
            )
        if _TARGETED_OCR_ACTIVE_TOKEN is not None:
            raise _TargetedOcrUnavailable("targeted OCR worker already running")
        _TARGETED_OCR_ACTIVE_TOKEN = token

    result_queue: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)
    worker_finished = threading.Event()

    def run() -> None:
        global _TARGETED_OCR_ACTIVE_TOKEN
        try:
            result = (True, worker())
        except BaseException as exc:
            result = (False, exc)
        result_queue.put_nowait(result)
        worker_finished.set()
        with _TARGETED_OCR_STATE_LOCK:
            if (
                _TARGETED_OCR_CIRCUIT_OPEN
                and _TARGETED_OCR_ACTIVE_TOKEN is token
            ):
                _TARGETED_OCR_ACTIVE_TOKEN = None

    thread = threading.Thread(
        target=run,
        name="exam-weaver-targeted-ocr",
        daemon=True,
    )
    try:
        thread.start()
    except BaseException:
        with _TARGETED_OCR_STATE_LOCK:
            if _TARGETED_OCR_ACTIVE_TOKEN is token:
                _TARGETED_OCR_ACTIVE_TOKEN = None
        raise
    try:
        succeeded, value = result_queue.get(timeout=timeout_seconds)
    except queue.Empty:
        with _TARGETED_OCR_STATE_LOCK:
            _TARGETED_OCR_CIRCUIT_OPEN = True
            if (
                worker_finished.is_set()
                and _TARGETED_OCR_ACTIVE_TOKEN is token
            ):
                _TARGETED_OCR_ACTIVE_TOKEN = None
        raise _TargetedOcrTimeout(
            f"targeted OCR exceeded {timeout_seconds:g} seconds"
        )
    with _TARGETED_OCR_STATE_LOCK:
        if _TARGETED_OCR_ACTIVE_TOKEN is token:
            _TARGETED_OCR_ACTIVE_TOKEN = None
    if not succeeded:
        raise value
    return value


@dataclass
class ImageData:
    """페이지 내 이미지 데이터"""
    path: str
    bbox: Optional[tuple] = None


@dataclass
class TableData:
    """페이지 내 텍스트 기반 표 데이터"""
    rows: List[List[str]]
    bbox: Optional[tuple] = None
    cells: List[dict] = field(default_factory=list)
    column_widths: List[float] = field(default_factory=list)
    row_heights: List[float] = field(default_factory=list)
    source: dict = field(default_factory=dict)
    confidence: dict = field(default_factory=dict)
    complexity: dict = field(default_factory=dict)


@dataclass
class OverlineData:
    """페이지 내 텍스트 위 수평선 데이터"""
    text: str
    line_text: str
    start: int
    end: int
    bbox: Optional[tuple] = None


@dataclass
class PageData:
    """페이지 데이터"""
    number: int
    text: str
    source_path: Optional[str] = None
    image_path: Optional[str] = None
    image_paths: List[str] = field(default_factory=list)
    image_infos: List[ImageData] = field(default_factory=list)
    underlined_texts: List[str] = field(default_factory=list)
    overlined_texts: List[OverlineData] = field(default_factory=list)
    tables: List[TableData] = field(default_factory=list)
    has_visual_content: bool = False
    is_ocr_text: bool = False
    structured_page: Optional[StructuredPage] = None


@dataclass
class PDFContent:
    """추출된 PDF 컨텐츠"""
    pages: List[PageData]
    manifest: Dict
    source_path: str


class PDFExtractor:
    """PDF(ZIP) 파일에서 텍스트 추출"""
    
    def __init__(self, output_dir: str = './extracted'):
        self.output_dir = Path(output_dir)

    def extract_structured_page(self, page, page_number: int) -> StructuredPage:
        """Extract one page into normalized, position-aware layout records."""
        native_page = self._extract_native_structured_page(page, page_number)
        has_embedded_images = bool(native_page.images)
        needs_ocr = (
            native_page.kind == 'image_with_fake_text_layer'
            or self._should_use_ocr_fallback(native_page.text, has_embedded_images)
        )
        if needs_ocr:
            ocr_page = self._extract_ocr_structured_page(page, page_number)
            if ocr_page.lines:
                return ocr_page
        return self._attach_native_text_decorations(native_page, page)

    def _extract_native_structured_page(self, page, page_number: int) -> StructuredPage:
        rect = getattr(page, 'rect', None)
        width = float(getattr(rect, 'width', 0) or 0)
        height = float(getattr(rect, 'height', 0) or 0)
        try:
            words = page.get_text('words') or []
        except Exception:
            words = []
        if width <= 0:
            width = max((float(word[2]) for word in words), default=1.0)
        if height <= 0:
            height = max((float(word[3]) for word in words), default=1.0)
        images = self._structured_image_bboxes(page, width, height)
        divider_x = self._native_vector_column_divider(page, width, height)
        return build_structured_page(
            words,
            page_number=page_number,
            width=width,
            height=height,
            source='native',
            images=images,
            divider_x=divider_x,
        )

    @staticmethod
    def _native_vector_column_divider(page, width: float, height: float) -> float | None:
        """Return a page-height center rule when the PDF exposes one as vector art."""

        try:
            drawings = page.get_drawings() or []
        except Exception:
            return None
        candidates: list[tuple[float, float]] = []
        for drawing in drawings:
            rect = drawing.get('rect') if isinstance(drawing, dict) else None
            if rect is None:
                continue
            try:
                x0 = float(rect.x0)
                x1 = float(rect.x1)
                y0 = float(rect.y0)
                y1 = float(rect.y1)
            except (AttributeError, TypeError, ValueError):
                continue
            rule_height = abs(y1 - y0)
            rule_width = abs(x1 - x0)
            center_x = (x0 + x1) / 2
            if (
                width * 0.44 <= center_x <= width * 0.56
                and rule_height >= height * 0.65
                and rule_width <= width * 0.01
            ):
                candidates.append((rule_height, center_x))
        if not candidates:
            return None
        return max(candidates, key=lambda item: item[0])[1]

    @staticmethod
    def _structured_image_bboxes(page, width: float, height: float) -> List[tuple]:
        try:
            embedded = page.get_images(full=True) or []
        except Exception:
            return []

        bboxes = []
        for image in embedded:
            try:
                rects = page.get_image_rects(image[0]) or []
            except Exception:
                continue
            for rect in rects:
                try:
                    bboxes.append((float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)))
                except (AttributeError, TypeError, ValueError):
                    try:
                        bboxes.append(tuple(float(value) for value in rect[:4]))
                    except (TypeError, ValueError):
                        continue
        return bboxes
    
    def extract(self, pdf_path: str) -> PDFContent:
        """
        PDF 압축 해제 및 텍스트 로드
        
        Args:
            pdf_path: PDF 파일 경로
            
        Returns:
            PDFContent: 추출된 컨텐츠
        """
        pdf_path = Path(pdf_path)
        
        # 1. Check if it's a ZIP file (original format)
        if zipfile.is_zipfile(pdf_path):
            return self._extract_zip(pdf_path)
        # 2. Check if it's a standard PDF
        elif pdf_path.suffix.lower() == '.pdf':
            return self._extract_standard_pdf(pdf_path)
        else:
            raise ValueError(f"Unsupported file format: {pdf_path}")

    def _extract_zip(self, pdf_path: Path) -> PDFContent:
        extract_dir = self.output_dir / pdf_path.stem
        extract_dir.mkdir(parents=True, exist_ok=True)
        
        # ZIP 압축 해제
        with zipfile.ZipFile(pdf_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
        
        # manifest.json 로드
        manifest_path = extract_dir / 'manifest.json'
        if not manifest_path.exists():
            return self._extract_pdf_zip(pdf_path, extract_dir)

        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
        
        # 페이지별 텍스트 로드
        pages = []
        for page_info in manifest['pages']:
            page_num = page_info['page_number']
            
            # Text path handling
            text_info = page_info.get('text')
            text = ''
            if text_info and 'path' in text_info:
                text_path = extract_dir / text_info['path']
                if text_path.exists():
                    with open(text_path, 'r', encoding='utf-8') as f:
                        text = f.read()
            
            # Image path handling
            image_paths = []
            image_infos = []
            image_path = None
            if 'image' in page_info and 'path' in page_info['image']:
                image_path = str(extract_dir / page_info['image']['path'])
                image_paths.append(image_path)
                image_infos.append(ImageData(path=image_path))
            if 'images' in page_info:
                for img in page_info['images']:
                    if isinstance(img, dict) and 'path' in img:
                        path = str(extract_dir / img['path'])
                        image_paths.append(path)
                        image_infos.append(ImageData(path=path, bbox=img.get('bbox')))
                    elif isinstance(img, str):
                        path = str(extract_dir / img)
                        image_paths.append(path)
                        image_infos.append(ImageData(path=path))
            
            pages.append(PageData(
                number=page_num,
                text=text,
                source_path=str(pdf_path),
                image_path=image_path,
                image_paths=image_paths,
                image_infos=image_infos,
                underlined_texts=[],
                overlined_texts=[
                    OverlineData(**item)
                    for item in page_info.get('overlined_texts', [])
                    if isinstance(item, dict)
                    and {'text', 'line_text', 'start', 'end'} <= set(item)
                ],
                tables=[],
                has_visual_content=page_info.get('has_visual_content', False)
            ))
        
        return PDFContent(
            pages=pages,
            manifest=manifest,
            source_path=str(pdf_path)
        )

    def _extract_pdf_zip(self, zip_path: Path, extract_dir: Path) -> PDFContent:
        pdf_files = sorted(
            path
            for path in extract_dir.rglob("*")
            if path.is_file() and path.suffix.lower() == ".pdf"
        )
        if not pdf_files:
            raise FileNotFoundError(f"No manifest.json or PDF files found in ZIP: {zip_path}")

        pages = []
        for member_pdf in pdf_files:
            content = self._extract_standard_pdf(member_pdf)
            pages.extend(content.pages)

        return PDFContent(
            pages=pages,
            manifest={
                'num_pages': len(pages),
                'type': 'pdf_zip',
                'members': [str(path.relative_to(extract_dir)) for path in pdf_files],
            },
            source_path=str(zip_path)
        )

    def _extract_standard_pdf(self, pdf_path: Path) -> PDFContent:
        reader = None
        try:
            import fitz
            fitz_doc = fitz.open(pdf_path)
        except Exception as exc:
            logging.warning("PyMuPDF image extraction unavailable; falling back to pypdf images: %s", exc)
            fitz_doc = None
            reader = pypdf.PdfReader(pdf_path)
        pages = []
        
        image_out_dir = self.output_dir / "images" / pdf_path.stem
        image_out_dir.mkdir(parents=True, exist_ok=True)
        table_image_dir = self.output_dir / "table_images" / pdf_path.stem
        table_image_dir.mkdir(parents=True, exist_ok=True)
        ocr_out_dir = self.output_dir / "ocr" / pdf_path.stem
        ocr_out_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            page_count = fitz_doc.page_count if fitz_doc is not None else len(reader.pages)
            for i in range(page_count):
                page = reader.pages[i] if reader is not None else None
                text = page.extract_text() if page is not None else ''
                text = text or ''
                image_paths = []
                image_infos = []
                underlined_texts = []
                overlined_texts = []
                tables = []
                is_ocr_text = False
                structured_page = None
                if fitz_doc is not None:
                    fitz_page = fitz_doc[i]
                    text = self._extract_positioned_text(fitz_page) or text
                    structured_page = self.extract_structured_page(fitz_page, i + 1)
                    embedded_images = fitz_page.get_images(full=True)
                    structured_ocr_text = (
                        self._structured_page_text(structured_page)
                        if structured_page.kind == 'scanned' and structured_page.lines
                        else ''
                    )
                    if structured_ocr_text or self._should_use_ocr_fallback(text, bool(embedded_images)):
                        ocr_cache_path = ocr_out_dir / f"{i + 1}.txt"
                        if structured_ocr_text:
                            ocr_text = structured_ocr_text
                        elif ocr_cache_path.exists():
                            ocr_text = ocr_cache_path.read_text(encoding='utf-8')
                        else:
                            ocr_text = self._extract_ocr_text(fitz_page)
                            if ocr_text.strip():
                                ocr_cache_path.write_text(ocr_text, encoding='utf-8')
                        if ocr_text.strip():
                            if (
                                structured_ocr_text
                                or not text.strip()
                                or len(ocr_text.strip()) > len(text.strip())
                            ):
                                text = ocr_text
                            is_ocr_text = True
                    underlined_texts = self._extract_underlined_texts(fitz_page)
                    overlined_texts = self._extract_overlined_texts(fitz_page)
                    tables = self._extract_text_tables(
                        fitz_page,
                        page_number=i + 1,
                        source_path=pdf_path,
                        table_image_dir=table_image_dir,
                    )
                    if is_ocr_text and structured_page is not None:
                        ocr_tables = self._extract_ocr_grid_tables(
                            fitz_page,
                            structured_page,
                            page_number=i + 1,
                            source_path=pdf_path,
                            table_image_dir=table_image_dir,
                        )
                        for ocr_table in ocr_tables:
                            if not any(
                                self._bbox_overlap_ratio(ocr_table.bbox, existing.bbox) >= 0.85
                                for existing in tables
                            ):
                                tables.append(ocr_table)
                    seen = {}
                    image_index = 0

                    if not is_ocr_text:
                        for image in embedded_images:
                            xref = image[0]
                            try:
                                image_width = int(image[2])
                                image_height = int(image[3])
                            except (TypeError, ValueError, IndexError):
                                image_width = 0
                                image_height = 0
                            if image_width * image_height > 6_000_000:
                                continue
                            rects = fitz_page.get_image_rects(xref)
                            if not rects:
                                continue

                            if xref not in seen:
                                extracted = fitz_doc.extract_image(xref)
                                ext = extracted.get("ext", "png")
                                image_path = image_out_dir / f"{i+1}_{image_index}_xref{xref}.{ext}"
                                image_index += 1
                                with open(image_path, "wb") as fp:
                                    fp.write(extracted["image"])
                                seen[xref] = str(image_path)

                            for rect in rects:
                                path = seen[xref]
                                image_paths.append(path)
                                image_infos.append(ImageData(
                                    path=path,
                                    bbox=(rect.x0, rect.y0, rect.x1, rect.y1)
                                ))
                else:
                    for j, image_file in enumerate(page.images):
                        image_name = f"{i+1}_{j}_{image_file.name}"
                        image_path = image_out_dir / image_name
                        
                        with open(image_path, "wb") as fp:
                            fp.write(image_file.data)
                        
                        image_paths.append(str(image_path))

                primary_image_path = image_paths[0] if image_paths else None

                pages.append(PageData(
                    number=i + 1,
                    text=text,
                    source_path=str(pdf_path),
                    image_path=primary_image_path,
                    image_paths=image_paths,
                    image_infos=image_infos,
                    underlined_texts=underlined_texts,
                    overlined_texts=overlined_texts,
                    tables=tables,
                    has_visual_content=bool(image_paths),
                    is_ocr_text=is_ocr_text,
                    structured_page=structured_page,
                ))
        finally:
            if fitz_doc is not None:
                fitz_doc.close()

        return PDFContent(
            pages=pages,
            manifest={'num_pages': len(pages), 'type': 'standard_pdf'},
            source_path=str(pdf_path)
        )

    def _extract_ocr_text(self, page) -> str:
        """OCR scanned pages with Windows OCR and rebuild two-column reading order."""
        page_number = int(getattr(page, 'number', 0) or 0) + 1
        return self._structured_page_text(self._extract_ocr_structured_page(page, page_number))

    def _extract_ocr_structured_page(self, page, page_number: int) -> StructuredPage:
        try:
            import asyncio
            return asyncio.run(self._extract_ocr_structured_page_async(page, page_number))
        except Exception:
            return self._empty_ocr_structured_page(page, page_number)

    @staticmethod
    def _empty_ocr_structured_page(page, page_number: int) -> StructuredPage:
        rect = getattr(page, 'rect', None)
        width = float(getattr(rect, 'width', 0) or 1.0)
        height = float(getattr(rect, 'height', 0) or 1.0)
        return build_structured_page(
            (),
            page_number=page_number,
            width=width,
            height=height,
            source='ocr',
            images=((0.0, 0.0, width, height),),
        )

    def _structured_page_text(self, page: StructuredPage) -> str:
        text_lines = []
        for line in page.lines:
            items = [
                {
                    'x0': word.bbox[0] * page.width,
                    'y0': word.bbox[1] * page.height,
                    'x1': word.bbox[2] * page.width,
                    'y1': word.bbox[3] * page.height,
                    'text': word.text,
                }
                for word in line.words
            ]
            text_lines.append(self._join_positioned_line(items))
        return "\n".join(line for line in text_lines if line.strip())

    @staticmethod
    def _should_use_ocr_fallback(text: str, has_embedded_images: bool) -> bool:
        """Use OCR when a page is image-backed but native text only has a header."""
        stripped = (text or '').strip()
        if not stripped:
            return True
        if not has_embedded_images:
            return False
        return len(stripped) < 250

    async def _extract_ocr_text_async(self, page) -> str:
        page_number = int(getattr(page, 'number', 0) or 0) + 1
        structured_page = await self._extract_ocr_structured_page_async(page, page_number)
        return self._structured_page_text(structured_page)

    def _structured_page_from_ocr_result(
        self,
        result,
        *,
        page_number: int,
        page_width: float,
        page_height: float,
        image_width: float,
        image_height: float,
        divider_x: Optional[float],
    ) -> StructuredPage:
        """Adapt WinRT pixel-coordinate words to normalized PDF page coordinates."""
        safe_image_width = max(float(image_width), 1.0)
        safe_image_height = max(float(image_height), 1.0)
        page_width = float(page_width) if page_width > 0 else safe_image_width
        page_height = float(page_height) if page_height > 0 else safe_image_height
        scale_x = page_width / safe_image_width
        scale_y = page_height / safe_image_height
        items = []
        for line in getattr(result, 'lines', ()) or ():
            for word in getattr(line, 'words', ()) or ():
                value = str(getattr(word, 'text', '') or '').strip()
                if not value:
                    continue
                rect = word.bounding_rect
                x0 = float(rect.x) * scale_x
                y0 = float(rect.y) * scale_y
                x1 = x0 + float(rect.width) * scale_x
                y1 = y0 + float(rect.height) * scale_y
                items.append({
                    'text': value,
                    'bbox': (x0, y0, x1, y1),
                    'confidence': getattr(word, 'confidence', None),
                })

        scaled_divider = float(divider_x) * scale_x if divider_x is not None else None
        return build_structured_page(
            items,
            page_number=page_number,
            width=page_width,
            height=page_height,
            source='ocr',
            images=((0.0, 0.0, page_width, page_height),),
            divider_x=scaled_divider,
        )

    @staticmethod
    def _ocr_page_plain_text(page: StructuredPage) -> str:
        return "\n".join(
            " ".join(str(word.text) for word in line.words)
            for line in page.lines
        )

    @classmethod
    def _ocr_page_has_english_body(cls, page: StructuredPage) -> bool:
        value = cls._ocr_page_plain_text(page)
        latin_count = len(re.findall(r"[A-Za-z]", value))
        hangul_count = len(re.findall(r"[가-힣]", value))
        return latin_count >= 80 and latin_count >= 0.45 * max(
            1, latin_count + hangul_count
        )

    @classmethod
    def _tesseract_languages_for_ocr_page(cls, page: StructuredPage) -> str:
        """Use the English model alone for English-heavy bilingual exam pages.

        Windows OCR remains the Korean/layout authority and the Tesseract result
        is merged line-by-line. Loading the Korean Tesseract model for long
        English passages substantially increases digit/letter confusions such
        as ``of`` -> ``0f`` and ``collision`` -> ``C011ision``.
        """

        return "eng" if cls._ocr_page_has_english_body(page) else "kor+eng"

    @staticmethod
    def _ocr_line_noise_score(value: str) -> int:
        """Score high-confidence OCR damage without penalizing valid formulas."""

        text = str(value or "")
        score = 0
        codes = text_quality_issue_codes(text)
        if "ocr_noise" in codes:
            score += 20
        if "broken_unit" in codes:
            score += 4
        if "unbalanced_delimiter" in codes:
            score += 6
        if has_suspicious_text_artifact(text):
            score += 12
        score += 4 * len(re.findall(r"[\ue000-\uf8ff\ufffd]", text))
        score += 3 * len(re.findall(r"[ⅰ-ⅹ]", text, re.IGNORECASE))
        score += 2 * len(re.findall(r"[{}|`^]", text))
        score += 2 * len(
            re.findall(
                r"(?<=[A-Za-z가-힣0-9])[卜入人己呑喬粼飇恤訃]"
                r"|[卜入人己呑喬粼飇恤訃](?=[A-Za-z가-힣0-9])",
                text,
            )
        )
        return score

    @classmethod
    def _ocr_page_has_repairable_noise(cls, page: StructuredPage) -> bool:
        return any(cls._ocr_line_noise_score(line.text) > 0 for line in page.lines)

    @staticmethod
    def _ocr_similarity_key(value: str) -> str:
        return re.sub(r"[^0-9A-Za-z가-힣]", "", str(value or "")).casefold()

    @staticmethod
    def _normalize_tesseract_korean_spacing(line: LayoutLine) -> str:
        """Collapse syllable-level Tesseract tokens while retaining word gaps."""

        words = list(line.words)
        korean_tokens = [
            word for word in words
            if re.fullmatch(r"[가-힣]+[,.?]?", str(word.text).strip())
        ]
        single_ratio = sum(
            len(re.sub(r"[^가-힣]", "", str(word.text))) == 1
            for word in korean_tokens
        ) / max(1, len(korean_tokens))
        if len(korean_tokens) < 4 or single_ratio < 0.45:
            return line.text

        character_widths = [
            (word.bbox[2] - word.bbox[0])
            / max(1, len(re.sub(r"[^가-힣]", "", str(word.text))))
            for word in korean_tokens
        ]
        typical_width = sorted(character_widths)[len(character_widths) // 2]
        particles = set("은는이가을를의에로와과도만서며고")
        output: list[str] = []
        previous: LayoutWord | None = None
        for word in words:
            value = str(word.text).strip()
            join = False
            if previous is not None:
                previous_text = str(previous.text).strip()
                gap = max(0.0, word.bbox[0] - previous.bbox[2])
                both_korean = bool(
                    re.fullmatch(r"[가-힣]+[,.?]?", previous_text)
                    and re.fullmatch(r"[가-힣]+[,.?]?", value)
                )
                join = both_korean and (
                    gap <= 0.75 * typical_width
                    or (
                        value[0] in particles
                        and gap <= 1.05 * typical_width
                    )
                )
            if output and not join:
                output.append(" ")
            output.append(value)
            previous = word
        return "".join(output)

    @classmethod
    def _should_prefer_tesseract_ocr_page(
        cls,
        windows_page: StructuredPage,
        tesseract_page: StructuredPage,
    ) -> bool:
        """Prefer a complete Tesseract result on English-heavy scan pages."""

        def compact_length(value: str) -> int:
            return len(re.sub(r"\s+", "", value))

        def question_count(value: str) -> int:
            return len(re.findall(r"(?m)^\s*\d{1,3}\s*[.)]", value))

        def noise_score(value: str) -> int:
            return len(
                re.findall(
                    r"[ⅰ-ⅹ]|(?<=[A-Za-z])[01](?=[A-Za-z])|"
                    r"(?<=[A-Za-z])[가-힣]|(?<=[가-힣])[A-Za-z]",
                    value,
                    re.IGNORECASE,
                )
            )

        windows_text = cls._ocr_page_plain_text(windows_page)
        tesseract_text = cls._ocr_page_plain_text(tesseract_page)
        if cls._ocr_page_has_repairable_noise(windows_page):
            # Tesseract is merged into the proven Windows line geometry.  A
            # partial English pass therefore remains safe when it measurably
            # repairs matching lines; it need not rediscover every Korean
            # question number on the page.
            merged = cls._merge_tesseract_text_into_windows_layout(
                windows_page, tesseract_page
            )
            before = sum(cls._ocr_line_noise_score(line.text) for line in windows_page.lines)
            after = sum(cls._ocr_line_noise_score(line.text) for line in merged.lines)
            if after < before:
                return True
        if compact_length(tesseract_text) < 0.72 * compact_length(windows_text):
            return False
        windows_questions = question_count(windows_text)
        if windows_questions >= 3 and question_count(tesseract_text) < 0.70 * windows_questions:
            return False
        if not cls._ocr_page_has_english_body(windows_page):
            return False
        return noise_score(tesseract_text) <= noise_score(windows_text)

    @classmethod
    def _select_preferred_ocr_page(
        cls,
        windows_page: StructuredPage,
        tesseract_page: Optional[StructuredPage],
    ) -> StructuredPage:
        if (
            tesseract_page is not None
            and cls._should_prefer_tesseract_ocr_page(windows_page, tesseract_page)
        ):
            return cls._merge_tesseract_text_into_windows_layout(
                windows_page, tesseract_page
            )
        return windows_page

    @staticmethod
    def _preserves_importable_question_coverage(
        windows_page: StructuredPage,
        candidate_page: StructuredPage,
    ) -> bool:
        """Reject prettier OCR when it loses a structurally valid question."""

        from .offline_exam import OfflineExamParser
        from .offline_quality import validate_offline_question

        def importable_numbers(page: StructuredPage) -> set[int]:
            return {
                question.number
                for question in OfflineExamParser().parse_pages([page])
                if validate_offline_question(question).importable
            }

        return importable_numbers(windows_page) <= importable_numbers(candidate_page)

    @staticmethod
    def _preserves_question_number_coverage(
        baseline_page: StructuredPage,
        candidate_page: StructuredPage,
    ) -> bool:
        """Reject an OCR cleanup that loses a visually detected question.

        The cleanup candidate is allowed to improve text that is not yet
        importable, but it must retain every question number already found on
        the baseline page.  This is stricter than comparing raw OCR line counts
        and directly protects the downstream exam-set completeness contract.
        """

        from .offline_exam import OfflineExamParser

        def question_numbers(page: StructuredPage) -> set[int]:
            return {
                question.number
                for question in OfflineExamParser().parse_pages([page])
            }

        return question_numbers(baseline_page) <= question_numbers(candidate_page)

    @classmethod
    def _should_prefer_high_contrast_ocr_page(
        cls,
        baseline_page: StructuredPage,
        high_contrast_page: StructuredPage,
    ) -> bool:
        """Choose the thresholded OCR page only after structural/text gates."""

        if not cls._preserves_question_number_coverage(
            baseline_page, high_contrast_page
        ):
            return False
        baseline_text = cls._ocr_page_plain_text(baseline_page)
        candidate_text = cls._ocr_page_plain_text(high_contrast_page)
        baseline_length = len(re.sub(r"\s+", "", baseline_text))
        candidate_length = len(re.sub(r"\s+", "", candidate_text))
        if candidate_length < 0.82 * max(1, baseline_length):
            return False
        baseline_noise = sum(
            cls._ocr_line_noise_score(line.text) for line in baseline_page.lines
        )
        candidate_noise = sum(
            cls._ocr_line_noise_score(line.text)
            for line in high_contrast_page.lines
        )
        # The page-level score is deliberately monotonic rather than requiring
        # a large percentage gain. A single repaired Hangul syllable can be the
        # difference between importing and rejecting a question, while the
        # coverage/length gates above already prevent destructive replacement.
        return candidate_noise < baseline_noise

    @classmethod
    def _merge_tesseract_text_into_windows_layout(
        cls,
        windows_page: StructuredPage,
        tesseract_page: StructuredPage,
    ) -> StructuredPage:
        """Improve English lines without changing proven Windows page structure."""

        marker = re.compile(r"^(?:\d{1,3}[.)]|[①-⑤㉦㉨㉩㉭@])$")
        ocr_marker = re.compile(
            r"^(?:\d{1,3}[.)]|[OQ@][.)]|[①-⑤㉦㉨㉩㉭@])$",
            re.IGNORECASE,
        )
        unused = set(range(len(tesseract_page.lines)))
        damaged_indexes = {
            index
            for index, line in enumerate(windows_page.lines)
            if cls._ocr_line_noise_score(line.text) > 0
        }
        merged_lines = []
        for windows_index, windows_line in enumerate(windows_page.lines):
            windows_center = (windows_line.bbox[1] + windows_line.bbox[3]) / 2
            candidates = []
            for index in unused:
                tesseract_line = tesseract_page.lines[index]
                if tesseract_line.column != windows_line.column:
                    continue
                tesseract_center = (
                    tesseract_line.bbox[1] + tesseract_line.bbox[3]
                ) / 2
                distance = abs(windows_center - tesseract_center)
                tolerance = max(
                    0.012,
                    1.4
                    * max(
                        windows_line.bbox[3] - windows_line.bbox[1],
                        tesseract_line.bbox[3] - tesseract_line.bbox[1],
                    ),
                )
                if distance <= tolerance:
                    candidates.append((distance, index, tesseract_line))
            if not candidates:
                merged_lines.append(windows_line)
                continue
            _distance, index, tesseract_line = min(candidates)
            tesseract_text = cls._normalize_tesseract_korean_spacing(tesseract_line)
            latin_count = len(re.findall(r"[A-Za-z]", tesseract_text))
            hangul_count = len(re.findall(r"[가-힣]", tesseract_text))
            windows_key = cls._ocr_similarity_key(windows_line.text)
            tesseract_key = cls._ocr_similarity_key(tesseract_text)
            similarity = SequenceMatcher(
                None, windows_key, tesseract_key, autojunk=False
            ).ratio()
            windows_noise = cls._ocr_line_noise_score(windows_line.text)
            tesseract_noise = cls._ocr_line_noise_score(tesseract_text)
            adjacent_damage = any(
                neighbor in damaged_indexes
                and windows_page.lines[neighbor].column == windows_line.column
                for neighbor in (windows_index - 1, windows_index + 1)
                if 0 <= neighbor < len(windows_page.lines)
            )
            korean_repair = (
                windows_noise > tesseract_noise and similarity >= 0.45
            ) or (
                windows_noise == 0
                and tesseract_noise == 0
                and adjacent_damage
                and similarity >= 0.90
            )
            english_candidate = (
                latin_count < 5
                or hangul_count
                or min(len(windows_key), len(tesseract_key)) < 4
                or len(tesseract_key) < 0.55 * len(windows_key)
                or similarity < 0.50
            ) is False
            english_repair = (
                english_candidate
                and windows_noise == 0
                and tesseract_noise == 0
                and adjacent_damage
                and similarity >= 0.90
            )
            if not korean_repair and not english_repair:
                merged_lines.append(windows_line)
                continue

            words = list(tesseract_line.words)
            windows_first = windows_line.words[0] if windows_line.words else None
            tesseract_first = words[0] if words else None
            if windows_first is not None and marker.match(
                str(windows_first.text).strip()
            ):
                if tesseract_first is not None and ocr_marker.match(
                    str(tesseract_first.text).strip()
                ):
                    words.pop(0)
                words.insert(0, windows_first)
            if not words:
                merged_lines.append(windows_line)
                continue
            if korean_repair:
                replacement_text = tesseract_text
                if windows_first is not None and marker.match(
                    str(windows_first.text).strip()
                ):
                    replacement_text = re.sub(
                        r"^(?:\d{1,3}[.)]|[OQ@][.)]|[①-⑤㉦㉨㉩㉭@])\s*",
                        "",
                        replacement_text,
                        count=1,
                        flags=re.IGNORECASE,
                    ).strip()
                    content_words = words[1:] if tesseract_first is not None and ocr_marker.match(
                        str(tesseract_first.text).strip()
                    ) else words
                    content_bbox = (
                        min(word.bbox[0] for word in content_words),
                        min(word.bbox[1] for word in content_words),
                        max(word.bbox[2] for word in content_words),
                        max(word.bbox[3] for word in content_words),
                    ) if content_words else windows_first.bbox
                    words = [
                        windows_first,
                        LayoutWord(
                            text=replacement_text,
                            bbox=content_bbox,
                            confidence=min(
                                (word.confidence for word in content_words if word.confidence is not None),
                                default=None,
                            ),
                            column=windows_line.column,
                        ),
                    ]
                else:
                    words = [
                        LayoutWord(
                            text=replacement_text,
                            bbox=tesseract_line.bbox,
                            confidence=min(
                                (word.confidence for word in words if word.confidence is not None),
                                default=None,
                            ),
                            column=windows_line.column,
                        )
                    ]
            words.sort(key=lambda word: word.bbox[0])
            merged_lines.append(
                LayoutLine(
                    words=tuple(words),
                    bbox=(
                        min(word.bbox[0] for word in words),
                        min(word.bbox[1] for word in words),
                        max(word.bbox[2] for word in words),
                        max(word.bbox[3] for word in words),
                    ),
                    page=windows_line.page,
                    column=windows_line.column,
                )
            )
            unused.remove(index)
        return replace(windows_page, lines=tuple(merged_lines))

    @staticmethod
    def _extract_tesseract_structured_page(
        image,
        *,
        page_number: int,
        page_width: float,
        page_height: float,
        divider_x: Optional[float],
        languages: str = "kor+eng",
    ) -> Optional[StructuredPage]:
        """Run the optional local Tesseract engine and retain word geometry."""

        executable = shutil.which("tesseract")
        if executable is None:
            fallback = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
            executable = str(fallback) if fallback.exists() else None
        tessdata = Path(__file__).resolve().parent / "tessdata"
        if (
            executable is None
            or not (tessdata / "kor.traineddata").exists()
            or not (tessdata / "eng.traineddata").exists()
        ):
            return None
        try:
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, format="PNG")
            completed = subprocess.run(
                [
                    executable,
                    "stdin",
                    "stdout",
                    "--tessdata-dir",
                    str(tessdata),
                    "-l",
                    languages,
                    "--psm",
                    "3" if divider_x is not None else "4",
                    "-c",
                    "tessedit_create_tsv=1",
                ],
                input=buffer.getvalue(),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=90,
                check=False,
                creationflags=(
                    subprocess.CREATE_NO_WINDOW
                    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW")
                    else 0
                ),
            )
            if completed.returncode != 0:
                return None
            tsv = completed.stdout.decode("utf-8", errors="ignore")
            page = PDFExtractor._structured_page_from_tesseract_tsv(
                tsv,
                page_number=page_number,
                page_width=page_width,
                page_height=page_height,
                image_width=image.width,
                image_height=image.height,
                divider_x=divider_x,
            )
            return page if page.lines else None
        except Exception:
            return None

    @staticmethod
    def _structured_page_from_tesseract_tsv(
        tsv: str,
        *,
        page_number: int,
        page_width: float,
        page_height: float,
        image_width: float,
        image_height: float,
        divider_x: Optional[float],
    ) -> StructuredPage:
        """Adapt Tesseract TSV pixel coordinates to the shared page model."""

        safe_image_width = max(float(image_width), 1.0)
        safe_image_height = max(float(image_height), 1.0)
        page_width = float(page_width) if page_width > 0 else safe_image_width
        page_height = float(page_height) if page_height > 0 else safe_image_height
        scale_x = page_width / safe_image_width
        scale_y = page_height / safe_image_height
        items = []
        for row in csv.DictReader(
            io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE
        ):
            value = str(row.get("text") or "").strip()
            if not value:
                continue
            try:
                left = float(row["left"])
                top = float(row["top"])
                width = float(row["width"])
                height = float(row["height"])
                raw_confidence = float(row.get("conf") or -1)
            except (KeyError, TypeError, ValueError):
                continue
            items.append(
                {
                    "text": value,
                    "bbox": (
                        left * scale_x,
                        top * scale_y,
                        (left + width) * scale_x,
                        (top + height) * scale_y,
                    ),
                    "confidence": (
                        raw_confidence / 100 if raw_confidence >= 0 else None
                    ),
                }
            )
        scaled_divider = float(divider_x) * scale_x if divider_x is not None else None
        return build_structured_page(
            items,
            page_number=page_number,
            width=page_width,
            height=page_height,
            source="ocr",
            images=((0.0, 0.0, page_width, page_height),),
            divider_x=scaled_divider,
        )

    async def _extract_ocr_structured_page_async(self, page, page_number: int) -> StructuredPage:
        try:
            import fitz
            from PIL import Image, ImageOps
            from winrt.windows.graphics.imaging import BitmapDecoder
            from winrt.windows.globalization import Language
            from winrt.windows.media.ocr import OcrEngine
            from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream
        except Exception:
            return self._empty_ocr_structured_page(page, page_number)

        engine = OcrEngine.try_create_from_language(Language('ko'))
        if engine is None:
            return self._empty_ocr_structured_page(page, page_number)

        rect = getattr(page, 'rect', None)
        page_width = float(getattr(rect, 'width', 0) or 0)
        page_height = float(getattr(rect, 'height', 0) or 0)
        # The legacy maritime PDFs contain small serif English passages.  At
        # the previous 3x render (roughly 216 dpi on A4) Tesseract routinely
        # confused o/0 and l/1.  A 4.2x render is close to 300 dpi.  Legacy
        # Ronpark pages are unusually tall (about 1222 PDF points), so the old
        # 4200px height cap silently reduced them to ~247dpi and broke compact
        # Hangul such as ``징수``.  The larger caps retain the intended 300dpi
        # while still bounding memory for outlier page sizes.
        zoom = 4.2
        if page_width > 0 and page_height > 0:
            zoom = min(zoom, 4200 / page_width, 6000 / page_height)
            zoom = max(0.5, zoom)

        pix = self._render_page_pixmap(
            page, matrix=fitz.Matrix(zoom, zoom), alpha=False,
        )
        image = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
        async def recognize(candidate_image):
            buffer = io.BytesIO()
            candidate_image.save(buffer, format='PNG')
            stream = InMemoryRandomAccessStream()
            writer = DataWriter(stream.get_output_stream_at(0))
            writer.write_bytes(buffer.getvalue())
            await writer.store_async()
            await writer.flush_async()
            writer.close()
            stream.seek(0)
            decoder = await BitmapDecoder.create_async(stream)
            bitmap = await decoder.get_software_bitmap_async()
            # WinRT OCR engines keep internal recognition state. Reusing one
            # instance for the raw and thresholded bitmap can make the second
            # pass echo fragments from the first. A fresh engine keeps both
            # candidates independent and deterministic.
            candidate_engine = OcrEngine.try_create_from_language(Language('ko'))
            return await candidate_engine.recognize_async(bitmap)

        result = await recognize(image)

        detected_split = self._detect_vertical_column_split(image)
        windows_page = self._structured_page_from_ocr_result(
            result,
            page_number=page_number,
            page_width=page_width,
            page_height=page_height,
            image_width=image.width,
            image_height=image.height,
            divider_x=detected_split,
        )
        # Recover the proven visual markers before replacing English text.  The
        # raw OCR prefixes (for example ``0)``/``Q)``) are otherwise liable to
        # overwrite circled choice markers during the Tesseract merge.
        windows_page = self._restore_visual_choice_markers(windows_page, image)
        used_high_contrast_windows = False

        # Old maritime scans have a light gray paper background and antialiased
        # Hangul strokes.  On those pages the raw Windows OCR result frequently
        # turns compact syllables into CJK/Latin fragments (for example
        # ``징수`` -> ``지入 / 。丁``).  A fixed high-contrast retry at the same
        # geometry recovers those strokes reliably.  It is intentionally
        # conditional and is merged line-by-line, so clean pages pay no second
        # OCR pass and question/choice marker coverage cannot regress.
        if self._ocr_page_has_repairable_noise(windows_page):
            high_contrast_image = ImageOps.grayscale(image).point(
                lambda value: 255 if value > 210 else 0
            ).convert('RGB')
            high_contrast_result = await recognize(high_contrast_image)
            high_contrast_page = self._structured_page_from_ocr_result(
                high_contrast_result,
                page_number=page_number,
                page_width=page_width,
                page_height=page_height,
                image_width=image.width,
                image_height=image.height,
                divider_x=detected_split,
            )
            high_contrast_page = self._restore_visual_choice_markers(
                # OCR text comes from the thresholded image, while marker
                # recovery keeps the grayscale/ring evidence from the original
                # render. Thin circled digits can disappear at threshold 210.
                high_contrast_page, image, targeted_recovery=False
            )
            if self._should_prefer_high_contrast_ocr_page(
                windows_page, high_contrast_page
            ):
                windows_page = high_contrast_page
                used_high_contrast_windows = True
            else:
                merged_windows_page = self._merge_tesseract_text_into_windows_layout(
                    windows_page, high_contrast_page
                )
                merged_windows_page = self._restore_visual_choice_markers(
                    merged_windows_page, image
                )
                if self._preserves_question_number_coverage(
                    windows_page, merged_windows_page
                ):
                    windows_page = merged_windows_page
        tesseract_page = None
        if (
            self._ocr_page_has_english_body(windows_page)
            or (
                not used_high_contrast_windows
                and self._ocr_page_has_repairable_noise(windows_page)
            )
        ):
            tesseract_page = self._extract_tesseract_structured_page(
                image,
                page_number=page_number,
                page_width=page_width,
                page_height=page_height,
                divider_x=detected_split,
                languages=self._tesseract_languages_for_ocr_page(windows_page),
            )
        structured_page = self._select_preferred_ocr_page(
            windows_page, tesseract_page
        )
        used_tesseract = structured_page is not windows_page
        structured_page = self._merge_false_split_column_fragments(structured_page)
        structured_page = self._restore_visual_choice_markers(structured_page, image)
        if used_tesseract:
            windows_fallback = self._merge_false_split_column_fragments(
                windows_page
            )
            windows_fallback = self._restore_visual_choice_markers(
                windows_fallback, image
            )
            if not self._preserves_importable_question_coverage(
                windows_fallback, structured_page
            ):
                structured_page = windows_fallback
        return self._attach_raster_text_decorations(structured_page, image)

    @staticmethod
    def _merge_false_split_column_fragments(page: StructuredPage) -> StructuredPage:
        """Join a one-column page accidentally split through its text block."""

        lines = list(page.lines)
        if {line.column for line in lines} != {0, 1}:
            return page
        left_body = [
            (index, line) for index, line in enumerate(lines)
            if line.column == 0 and 0.12 <= float(line.bbox[1]) <= 0.88
        ]
        right_body = [
            (index, line) for index, line in enumerate(lines)
            if line.column == 1 and 0.12 <= float(line.bbox[1]) <= 0.88
        ]
        if (
            len(right_body) < 6
            or any(_VISUAL_QUESTION_START.match(line.text) for _index, line in right_body)
        ):
            return page

        strict_matches = []
        used_left: set[int] = set()
        for right_index, right in right_body:
            candidates = sorted(
                (
                    abs(float(left.bbox[1]) - float(right.bbox[1])),
                    left_index,
                    left,
                )
                for left_index, left in left_body
                if left_index not in used_left
            )
            if not candidates:
                continue
            y_gap, left_index, left = candidates[0]
            horizontal_gap = float(right.bbox[0]) - float(left.bbox[2])
            if y_gap <= 0.004 and -0.020 <= horizontal_gap <= 0.060:
                strict_matches.append((left_index, right_index))
                used_left.add(left_index)
        if (
            len(strict_matches) < 6
            or len(strict_matches) / len(right_body) < 0.65
        ):
            return page

        matches: dict[int, int] = {}
        used_right: set[int] = set()
        for left_index, left in enumerate(lines):
            if left.column != 0:
                continue
            candidates = sorted(
                (
                    abs(float(left.bbox[1]) - float(right.bbox[1])),
                    right_index,
                )
                for right_index, right in enumerate(lines)
                if right.column == 1 and right_index not in used_right
            )
            if not candidates:
                continue
            y_gap, right_index = candidates[0]
            right = lines[right_index]
            horizontal_gap = float(right.bbox[0]) - float(left.bbox[2])
            if y_gap <= 0.004 and -0.020 <= horizontal_gap <= 0.180:
                matches[left_index] = right_index
                used_right.add(right_index)

        rewritten = []
        consumed_right = set(matches.values())
        for index, line in enumerate(lines):
            if index in consumed_right:
                continue
            right_index = matches.get(index)
            if right_index is None:
                rewritten.append(line)
                continue
            right = lines[right_index]
            words = tuple(sorted(
                (
                    replace(word, column=0) if word.column != 0 else word
                    for word in (*line.words, *right.words)
                ),
                key=lambda word: word.bbox[0],
            ))
            rewritten.append(LayoutLine(
                words,
                (
                    min(float(line.bbox[0]), float(right.bbox[0])),
                    min(float(line.bbox[1]), float(right.bbox[1])),
                    max(float(line.bbox[2]), float(right.bbox[2])),
                    max(float(line.bbox[3]), float(right.bbox[3])),
                ),
                line.page,
                0,
            ))
        return replace(page, lines=tuple(rewritten))

    @staticmethod
    def _render_page_pixmap(page, *, matrix, alpha=False):
        """Render while keeping recoverable MuPDF diagnostics out of callbacks."""
        import fitz

        with _MUPDF_RENDER_LOCK:
            display_errors = bool(fitz.TOOLS.mupdf_display_errors())
            display_warnings = bool(fitz.TOOLS.mupdf_display_warnings())
            try:
                fitz.TOOLS.mupdf_display_errors(False)
                fitz.TOOLS.mupdf_display_warnings(False)
                return page.get_pixmap(matrix=matrix, alpha=alpha)
            finally:
                fitz.TOOLS.mupdf_display_errors(display_errors)
                fitz.TOOLS.mupdf_display_warnings(display_warnings)

    def _restore_visual_choice_markers(
        self,
        page: StructuredPage,
        image,
        *,
        targeted_recovery: bool = True,
    ) -> StructuredPage:
        """Restore a complete ①-④ layout only with raster ring evidence."""
        gray = image.convert("L")
        lines = list(page.lines)
        replacements: dict[int, list[tuple[str, int, float, bool]]] = {}
        recovered_cells: dict[int, list[tuple[str, float, float, bool]]] = {}
        columns = sorted({line.column for line in lines})

        for column in columns:
            indexes = [index for index, line in enumerate(lines) if line.column == column]
            raw_starts = [
                position
                for position, index in enumerate(indexes)
                if _VISUAL_QUESTION_START.match(lines[index].text)
            ]
            embedded_starts = {
                position
                for position, index in enumerate(indexes)
                if _VISUAL_EMBEDDED_QUESTION_START.match(lines[index].text)
            }
            if not raw_starts:
                continue
            first_missing_starts = set()
            first_match = _VISUAL_LEADING_NUMBER.match(
                lines[indexes[raw_starts[0]]].text
            )
            if first_match is not None and int(first_match.group(1)) == 2:
                first_lead = next((
                    position
                    for position in range(raw_starts[0])
                    if _VISUAL_QUESTION_LEAD.match(lines[indexes[position]].text)
                ), None)
                if first_lead is not None:
                    first_missing_starts.add(first_lead)
            question_gutter = min(
                float(lines[indexes[position]].words[0].bbox[0])
                for position in raw_starts
                if lines[indexes[position]].words
            )
            hanging_starts = {
                position
                for position in range(len(indexes) - 1)
                if _VISUAL_QUESTION_LEAD.match(lines[indexes[position]].text)
                and _VISUAL_HANGING_NUMBER.match(lines[indexes[position + 1]].text)
                and lines[indexes[position + 1]].words
                and float(lines[indexes[position + 1]].words[0].bbox[0])
                <= question_gutter + 0.020
            }
            effective_raw_starts = (
                set(raw_starts) | embedded_starts | first_missing_starts
            )
            for position in tuple(raw_starts):
                if (
                    position + 1 < len(indexes)
                    and not _VISUAL_QUESTION_LEAD.match(lines[indexes[position]].text)
                    and _VISUAL_QUESTION_LEAD.match(lines[indexes[position + 1]].text)
                ):
                    effective_raw_starts.discard(position)
                    hanging_starts.add(position + 1)
                    continue
                if not _VISUAL_NUMBERED_CHOICE.match(lines[indexes[position]].text):
                    continue
                previous_start = max(
                    (prior for prior in raw_starts if prior < position),
                    default=-1,
                )
                lead_position = next((
                    candidate
                    for candidate in range(position - 1, previous_start, -1)
                    if _VISUAL_QUESTION_LEAD.match(lines[indexes[candidate]].text)
                ), None)
                if lead_position is not None:
                    effective_raw_starts.discard(position)
                    hanging_starts.add(lead_position)
            semantic_starts = set()
            trusted_leading = (
                set(_VISUAL_EXPLICIT_MARKERS)
                | set(_VISUAL_DAMAGED_MARKERS)
                | {"@", "O", "1", "2", "3", "4", "5"}
            )
            for position in range(len(indexes)):
                if not _VISUAL_QUESTION_LEAD.match(lines[indexes[position]].text):
                    continue
                candidate_line = lines[indexes[position]]
                if candidate_line.words:
                    word_x = float(candidate_line.words[0].bbox[0])
                    ring_positions = [
                        word_x + delta
                        for delta in (-0.004, -0.002, 0.0, 0.002, 0.004)
                    ]
                    ring_positions.extend(
                        word_x - delta for delta in (0.025, 0.027, 0.029, 0.031)
                    )
                    if any(
                        self._has_visual_marker_ring(
                            gray, marker_x, candidate_line.bbox
                        )
                        for marker_x in ring_positions
                    ):
                        continue
                prior = max(
                    (
                        candidate
                        for candidate in effective_raw_starts | hanging_starts | semantic_starts
                        if candidate < position
                    ),
                    default=-1,
                )
                evidence_lines = sum(
                    any(
                        str(word.text).strip()[:1] in trusted_leading
                        for word in lines[indexes[candidate]].words
                    )
                    for candidate in range(prior + 1, position)
                )
                if evidence_lines >= 2:
                    semantic_starts.add(position)
            starts = [
                position for position in sorted(
                    effective_raw_starts | hanging_starts | semantic_starts
                )
                if position in hanging_starts or position in embedded_starts
                or position in semantic_starts or position in first_missing_starts
                or (
                    lines[indexes[position]].words
                    and float(lines[indexes[position]].words[0].bbox[0])
                    <= question_gutter + 0.020
                )
            ]
            for start_offset, start_position in enumerate(starts):
                end_position = starts[start_offset + 1] if start_offset + 1 < len(starts) else len(indexes)
                region_indexes = indexes[start_position:end_position]
                if self._complete_explicit_visual_sequence(lines, region_indexes):
                    continue
                anchors = self._visual_ring_anchors(gray, lines, region_indexes[1:])
                selected = self._select_complete_visual_choice_layout(lines, anchors)
                if selected is None:
                    selected = self._recover_compact_inline_visual_layout(
                        gray, lines, region_indexes[1:]
                    )
                if selected is None:
                    continue
                recovered = self._recover_empty_visual_grid_cell(gray, lines, selected)
                if recovered is not None:
                    recovered_index, recovered_text, marker_x, cell_end_x = recovered
                    recovered_cells.setdefault(recovered_index, []).append((
                        recovered_text, marker_x, cell_end_x, False
                    ))
                for recovered in self._recover_empty_vertical_table_cells(
                    gray, lines, selected
                ):
                    (
                        recovered_index, recovered_text, marker_x,
                        cell_end_x, replace_existing,
                    ) = recovered
                    recovered_cells.setdefault(recovered_index, []).append((
                        recovered_text, marker_x, cell_end_x, replace_existing
                    ))
                for choice_number, (index, marker_x, word_index, existing, known) in enumerate(selected, start=1):
                    if known is not None and known != choice_number:
                        break
                    replacements.setdefault(index, []).append((
                        _VISUAL_CHOICE_SYMBOLS[choice_number - 1],
                        word_index,
                        marker_x,
                        existing,
                    ))
                else:
                    continue
                for index, *_ in selected:
                    replacements.pop(index, None)
                    recovered_cells.pop(index, None)

        # Garbled question terminators can make the semantic-start pass split
        # a valid choice region before it reaches the ring selector.  Recheck
        # only consecutive numbered questions anchored at the page gutter;
        # numeric-looking choice rows are indented and therefore excluded.
        for column in columns:
            indexes = [
                index for index, line in enumerate(lines)
                if line.column == column
            ]
            numbered_positions = [
                position for position, index in enumerate(indexes)
                if _VISUAL_QUESTION_START.match(lines[index].text)
                and lines[index].words
            ]
            if not numbered_positions:
                continue
            question_gutter = min(
                float(lines[indexes[position]].words[0].bbox[0])
                for position in numbered_positions
            )
            question_positions = [
                position for position in numbered_positions
                if float(lines[indexes[position]].words[0].bbox[0])
                <= question_gutter + 0.020
            ]
            for offset, start_position in enumerate(question_positions):
                end_position = (
                    question_positions[offset + 1]
                    if offset + 1 < len(question_positions)
                    else len(indexes)
                )
                region_indexes = indexes[start_position:end_position]
                anchors = self._visual_ring_anchors(
                    gray, lines, region_indexes[1:]
                )
                selected = self._select_complete_visual_choice_layout(
                    lines, anchors
                )
                if selected is None:
                    continue
                conflicting_indexes = {
                    index for index in region_indexes if index in replacements
                }
                if conflicting_indexes:
                    if (
                        len({index for index, *_ in selected}) == 4
                        and len(conflicting_indexes) < 4
                    ):
                        for index in conflicting_indexes:
                            replacements.pop(index, None)
                            recovered_cells.pop(index, None)
                    else:
                        continue
                if any(
                    known is not None and known != choice_number
                    for choice_number, (*_prefix, known) in enumerate(
                        selected, start=1
                    )
                ):
                    continue
                recovered = self._recover_empty_visual_grid_cell(
                    gray, lines, selected
                )
                if recovered is not None:
                    recovered_index, recovered_text, marker_x, cell_end_x = recovered
                    recovered_cells.setdefault(recovered_index, []).append((
                        recovered_text, marker_x, cell_end_x, False
                    ))
                for recovered in self._recover_empty_vertical_table_cells(
                    gray, lines, selected
                ):
                    (
                        recovered_index, recovered_text, marker_x,
                        cell_end_x, replace_existing,
                    ) = recovered
                    recovered_cells.setdefault(recovered_index, []).append((
                        recovered_text, marker_x, cell_end_x, replace_existing
                    ))
                for choice_number, (
                    index, marker_x, word_index, existing, _known
                ) in enumerate(selected, start=1):
                    replacements.setdefault(index, []).append((
                        _VISUAL_CHOICE_SYMBOLS[choice_number - 1],
                        word_index,
                        marker_x,
                        existing,
                    ))

        if replacements:
            for index, operations in replacements.items():
                lines[index] = self._line_with_visual_markers(lines[index], operations)
                if index in recovered_cells:
                    for (
                        text_value, marker_x, cell_end_x, replace_existing
                    ) in recovered_cells[index]:
                        lines[index] = self._line_with_recovered_choice_text(
                            lines[index], text_value, marker_x, cell_end_x,
                            replace_existing=replace_existing,
                        )
            page = replace(page, lines=tuple(lines))
        if not targeted_recovery:
            return self._mark_raster_underlined_choice_words(page, gray)
        page = self._recover_targeted_ton_hour_rows(page, gray)
        page = self._recover_targeted_three_field_rows(page, gray)
        page = self._recover_targeted_percentage_rows(page, gray)
        page = self._recover_targeted_percentage_length_rows(page, gray)
        page = self._recover_targeted_year_pairs(page, gray)
        page = self._recover_targeted_training_rows(page, gray)
        page = self._recover_raster_verified_vertical_sequence(page, gray)
        page = self._recover_same_page_glyph_mapping(page, gray)
        page = self._recover_separated_glyph_mapping(page, gray)
        page = self._recover_legacy_proposition_sequence_grid(page, gray)
        page = self._recover_missing_proposition_combination_row(page, gray)
        page = self._recover_legacy_abc_choice_rows(page, gray)
        page = self._recover_indented_duplicate_grid_cell(page, gray)
        page = self._recover_missing_legacy_two_by_two_cell(page, gray)
        for _attempt in range(4):
            recovered_page = self._recover_empty_marked_grid_cell(page, gray)
            if recovered_page is page:
                break
            page = recovered_page
        for _attempt in range(4):
            recovered_page = self._recover_sparse_raster_choice_region(page, gray)
            if recovered_page is page:
                break
            page = recovered_page
        return self._mark_raster_underlined_choice_words(page, gray)

    @classmethod
    def _recover_empty_marked_grid_cell(cls, page, gray):
        """Fill one OCR-empty cell after a ①-④ raster grid was restored."""

        lines = list(page.lines)
        by_column: dict[int, list[int]] = {}
        for index, line in enumerate(lines):
            by_column.setdefault(line.column, []).append(index)
        for indexes in by_column.values():
            indexes.sort(key=lambda index: float(lines[index].bbox[1]))
            for upper_index, lower_index in zip(indexes, indexes[1:]):
                selected = []
                numbers = []
                for index in (upper_index, lower_index):
                    for word_index, word in enumerate(lines[index].words):
                        text = str(word.text).strip()
                        if (
                            getattr(word, "visual_choice_marker", False)
                            and text[:1] in _VISUAL_EXPLICIT_MARKERS
                        ):
                            number = _VISUAL_EXPLICIT_MARKERS[text[:1]]
                            numbers.append(number)
                            selected.append((
                                index,
                                float(word.bbox[0]),
                                word_index,
                                True,
                                number,
                            ))
                if numbers != [1, 2, 3, 4]:
                    continue
                recovered = cls._recover_empty_visual_grid_cell(
                    gray, lines, selected, trust_selected=True
                )
                if recovered is None:
                    continue
                index, value, marker_x, cell_end_x = recovered
                lines[index] = cls._line_with_recovered_choice_text(
                    lines[index], value, marker_x, cell_end_x
                )
                return replace(page, lines=tuple(lines))
        return page

    @classmethod
    def _recover_sparse_raster_choice_region(cls, page, gray):
        """Re-OCR a narrow answer band when page OCR retained fewer than four choices."""

        lines = list(page.lines)
        changed = False
        try:
            from .offline_exam import OfflineExamParser
            from .offline_quality import validate_offline_question

            healthy_numbers = {
                question.number
                for question in OfflineExamParser().parse_pages([page])
                if validate_offline_question(question).importable
            }
        except Exception:
            healthy_numbers = set()
        for column in sorted({line.column for line in lines}):
            indexes = sorted(
                (index for index, line in enumerate(lines) if line.column == column),
                key=lambda index: float(lines[index].bbox[1]),
            )
            starts = [
                position
                for position, index in enumerate(indexes)
                if _VISUAL_QUESTION_START.match(lines[index].text)
            ]
            for offset, start in enumerate(starts):
                end = starts[offset + 1] if offset + 1 < len(starts) else len(indexes)
                region_indexes = indexes[start:end]
                if len(region_indexes) < 2:
                    continue
                leading_number = _VISUAL_LEADING_NUMBER.match(
                    lines[region_indexes[0]].text
                )
                if (
                    leading_number is not None
                    and int(leading_number.group(1)) in healthy_numbers
                ):
                    continue
                region = [lines[index] for index in region_indexes]
                # This expensive fallback is intentionally Korean-only.  Applying
                # it to damaged maritime-English rows can turn partial English OCR
                # into plausible but unrelated Korean choices and drop the source
                # question at the quality gate.
                if len(re.findall(r"[가-힣]", " ".join(line.text for line in region))) < 4:
                    continue
                existing_numbers = [
                    _VISUAL_EXPLICIT_MARKERS[text[:1]]
                    for line in region[1:]
                    for word in line.words
                    if (text := str(word.text).strip())[:1] in _VISUAL_EXPLICIT_MARKERS
                ]
                if existing_numbers == [1, 2, 3, 4]:
                    continue
                terminator = next(
                    (
                        position
                        for position, line in enumerate(region)
                        if re.search(r"[?？]", line.text)
                        or _VISUAL_QUESTION_TERMINATOR.search(line.text)
                    ),
                    None,
                )
                if terminator is None:
                    continue
                tail_indexes = region_indexes[terminator + 1:]
                if not tail_indexes:
                    continue
                marker_indexes = []
                for index in tail_indexes:
                    markerish = any(
                        getattr(word, "visual_choice_marker", False)
                        or str(word.text).strip()[:1]
                        in (set(_VISUAL_EXPLICIT_MARKERS) | set(_VISUAL_DAMAGED_MARKERS) | {"年"})
                        or re.fullmatch(r"\(?[0-4OQ]\)?[.)]?", str(word.text).strip())
                        for word in lines[index].words
                    )
                    if markerish:
                        marker_indexes.append(index)

                next_y = (
                    float(lines[indexes[starts[offset + 1]]].bbox[1])
                    if offset + 1 < len(starts)
                    else 0.940
                )
                if marker_indexes:
                    crop_y0 = max(
                        float(region[terminator].bbox[3]),
                        min(float(lines[index].bbox[1]) for index in marker_indexes) - 0.025,
                    )
                    crop_y1 = min(
                        next_y - 0.004,
                        max(
                            (
                                float(lines[index].bbox[1])
                                + float(lines[index].bbox[3])
                            )
                            / 2
                            + 0.012
                            for index in marker_indexes
                        ),
                        0.936,
                    )
                else:
                    last = lines[tail_indexes[-1]]
                    gap = next_y - float(last.bbox[3])
                    if not 0.010 <= gap <= 0.120:
                        continue
                    crop_y0 = max(
                        float(region[terminator].bbox[3]),
                        float(last.bbox[3]) - 0.004,
                    )
                    crop_y1 = next_y - 0.004
                if not 0.018 <= crop_y1 - crop_y0 <= 0.140:
                    continue

                column_left = min(float(line.bbox[0]) for line in region)
                column_right = max(float(line.bbox[2]) for line in region)
                crop_x0 = max(0.0, column_left - 0.020)
                crop_x1 = min(1.0, column_right + 0.025)
                width, height = gray.size
                crop = gray.crop((
                    int(crop_x0 * width),
                    int(crop_y0 * height),
                    int(crop_x1 * width),
                    int(crop_y1 * height),
                ))
                choices = cls._targeted_korean_choice_values(crop)
                if choices is None:
                    continue

                removable = {
                    index
                    for index in tail_indexes
                    if float(lines[index].bbox[1]) >= crop_y0 - 0.004
                }
                insert_at = min(removable, default=region_indexes[-1] + 1)
                kept = [line for index, line in enumerate(lines) if index not in removable]
                insert_at -= sum(index < insert_at for index in removable)
                marker_x = crop_x0 + 0.010
                row_height = min(0.016, max(0.010, (crop_y1 - crop_y0) / 5))
                recovered_lines = []
                for choice_number, choice in enumerate(choices, start=1):
                    y = crop_y0 + choice_number * min(0.002, row_height / 6)
                    marker = LayoutWord(
                        _VISUAL_CHOICE_SYMBOLS[choice_number - 1],
                        (marker_x, y, marker_x + 0.018, y + row_height),
                        0.90,
                        column,
                        True,
                    )
                    content = LayoutWord(
                        choice,
                        (marker_x + 0.024, y, crop_x1, y + row_height),
                        0.85,
                        column,
                    )
                    recovered_lines.append(LayoutLine(
                        (marker, content),
                        (marker_x, y, crop_x1, y + row_height),
                        page.number,
                        column,
                    ))
                kept[insert_at:insert_at] = recovered_lines
                lines = kept
                changed = True
                break
        return replace(page, lines=tuple(lines)) if changed else page

    @classmethod
    def _recover_missing_legacy_two_by_two_cell(cls, page, gray):
        """Re-OCR one empty fourth cell in a legacy two-by-two choice grid.

        Old Ronpark scans can retain the first/third/fourth OCR markers while
        dropping the second marker and the entire fourth choice text.  The two
        aligned row gaps prove the grid; the peer row supplies a safe crop end.
        """

        lines = list(page.lines)
        legacy_prefix = re.compile(r"^\([^\s)]{1,2}\)?$")
        fourth_marker = re.compile(r"^(?:④|4\))$")

        def split_at_grid_gap(line):
            ordered = sorted(line.words, key=lambda word: word.bbox[0])
            if len(ordered) < 4:
                return None
            gaps = [
                float(ordered[index].bbox[0])
                - float(ordered[index - 1].bbox[2])
                for index in range(1, len(ordered))
            ]
            split_index = max(
                range(1, len(ordered)), key=lambda index: gaps[index - 1]
            )
            if gaps[split_index - 1] < 0.075:
                return None
            return ordered[:split_index], ordered[split_index:]

        for first_index in range(len(lines) - 1):
            first, second = lines[first_index], lines[first_index + 1]
            if first.column != second.column or first.page != second.page:
                continue
            row_gap = float(second.bbox[1]) - float(first.bbox[1])
            if not 0.010 <= row_gap <= 0.060:
                continue
            first_cells = split_at_grid_gap(first)
            second_cells = split_at_grid_gap(second)
            if first_cells is None or second_cells is None:
                continue
            first_left, first_right = first_cells
            second_left, second_right = second_cells
            if not first_left or not first_right or not second_left:
                continue
            if not legacy_prefix.fullmatch(str(first_left[0].text).strip()):
                continue
            if not legacy_prefix.fullmatch(str(second_left[0].text).strip()):
                continue
            if len(first_left) < 3 or len(first_right) < 2 or len(second_left) < 3:
                continue
            if len(second_right) != 1:
                continue
            marker = second_right[0]
            if not fourth_marker.fullmatch(str(marker.text).strip()):
                continue
            peer_column_x = float(first_right[0].bbox[0])
            marker_x = float(marker.bbox[0])
            if abs(peer_column_x - marker_x) > 0.045:
                continue

            cell_end_x = min(
                0.995,
                max(float(first.bbox[2]), marker_x + 0.10) + 0.012,
            )
            width, height = gray.size
            crop = gray.crop((
                max(0, int((float(marker.bbox[2]) - 0.005) * width)),
                max(0, int((float(second.bbox[1]) - 0.006) * height)),
                min(width, int(cell_end_x * width)),
                min(height, int((float(second.bbox[3]) + 0.008) * height)),
            ))
            recovered = cls._targeted_english_choice_crop_text(crop) or ""
            recovered = re.sub(
                r"^\s*(?:(?:[①-④]|[1-4])[.)]?|[.)])\s*", "", recovered
            ).strip(" .)")
            recovered = re.sub(r"[-‐‑‒–—―¯]+", "-", recovered)
            if len(re.sub(r"[^0-9A-Za-z]", "", recovered)) < 3:
                continue
            lines[first_index + 1] = cls._line_with_recovered_choice_text(
                second,
                recovered,
                marker_x,
                cell_end_x,
            )
            return replace(page, lines=tuple(lines))
        return page

    @classmethod
    def _recover_indented_duplicate_grid_cell(cls, page, gray):
        """Re-OCR one visibly indented cell when it duplicates another choice."""

        lines = list(page.lines)
        for first_index in range(len(lines) - 1):
            pair = (lines[first_index], lines[first_index + 1])
            if pair[0].column != pair[1].column:
                continue
            cells = []
            marker_numbers = []
            for line_index, line in zip((first_index, first_index + 1), pair):
                ordered = sorted(line.words, key=lambda word: word.bbox[0])
                marker_positions = [
                    index for index, word in enumerate(ordered)
                    if getattr(word, "visual_choice_marker", False)
                    and str(word.text).strip()[:1] in _VISUAL_EXPLICIT_MARKERS
                ]
                if len(marker_positions) != 2:
                    break
                for offset, marker_position in enumerate(marker_positions):
                    marker = ordered[marker_position]
                    number = _VISUAL_EXPLICIT_MARKERS[str(marker.text).strip()[:1]]
                    marker_numbers.append(number)
                    end_position = (
                        marker_positions[offset + 1]
                        if offset + 1 < len(marker_positions)
                        else len(ordered)
                    )
                    content = [
                        word for word in ordered[marker_position + 1:end_position]
                        if not getattr(word, "visual_choice_marker", False)
                    ]
                    if not content:
                        break
                    cells.append((line_index, line, marker, content))
            if marker_numbers != [1, 2, 3, 4] or len(cells) != 4:
                continue
            texts = [" ".join(str(word.text).strip() for word in cell[3]) for cell in cells]
            normalized = [re.sub(r"\s+", "", text).casefold() for text in texts]
            duplicate_keys = {key for key in normalized if normalized.count(key) == 2}
            if len(duplicate_keys) != 1:
                continue
            duplicate_indexes = [
                index for index, key in enumerate(normalized)
                if key in duplicate_keys
            ]
            gaps = [
                float(cells[index][3][0].bbox[0]) - float(cells[index][2].bbox[2])
                for index in duplicate_indexes
            ]
            suspect_offset = max(range(2), key=lambda offset: gaps[offset])
            other_offset = 1 - suspect_offset
            if gaps[suspect_offset] < 0.045 or gaps[other_offset] > 0.030:
                continue
            suspect_index = duplicate_indexes[suspect_offset]
            line_index, line, marker, _content = cells[suspect_index]
            peer_spans = [
                float(cell[3][-1].bbox[2]) - float(cell[2].bbox[0])
                for index, cell in enumerate(cells)
                if index != suspect_index
            ]
            cell_end_x = min(
                0.995,
                float(marker.bbox[0]) + max(peer_spans, default=0.12) + 0.020,
            )
            width, height = gray.size
            crop = gray.crop((
                max(0, int((float(marker.bbox[0]) - 0.005) * width)),
                max(0, int((float(line.bbox[1]) - 0.004) * height)),
                min(width, int(cell_end_x * width)),
                min(height, int((float(line.bbox[3]) + 0.008) * height)),
            ))
            recovered = cls._targeted_english_choice_crop_text(crop) or ""
            recovered = re.sub(
                r"^\s*(?:[①-④]|[1-4][.)]?|[@O0])\s*", "", recovered
            ).strip(" .")
            recovered_key = re.sub(r"\s+", "", recovered).casefold()
            if (
                len(recovered_key) <= len(normalized[suspect_index])
                or recovered_key == normalized[suspect_index]
                or not recovered_key.endswith(normalized[suspect_index])
            ):
                continue
            lines[line_index] = cls._line_with_recovered_choice_text(
                line,
                recovered,
                float(marker.bbox[0]),
                cell_end_x,
                replace_existing=True,
            )
            return replace(page, lines=tuple(lines))
        return page

    @staticmethod
    def _targeted_english_choice_crop_text(crop) -> str | None:
        """Use an installed English OCR engine for one ambiguous tiny cell."""

        executable = shutil.which("tesseract")
        if executable is None:
            fallback = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
            executable = str(fallback) if fallback.exists() else None
        if executable is None:
            return None
        try:
            from PIL import Image, ImageEnhance, ImageOps

            enlarged = crop.resize(
                (max(1, crop.width * 4), max(1, crop.height * 4)),
                Image.Resampling.LANCZOS,
            )
            contrasted = ImageOps.autocontrast(enlarged)
            variants = (
                ImageEnhance.Sharpness(contrasted).enhance(2.5),
                contrasted,
            )
            values = []
            for variant in variants:
                buffer = io.BytesIO()
                variant.convert("RGB").save(buffer, format="PNG")
                completed = subprocess.run(
                    [executable, "stdin", "stdout", "-l", "eng", "--psm", "7"],
                    input=buffer.getvalue(),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    timeout=20,
                    check=False,
                    creationflags=(
                        subprocess.CREATE_NO_WINDOW
                        if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW")
                        else 0
                    ),
                )
                value = completed.stdout.decode("utf-8", errors="ignore").strip()
                if value:
                    values.append(value)
            if not values:
                return None
            return min(values, key=lambda value: (len(value.splitlines()), -len(value)))
        except Exception:
            return None

    @staticmethod
    def _mark_raster_underlined_choice_words(page, gray):
        """Annotate OCR words backed by a real horizontal underline."""

        if "밑줄" not in page.text:
            return page
        gray = gray.convert("L")
        width, height = gray.size
        pixels = gray.load()
        allowed_indexes: set[int] = set()
        for column in sorted({line.column for line in page.lines}):
            indexes = sorted(
                (index for index, line in enumerate(page.lines) if line.column == column),
                key=lambda index: float(page.lines[index].bbox[1]),
            )
            underline_prompt = False
            prompt_finished = False
            for index in indexes:
                text = page.lines[index].text
                if _VISUAL_QUESTION_START.match(text):
                    underline_prompt = False
                    prompt_finished = False
                if "밑줄" in text:
                    underline_prompt = True
                if underline_prompt and re.search(r"[?？]", text):
                    prompt_finished = True
                    continue
                if underline_prompt and prompt_finished:
                    allowed_indexes.add(index)
        changed = False
        rewritten_lines = []
        for line_index, line in enumerate(page.lines):
            rewritten_words = []
            for word in line.words:
                text = str(word.text).strip()
                x0 = float(word.bbox[0])
                x1 = float(word.bbox[2])
                fused_marker = bool(re.match(r"^[0O④][A-Za-z]", text))
                if fused_marker:
                    x0 += (x1 - x0) * 0.30
                left = max(0, min(width - 1, int(x0 * width)))
                right = max(left + 1, min(width, int(x1 * width)))
                top = max(0, min(height - 1, int((float(word.bbox[3]) - 0.004) * height)))
                bottom = max(top + 1, min(height, int((float(word.bbox[3]) + 0.012) * height)))
                marked = False
                if (
                    line_index in allowed_indexes
                    and not re.fullmatch(r"[①-⑤㉠-㉭]", text)
                ):
                    center = (left + right) // 2
                    for y in range(top, bottom):
                        density = (
                            sum(pixels[x, y] < 180 for x in range(left, right))
                            / max(1, right - left)
                        )
                        minimum_density = 0.72 if fused_marker else 0.95
                        if density < minimum_density or pixels[center, y] >= 180:
                            continue
                        run_left = center
                        while run_left > 0 and pixels[run_left - 1, y] < 180:
                            run_left -= 1
                        run_right = center
                        while run_right + 1 < width and pixels[run_right + 1, y] < 180:
                            run_right += 1
                        if (run_right - run_left + 1) / width < 0.25:
                            marked = True
                            break
                if marked != getattr(word, "underlined_choice_word", False):
                    word = replace(word, underlined_choice_word=marked)
                    changed = True
                rewritten_words.append(word)
            rewritten_lines.append(
                replace(line, words=tuple(rewritten_words))
                if tuple(rewritten_words) != line.words
                else line
            )
        return replace(page, lines=tuple(rewritten_lines)) if changed else page

    @classmethod
    def _recover_missing_proposition_combination_row(cls, page, gray):
        """Restore one raster-only row in a four-choice proposition block."""

        lines = list(page.lines)
        proposition_pattern = re.compile(r"[㉠-㉥]")
        by_column: dict[int, list[tuple[int, tuple[str, str]]]] = {}
        for index, line in enumerate(lines):
            symbols = tuple(proposition_pattern.findall(line.text))
            if len(symbols) == 2:
                by_column.setdefault(line.column, []).append(
                    (index, (symbols[0], symbols[1]))
                )

        for column, candidates in by_column.items():
            for offset in range(len(candidates) - 2):
                triple = candidates[offset:offset + 3]
                indexes = [item[0] for item in triple]
                rows = [lines[index] for index in indexes]
                if any(row.column != column for row in rows):
                    continue
                y_values = [float(row.bbox[1]) for row in rows]
                gaps = [right - left for left, right in zip(y_values, y_values[1:])]
                small_gap, large_gap = min(gaps), max(gaps)
                if (
                    not 0.012 <= small_gap <= 0.045
                    or not 1.60 * small_gap <= large_gap <= 2.45 * small_gap
                ):
                    continue

                prior_symbols = {
                    symbol
                    for line in lines[:indexes[0]]
                    if line.column == column
                    for symbol in proposition_pattern.findall(line.text)
                    if len(line.text) >= 8
                }
                if len(prior_symbols) < 4:
                    continue

                missing_position = 1 if gaps[0] == large_gap else 2
                missing_y = y_values[missing_position - 1] + small_gap
                width, height = gray.size
                marker_x = min(float(row.bbox[0]) for row in rows)
                content_end_x = max(float(row.bbox[2]) for row in rows)
                crop = gray.crop((
                    max(0, int((marker_x - 0.015) * width)),
                    max(0, int((missing_y - 0.012) * height)),
                    min(width, int((content_end_x + 0.080) * width)),
                    min(height, int((missing_y + 0.030) * height)),
                ))
                recovered_text = cls._targeted_choice_crop_text(crop) or ""
                recovered_symbols = tuple(
                    proposition_pattern.findall(recovered_text)
                )
                if len(recovered_symbols) != 2:
                    continue

                values = [item[1] for item in triple]
                values.insert(
                    missing_position,
                    (recovered_symbols[0], recovered_symbols[1]),
                )
                row_specs = [
                    (y_values[0] + small_gap * choice_offset, value)
                    for choice_offset, value in enumerate(values)
                ]
                rewritten = []
                row_height = max(
                    0.010,
                    sum(float(row.bbox[3]) - float(row.bbox[1]) for row in rows)
                    / len(rows),
                )
                for choice_number, (y, value) in enumerate(row_specs, start=1):
                    marker = LayoutWord(
                        _VISUAL_CHOICE_SYMBOLS[choice_number - 1],
                        (marker_x, y, marker_x + 0.018, y + row_height),
                        1.0, column, True,
                    )
                    content = LayoutWord(
                        f"{value[0]}, {value[1]}",
                        (marker_x + 0.028, y, content_end_x, y + row_height),
                        0.90, column,
                    )
                    rewritten.append(LayoutLine(
                        (marker, content),
                        (marker_x, y, content_end_x, y + row_height),
                        rows[0].page, column,
                    ))

                removed = set(indexes)
                insert_at = min(indexes)
                kept = [line for index, line in enumerate(lines) if index not in removed]
                kept[insert_at:insert_at] = rewritten
                return replace(page, lines=tuple(kept))
        return page

    @classmethod
    def _recover_legacy_abc_choice_rows(cls, page, gray):
        """Re-OCR compact A/B/C answer tables when their left cells vanish."""

        lines = list(page.lines)
        for start in range(len(lines) - 3):
            rows = lines[start:start + 4]
            if len({(row.page, row.column) for row in rows}) != 1:
                continue
            if any(_VISUAL_QUESTION_START.match(row.text) for row in rows):
                continue
            gaps = [
                float(right.bbox[1]) - float(left.bbox[1])
                for left, right in zip(rows, rows[1:])
            ]
            if any(not 0.015 <= gap <= 0.035 for gap in gaps):
                continue
            if not all(
                re.search(r"\bB\b", row.text, re.IGNORECASE)
                and re.search(r"\bC\b", row.text, re.IGNORECASE)
                for row in rows
            ):
                continue
            if sum(
                bool(re.search(r"\bA\b", row.text, re.IGNORECASE))
                for row in rows
            ) < 2:
                continue

            width, height = gray.size
            crop_x0 = min(float(row.bbox[0]) for row in rows) + 0.015
            crop_x1 = 0.96 if rows[0].column else 0.49
            recovered = []
            centers = [
                (float(row.bbox[1]) + float(row.bbox[3])) / 2
                for row in rows
            ]
            for offset, row in enumerate(rows):
                crop_y0 = (
                    (centers[offset - 1] + centers[offset]) / 2
                    if offset
                    else centers[offset] - 0.020
                )
                crop_y1 = (
                    (centers[offset] + centers[offset + 1]) / 2
                    if offset + 1 < len(rows)
                    else centers[offset] + 0.020
                )
                crop = gray.crop((
                    max(0, int(crop_x0 * width)),
                    max(0, int(crop_y0 * height)),
                    min(width, int(crop_x1 * width)),
                    min(height, int(crop_y1 * height)),
                ))
                value = cls._targeted_choice_crop_text(crop)
                value = re.sub(
                    r"^[^A-Za-z가-힣0-9]+", "", value or ""
                ).strip()
                if (
                    not re.search(r"\bA\b", value, re.IGNORECASE)
                    and re.search(r"\bB\b", value, re.IGNORECASE)
                    and re.search(r"\bC\b", value, re.IGNORECASE)
                ):
                    value = f"A : {value}"
                if not re.search(
                    r"\bA\b.*\bB\b.*\bC\b", value, re.IGNORECASE
                ):
                    recovered = []
                    break
                recovered.append(value)
            if len(recovered) != 4:
                continue

            marker_x = min(float(row.bbox[0]) for row in rows)
            rewritten = []
            for choice_number, (row, value) in enumerate(
                zip(rows, recovered), start=1
            ):
                marker = LayoutWord(
                    _VISUAL_CHOICE_SYMBOLS[choice_number - 1],
                    (marker_x, row.bbox[1], marker_x + 0.018, row.bbox[3]),
                    1.0,
                    row.column,
                    True,
                )
                content = LayoutWord(
                    value,
                    (marker_x + 0.025, row.bbox[1], crop_x1, row.bbox[3]),
                    0.90,
                    row.column,
                )
                rewritten.append(LayoutLine(
                    (marker, content),
                    (marker_x, row.bbox[1], crop_x1, row.bbox[3]),
                    row.page,
                    row.column,
                ))
            lines[start:start + 4] = rewritten
            return replace(page, lines=tuple(lines))
        return page

    @classmethod
    def _recover_legacy_proposition_sequence_grid(cls, page, gray):
        """Classify ㄱ-ㄹ option sequences from same-page raster templates."""

        try:
            from PIL import Image, ImageOps
        except Exception:
            return page

        lines = list(page.lines)
        short_label = re.compile(r"^\S{1,3}[.]$")
        legend = None
        for index in range(len(lines) - 1):
            upper, lower = lines[index:index + 2]
            if upper.page != lower.page or upper.column != lower.column:
                continue
            if not 0.012 <= float(lower.bbox[1]) - float(upper.bbox[1]) <= 0.035:
                continue
            upper_labels = [
                word for word in upper.words
                if short_label.fullmatch(str(word.text).strip())
            ]
            lower_labels = [
                word for word in lower.words
                if short_label.fullmatch(str(word.text).strip())
            ]
            if len(upper_labels) != 2 or len(lower_labels) != 2:
                continue
            if any(
                abs(float(upper_labels[position].bbox[0]) - float(lower_labels[position].bbox[0]))
                > 0.020
                for position in range(2)
            ):
                continue
            legend = (index, upper, lower, upper_labels + lower_labels)
            break
        if legend is None:
            return page

        legend_index, upper, lower, template_words = legend
        next_question_index = next(
            (
                index for index in range(legend_index + 2, len(lines))
                if lines[index].column == upper.column
                and _VISUAL_QUESTION_START.match(lines[index].text)
            ),
            None,
        )
        if next_question_index is None:
            return page
        next_question_y = float(lines[next_question_index].bbox[1])
        scan_y0 = float(lower.bbox[3]) + 0.006
        scan_y1 = next_question_y - 0.008
        if not 0.025 <= scan_y1 - scan_y0 <= 0.12:
            return page

        width, height = gray.size
        column_left, column_right = (
            (0.47, 0.92) if upper.column else (0.05, 0.49)
        )

        def components(box):
            x0, y0, x1, y1 = box
            crop = gray.crop((x0, y0, x1, y1)).convert("L")
            pixels = crop.load()
            dark = {
                (x, y)
                for y in range(crop.height)
                for x in range(crop.width)
                if pixels[x, y] < 180
            }
            result = []
            while dark:
                seed = dark.pop()
                stack = [seed]
                points = [seed]
                while stack:
                    x, y = stack.pop()
                    for adjacent_y in range(max(0, y - 2), min(crop.height, y + 3)):
                        for adjacent_x in range(max(0, x - 2), min(crop.width, x + 3)):
                            adjacent = (adjacent_x, adjacent_y)
                            if adjacent not in dark:
                                continue
                            dark.remove(adjacent)
                            stack.append(adjacent)
                            points.append(adjacent)
                if len(points) < 3:
                    continue
                left = min(x for x, _y in points)
                top = min(y for _x, y in points)
                right = max(x for x, _y in points) + 1
                bottom = max(y for _x, y in points) + 1
                mask = Image.new("L", (right - left, bottom - top), 255)
                mask_pixels = mask.load()
                for x, y in points:
                    mask_pixels[x - left, y - top] = 0
                result.append(((left, top, right, bottom), len(points), mask))
            return result

        def vector(mask):
            bbox = ImageOps.invert(mask).getbbox()
            if bbox is None:
                return None
            glyph = mask.crop(bbox)
            scale = min(28 / max(glyph.width, 1), 28 / max(glyph.height, 1))
            glyph = glyph.resize(
                (
                    max(1, round(glyph.width * scale)),
                    max(1, round(glyph.height * scale)),
                ),
                Image.Resampling.NEAREST,
            )
            canvas = Image.new("L", (32, 32), 255)
            canvas.paste(glyph, ((32 - glyph.width) // 2, (32 - glyph.height) // 2))
            return tuple(value < 128 for value in canvas.getdata())

        templates = []
        for word in template_words:
            bbox = word.bbox
            word_components = components((
                max(0, int((float(bbox[0]) - 0.003) * width)),
                max(0, int((float(bbox[1]) - 0.004) * height)),
                min(width, int((float(bbox[2]) + 0.003) * width)),
                min(height, int((float(bbox[3]) + 0.004) * height)),
            ))
            candidates = [
                item for item in word_components
                if 0.004 <= (item[0][2] - item[0][0]) / width <= 0.020
                and 0.0035 <= (item[0][3] - item[0][1]) / height <= 0.014
            ]
            if not candidates:
                return page
            selected_template = max(candidates, key=lambda item: item[1])
            value = vector(selected_template[2])
            if value is None:
                return page
            templates.append((value, selected_template[1]))

        x0 = max(0, int(column_left * width))
        x1 = min(width, int(column_right * width))
        dark_rows = []
        minimum_ink = max(3, round((x1 - x0) * 0.01))
        for y in range(max(0, int(scan_y0 * height)), min(height, int(scan_y1 * height))):
            count = sum(gray.getpixel((x, y)) < 180 for x in range(x0, x1))
            if minimum_ink <= count < (x1 - x0) * 0.45:
                dark_rows.append(y)
        bands = []
        for y in dark_rows:
            if not bands or y - bands[-1][-1] > 2:
                bands.append([y])
            else:
                bands[-1].append(y)
        bands = [
            band for band in bands
            if 0.003 <= (band[-1] - band[0] + 1) / height <= 0.016
        ]
        if len(bands) != 2:
            return page

        cell_bounds = (
            (column_left, (column_left + column_right) / 2),
            ((column_left + column_right) / 2, column_right),
        )
        option_components = []
        for band in bands:
            band_top = max(0, band[0] - 2)
            band_bottom = min(height, band[-1] + 3)
            for cell_left, cell_right in cell_bounds:
                cell_x0 = max(0, int(cell_left * width))
                cell_x1 = min(width, int(cell_right * width))
                cell_components = components((
                    cell_x0, band_top, cell_x1, band_bottom,
                ))
                glyphs = [
                    item for item in cell_components
                    if 0.006 <= (item[0][2] - item[0][0]) / width <= 0.018
                    and 0.0035 <= (item[0][3] - item[0][1]) / height <= 0.014
                ]
                glyphs.sort(key=lambda item: item[0][0])
                if len(glyphs) < 4:
                    return page
                option_components.append((glyphs[-4:], cell_left, band[0] / height))

        template_labels = ("ㄱ", "ㄷ", "ㄴ", "ㄹ")
        recovered = []
        for glyphs, cell_left, row_y in option_components:
            values = [(vector(item[2]), item[1]) for item in glyphs]
            if any(value is None for value, _ink in values):
                return page
            matrix = [
                [
                    (
                        sum(
                            left != right
                            for left, right in zip(value, template_value)
                        )
                        / len(template_value)
                        + 0.40
                        * abs(ink - template_ink)
                        / max(template_ink, 1)
                    )
                    for template_value, template_ink in templates
                ]
                for value, ink in values
            ]
            assignments = sorted(
                (
                    sum(matrix[position][assignment[position]] for position in range(4)),
                    assignment,
                )
                for assignment in itertools.permutations(range(4))
            )
            best_cost, assignment = assignments[0]
            if best_cost / 4 > 0.35 or assignments[1][0] - best_cost < 0.005:
                return page
            recovered.append((
                " - ".join(template_labels[index] for index in assignment),
                cell_left,
                row_y,
            ))

        answer_y0 = bands[0][0] / height - 0.004
        answer_y1 = bands[-1][-1] / height + 0.006
        remove_indexes = [
            index for index, line in enumerate(lines)
            if line.column == upper.column
            and answer_y0 <= float(line.bbox[1]) <= answer_y1
        ]
        insert_at = min(remove_indexes, default=next_question_index)
        kept = [
            line for index, line in enumerate(lines) if index not in set(remove_indexes)
        ]
        rewritten = []
        for choice_number, (value, cell_left, row_y) in enumerate(recovered, start=1):
            marker_x = cell_left + 0.010
            marker = LayoutWord(
                _VISUAL_CHOICE_SYMBOLS[choice_number - 1],
                (marker_x, row_y, marker_x + 0.018, row_y + 0.016),
                1.0,
                upper.column,
                True,
            )
            content = LayoutWord(
                value,
                (marker_x + 0.025, row_y, cell_left + 0.20, row_y + 0.016),
                1.0,
                upper.column,
            )
            rewritten.append(LayoutLine(
                (marker, content),
                (marker_x, row_y, content.bbox[2], row_y + 0.016),
                upper.page,
                upper.column,
            ))
        kept[insert_at:insert_at] = rewritten
        return replace(page, lines=tuple(kept))

    @classmethod
    def _recover_targeted_ton_hour_rows(cls, page, gray):
        lines = list(page.lines)
        for start in range(len(lines) - 7):
            window = lines[start:start + 8]
            row_pairs = [(window[offset], window[offset + 1]) for offset in range(0, 8, 2)]
            if any("톤" not in upper.text or "시간" not in lower.text for upper, lower in row_pairs):
                continue
            if any(
                not 0.010 <= float(lower.bbox[1]) - float(upper.bbox[1]) <= 0.030
                for upper, lower in row_pairs
            ):
                continue
            if any(
                not 0.010 <= float(window[offset + 2].bbox[1]) - float(window[offset + 1].bbox[1]) <= 0.030
                for offset in range(0, 6, 2)
            ):
                continue
            if not any(re.search(r"[①-④]\d+톤", upper.text) for upper, _lower in row_pairs):
                continue
            width, height = gray.size
            recovered = []
            for upper, lower in row_pairs:
                crop = gray.crop((
                    max(0, int((float(upper.bbox[0]) - 0.015) * width)),
                    max(0, int((float(upper.bbox[1]) - 0.010) * height)),
                    min(width, int((max(float(upper.bbox[2]), float(lower.bbox[2])) + 0.010) * width)),
                    min(height, int((float(lower.bbox[3]) + 0.010) * height)),
                ))
                target = cls._targeted_choice_crop_text(crop)
                ton = re.search(r"(\d{2,4})\s*톤", target or "")
                hour = re.search(r"(\d{1,2})\s*시", target or "")
                if ton is None or hour is None:
                    recovered = []
                    break
                raw = f"{upper.text} {lower.text}"
                raw = re.sub(r"[①-④]", "", raw)
                raw = re.sub(r"^[㉦㉨㉭]\s*", "", raw).strip()
                raw = re.sub(r"\d*\s*톤", f"{ton.group(1)}톤", raw, count=1)
                raw = re.sub(r"\d+\s*시간", f"{hour.group(1)}시간", raw, count=1)
                recovered.append(re.sub(r"\s+", " ", raw).strip())
            if len(recovered) != 4:
                continue
            rewritten = []
            for choice_number, ((upper, lower), text_value) in enumerate(
                zip(row_pairs, recovered), start=1
            ):
                marker_x = float(upper.bbox[0])
                content_x = min(
                    (
                        float(word.bbox[0])
                        for word in upper.words
                        if float(word.bbox[0]) >= marker_x + 0.020
                    ),
                    default=marker_x + 0.030,
                )
                marker = LayoutWord(
                    text=_VISUAL_CHOICE_SYMBOLS[choice_number - 1],
                    bbox=(marker_x, upper.bbox[1], marker_x + 0.018, lower.bbox[3]),
                    confidence=1.0,
                    column=upper.column,
                    visual_choice_marker=True,
                )
                content = LayoutWord(
                    text=text_value,
                    bbox=(content_x, upper.bbox[1], max(upper.bbox[2], lower.bbox[2]), lower.bbox[3]),
                    confidence=min(
                        (word.confidence for line in (upper, lower) for word in line.words if word.confidence is not None),
                        default=1.0,
                    ),
                    column=upper.column,
                )
                rewritten.append(
                    LayoutLine(
                        words=(marker, content),
                        bbox=(marker_x, upper.bbox[1], content.bbox[2], lower.bbox[3]),
                        page=upper.page,
                        column=upper.column,
                    )
                )
            lines[start:start + 8] = rewritten
            return replace(page, lines=tuple(lines))
        return page

    @classmethod
    def _recover_targeted_three_field_rows(cls, page, gray):
        lines = list(page.lines)
        for start in range(len(lines) - 3):
            rows = lines[start:start + 4]
            if any(
                not all(label in row.text for label in ("㉠", "㉡", "㉢"))
                for row in rows
            ):
                continue
            if any(
                not 0.010 <= float(right.bbox[1]) - float(left.bbox[1]) <= 0.030
                for left, right in zip(rows, rows[1:])
            ):
                continue
            if not any(re.search(r"[①-④]\d", row.text) for row in rows):
                continue
            width, height = gray.size
            recovered = []
            for row in rows:
                crop = gray.crop((
                    max(0, int((float(row.bbox[0]) - 0.010) * width)),
                    max(0, int((float(row.bbox[1]) - 0.010) * height)),
                    min(width, int((float(row.bbox[2]) + 0.010) * width)),
                    min(height, int((float(row.bbox[3]) + 0.010) * height)),
                ))
                target = cls._targeted_choice_crop_text(crop) or ""
                match = re.search(
                    r"㉠\s*(.+?)\s*㉡\s*(.+?)\s*㉢\s*(.+)$", target
                )
                if match is None or any(not value.strip() for value in match.groups()):
                    recovered = []
                    break
                recovered.append(
                    f"㉠ {match.group(1).strip()} ㉡ {match.group(2).strip()} ㉢ {match.group(3).strip()}"
                )
            if len(recovered) != 4:
                continue
            rewritten = []
            for choice_number, (row, text_value) in enumerate(zip(rows, recovered), start=1):
                marker_x = float(row.bbox[0])
                marker = LayoutWord(
                    text=_VISUAL_CHOICE_SYMBOLS[choice_number - 1],
                    bbox=(marker_x, row.bbox[1], marker_x + 0.018, row.bbox[3]),
                    confidence=1.0,
                    column=row.column,
                    visual_choice_marker=True,
                )
                content = LayoutWord(
                    text=text_value,
                    bbox=(marker_x + 0.025, row.bbox[1], row.bbox[2], row.bbox[3]),
                    confidence=min(
                        (word.confidence for word in row.words if word.confidence is not None),
                        default=1.0,
                    ),
                    column=row.column,
                )
                rewritten.append(
                    LayoutLine(
                        words=(marker, content),
                        bbox=(marker_x, row.bbox[1], row.bbox[2], row.bbox[3]),
                        page=row.page,
                        column=row.column,
                    )
                )
            lines[start:start + 4] = rewritten
            return replace(page, lines=tuple(lines))
        return page

    @classmethod
    def _recover_targeted_percentage_rows(cls, page, gray):
        def normalized_percent(text):
            compact = str(text).strip().replace(" ", "").strip(",")
            if match := re.fullmatch(r"(\d{1,3})%", compact):
                return int(match.group(1))
            for pattern in (
                r"^(\d{2,3})70$",
                r"^(\d+)0/0$",
                r"^(\d+)9/0$",
                r"^(\d+)96$",
            ):
                if match := re.fullmatch(pattern, compact):
                    value = int(match.group(1))
                    if 1 <= value <= 200:
                        return value
            return None

        lines = list(page.lines)
        for start in range(len(lines) - 3):
            rows = lines[start:start + 4]
            raw_values = [
                [
                    value
                    for word in row.words
                    if (value := normalized_percent(word.text)) is not None
                ]
                for row in rows
            ]
            if any(len(values) < 2 for values in raw_values):
                continue
            if any(
                not 0.010 <= float(right.bbox[1]) - float(left.bbox[1]) <= 0.025
                for left, right in zip(rows, rows[1:])
            ):
                continue
            width, height = gray.size
            recovered = []
            for row, raw in zip(rows, raw_values):
                crop = gray.crop((
                    max(0, int((float(row.bbox[0]) - 0.010) * width)),
                    max(0, int((float(row.bbox[1]) - 0.010) * height)),
                    min(width, int((float(row.bbox[2]) + 0.010) * width)),
                    min(height, int((float(row.bbox[3]) + 0.010) * height)),
                ))
                target = cls._targeted_choice_crop_text(crop) or ""
                target_values = [int(value) for value in re.findall(r"(\d{1,3})\s*%", target)]
                if len(target_values) != 3:
                    recovered = []
                    break
                recovered.append((raw[0], raw[1], target_values[2]))
            if len(recovered) != 4:
                continue
            rewritten = []
            for choice_number, (row, values) in enumerate(zip(rows, recovered), start=1):
                marker_x = min(float(row.bbox[0]), 0.95)
                marker = LayoutWord(
                    text=_VISUAL_CHOICE_SYMBOLS[choice_number - 1],
                    bbox=(marker_x, row.bbox[1], marker_x + 0.018, row.bbox[3]),
                    confidence=1.0,
                    column=row.column,
                    visual_choice_marker=True,
                )
                content = LayoutWord(
                    text=" ".join(f"{value}%" for value in values),
                    bbox=(marker_x + 0.025, row.bbox[1], row.bbox[2], row.bbox[3]),
                    confidence=min(
                        (word.confidence for word in row.words if word.confidence is not None),
                        default=1.0,
                    ),
                    column=row.column,
                )
                rewritten.append(
                    LayoutLine(
                        words=(marker, content),
                        bbox=(marker_x, row.bbox[1], row.bbox[2], row.bbox[3]),
                        page=row.page,
                        column=row.column,
                    )
                )
            lines[start:start + 4] = rewritten
            return replace(page, lines=tuple(lines))
        return page

    @classmethod
    def _recover_targeted_percentage_length_rows(cls, page, gray):
        def normalize(token):
            compact = token.replace(" ", "")
            for pattern in (r"^(\d+)0/0$", r"^(\d+)9/0$", r"^(\d+)96$", r"^(\d+)0%$"):
                if match := re.fullmatch(pattern, compact):
                    return int(match.group(1))
            if match := re.fullmatch(r"(\d{1,3})%", compact):
                return int(match.group(1))
            return None

        lines = list(page.lines)
        for start in range(1, len(lines) - 3):
            header = lines[start - 1]
            rows = lines[start:start + 4]
            if not all(label in header.text for label in ("㉠", "㉡", "㉢", "㉣")):
                continue
            if any("m" not in row.text for row in rows):
                continue
            if any(
                not 0.010 <= float(right.bbox[1]) - float(left.bbox[1]) <= 0.030
                for left, right in zip(rows, rows[1:])
            ):
                continue
            width, height = gray.size
            recovered = []
            for row in rows:
                raw_percentages = [
                    value
                    for word in row.words
                    if (value := normalize(str(word.text).strip())) is not None
                ]
                crop = gray.crop((
                    max(0, int((min(float(row.bbox[0]), float(header.bbox[0])) - 0.070) * width)),
                    max(0, int((float(row.bbox[1]) - 0.010) * height)),
                    min(width, int((float(row.bbox[2]) + 0.010) * width)),
                    min(height, int((float(row.bbox[3]) + 0.010) * height)),
                ))
                target = cls._targeted_choice_crop_text(crop) or ""
                percentages = [
                    value
                    for token in re.findall(r"\d+(?:0/0|9/0|96|%)", target)
                    if (value := normalize(token)) is not None
                ]
                length = re.search(r"(\d+)\s*m", target)
                if len(percentages) < 3 or length is None:
                    recovered = []
                    break
                chosen = raw_percentages[:3] if len(raw_percentages) >= 3 else percentages[:3]
                recovered.append((*chosen, int(length.group(1))))
            if len(recovered) != 4:
                continue
            rewritten = []
            for choice_number, (row, values) in enumerate(zip(rows, recovered), start=1):
                marker_x = min(float(row.bbox[0]), float(header.bbox[0]))
                marker = LayoutWord(
                    text=_VISUAL_CHOICE_SYMBOLS[choice_number - 1],
                    bbox=(marker_x, row.bbox[1], marker_x + 0.018, row.bbox[3]),
                    confidence=1.0,
                    column=row.column,
                    visual_choice_marker=True,
                )
                content = LayoutWord(
                    text=f"{values[0]}% {values[1]}% {values[2]}% {values[3]}m",
                    bbox=(marker_x + 0.025, row.bbox[1], row.bbox[2], row.bbox[3]),
                    confidence=min(
                        (word.confidence for word in row.words if word.confidence is not None),
                        default=1.0,
                    ),
                    column=row.column,
                )
                rewritten.append(
                    LayoutLine(
                        words=(marker, content),
                        bbox=(marker_x, row.bbox[1], row.bbox[2], row.bbox[3]),
                        page=row.page,
                        column=row.column,
                    )
                )
            lines[start:start + 4] = rewritten
            return replace(page, lines=tuple(lines))
        return page

    @classmethod
    def _recover_targeted_year_pairs(cls, page, gray):
        lines = list(page.lines)
        for start in range(len(lines) - 1):
            rows = lines[start:start + 2]
            if not 0.010 <= float(rows[1].bbox[1]) - float(rows[0].bbox[1]) <= 0.030:
                continue
            anchors = [
                [float(word.bbox[0]) for word in row.words if str(word.text).strip() == "㉠"]
                for row in rows
            ]
            if any(len(values) != 2 for values in anchors):
                continue
            if any("㉡" not in row.text for row in rows):
                continue
            width, height = gray.size
            recovered = []
            for row, values in zip(rows, anchors):
                bounds = (
                    (max(0.0, values[0] - 0.030), values[1] - 0.040),
                    (max(0.0, values[1] - 0.030), min(0.99, float(row.bbox[2]) + 0.012)),
                )
                for cell_start, cell_end in bounds:
                    crop = gray.crop((
                        int(cell_start * width),
                        max(0, int((float(row.bbox[1]) - 0.010) * height)),
                        min(width, int(cell_end * width)),
                        min(height, int((float(row.bbox[3]) + 0.010) * height)),
                    ))
                    target = cls._targeted_choice_crop_text(crop) or ""
                    match = re.search(
                        r"㉠\s*[:.]?\s*(\d+)\s*(개월|년).*?㉡\s*[:.]?\s*(\d+)\s*년",
                        target,
                    )
                    if match is None:
                        recovered = []
                        break
                    first, unit, second = match.groups()
                    raw = " ".join(
                        str(word.text)
                        for word in row.words
                        if cell_start <= float(word.bbox[0]) < cell_end
                    )
                    raw_first = re.search(r"㉠\s*[:.]?\s*(\d+)\s*(개월|년)", raw)
                    if raw_first is None or raw_first.groups() != (first, unit):
                        recovered = []
                        break
                    recovered.append((int(first), unit, int(second), cell_start, row))
                if not recovered:
                    break
            if len(recovered) != 4 or len({item[:3] for item in recovered}) != 4:
                continue
            rewritten = []
            for choice_number, (first, unit, second, marker_x, row) in enumerate(recovered, start=1):
                marker = LayoutWord(
                    _VISUAL_CHOICE_SYMBOLS[choice_number - 1],
                    (marker_x, row.bbox[1], marker_x + 0.018, row.bbox[3]),
                    1.0,
                    row.column,
                    True,
                )
                content = LayoutWord(
                    f"㉠ : {first}{unit} ㉡ : {second}년",
                    (marker_x + 0.025, row.bbox[1], marker_x + 0.19, row.bbox[3]),
                    1.0,
                    row.column,
                )
                rewritten.append(LayoutLine(
                    (marker, content),
                    (marker_x, row.bbox[1], content.bbox[2], row.bbox[3]),
                    row.page,
                    row.column,
                ))
            lines[start:start + 2] = rewritten
            return replace(page, lines=tuple(lines))
        return page

    @classmethod
    def _recover_targeted_training_rows(cls, page, gray):
        lines = list(page.lines)
        for start in range(len(lines) - 3):
            rows = lines[start:start + 4]
            if any(
                not 0.012 <= float(right.bbox[1]) - float(left.bbox[1]) <= 0.026
                for left, right in zip(rows, rows[1:])
            ):
                continue
            if sum("훈련" in row.text for row in rows) < 2 or "대응" not in rows[-1].text:
                continue
            width, height = gray.size
            first_content_x = min(
                (
                    float(word.bbox[0]) for word in rows[0].words
                    if not getattr(word, "visual_choice_marker", False)
                ),
                default=float(rows[0].bbox[0]),
            )
            first_crop = gray.crop((
                max(0, int((first_content_x - 0.010) * width)),
                max(0, int((float(rows[0].bbox[1]) - 0.004) * height)),
                min(width, int((float(rows[0].bbox[2]) + 0.020) * width)),
                min(height, int((float(rows[0].bbox[3]) + 0.004) * height)),
            ))
            first_target = cls._targeted_choice_crop_text(first_crop) or ""
            tail_crop = gray.crop((
                max(0, int((float(rows[-1].bbox[2]) - 0.083) * width)),
                max(0, int((float(rows[-1].bbox[1]) - 0.010) * height)),
                min(width, int((float(rows[-1].bbox[2]) + 0.025) * width)),
                min(height, int((float(rows[-1].bbox[3]) + 0.010) * height)),
            ))
            tail_target = cls._targeted_choice_crop_text(tail_crop) or ""
            if not re.fullmatch(r"[가-힣]+\s*훈련", first_target.strip()):
                continue
            if re.search(r"대응\s*훈련", tail_target) is None:
                continue
            values = [
                first_target.strip(),
                re.sub(r"^[①-④]\s*", "", rows[1].text).strip(),
                re.sub(r"^[①-④]\s*", "", rows[2].text).strip(),
                re.sub(r"\s*대응.*$", "", re.sub(r"^[①-④]\s*", "", rows[3].text)).strip()
                + " 대응 훈련",
            ]
            rewritten = []
            for choice_number, (row, value) in enumerate(zip(rows, values), start=1):
                marker_x = float(row.bbox[0])
                marker = LayoutWord(
                    _VISUAL_CHOICE_SYMBOLS[choice_number - 1],
                    (marker_x, row.bbox[1], marker_x + 0.018, row.bbox[3]),
                    1.0,
                    row.column,
                    True,
                )
                content = LayoutWord(
                    value,
                    (marker_x + 0.025, row.bbox[1], row.bbox[2], row.bbox[3]),
                    1.0,
                    row.column,
                )
                rewritten.append(LayoutLine(
                    (marker, content),
                    (marker_x, row.bbox[1], row.bbox[2], row.bbox[3]),
                    row.page,
                    row.column,
                ))
            lines[start:start + 4] = rewritten
            return replace(page, lines=tuple(lines))
        return page

    @classmethod
    def _recover_raster_verified_vertical_sequence(cls, page, gray):
        lines = list(page.lines)
        damaged = []
        for index, line in enumerate(lines):
            if not line.words:
                continue
            lead = str(line.words[0].text).strip()
            if lead in _VISUAL_DAMAGED_MARKERS:
                damaged.append((index, _VISUAL_DAMAGED_MARKERS[lead]))
        for offset in range(len(damaged) - 2):
            triple = damaged[offset:offset + 3]
            if [number for _index, number in triple] != [1, 2, 1]:
                continue
            indexes = [index for index, _number in triple]
            anchors = [lines[index] for index in indexes]
            if len({line.page for line in anchors}) != 1 or len({line.column for line in anchors}) != 1:
                continue
            marker_xs = [float(line.words[0].bbox[0]) for line in anchors]
            if max(marker_xs) - min(marker_xs) > 0.010:
                continue
            if float(anchors[-1].bbox[1]) - float(anchors[0].bbox[1]) > 0.20:
                continue
            marker_x = sum(marker_xs) / len(marker_xs)
            candidates = []
            for index in range(indexes[1] + 1, indexes[2]):
                line = lines[index]
                if not line.words or float(line.bbox[0]) < marker_x + 0.015:
                    continue
                score = cls._visual_marker_ring_score(gray, marker_x, line.bbox)
                if score[0] >= 23 and score[1] >= 140:
                    candidates.append(index)
            if len(candidates) != 1:
                continue
            selected = [indexes[0], indexes[1], candidates[0], indexes[2]]
            for choice_number, index in enumerate(selected, start=1):
                existing = index != candidates[0]
                lines[index] = cls._line_with_visual_markers(
                    lines[index],
                    [(
                        _VISUAL_CHOICE_SYMBOLS[choice_number - 1],
                        0,
                        marker_x,
                        existing,
                    )],
                )
            return replace(page, lines=tuple(lines))
        return page

    @classmethod
    def _recover_same_page_glyph_mapping(cls, page, gray):
        try:
            from PIL import ImageOps
        except Exception:
            return page

        lines = list(page.lines)
        labels = ("㉠", "㉡", "㉢", "㉣")
        candidates = {label: [] for label in labels}
        for index, line in enumerate(lines):
            if len(line.text) < 8:
                continue
            for label in labels:
                label_word = next(
                    (
                        word for word in line.words
                        if str(word.text).strip() == label
                        and not getattr(word, "visual_choice_marker", False)
                    ),
                    None,
                )
                if label_word is None:
                    continue
                right_words = [
                    word for word in line.words
                    if float(word.bbox[0]) >= float(label_word.bbox[0]) + 0.08
                    and (
                        getattr(word, "visual_choice_marker", False)
                        or re.match(r"^[㉠-㉭@]", str(word.text).strip())
                    )
                    and (
                        getattr(word, "visual_choice_marker", False)
                        or cls._visual_marker_ring_score(
                            gray, float(word.bbox[0]), line.bbox
                        )[0] >= 20
                    )
                ]
                if right_words:
                    candidates[label].append(
                        (index, label_word, min(right_words, key=lambda word: word.bbox[0]))
                    )

        template_group = None
        for first in candidates[labels[0]]:
            group = [first]
            for label in labels[1:]:
                match = next(
                    (
                        item for item in candidates[label]
                        if item[0] > group[-1][0]
                        and lines[item[0]].column == lines[first[0]].column
                        and float(lines[item[0]].bbox[1]) - float(lines[first[0]].bbox[1]) <= 0.15
                        and abs(float(item[1].bbox[0]) - float(first[1].bbox[0])) <= 0.012
                        and abs(float(item[2].bbox[0]) - float(first[2].bbox[0])) <= 0.018
                    ),
                    None,
                )
                if match is None:
                    break
                group.append(match)
            if len(group) == 4:
                template_group = group
                break
        if template_group is None:
            return page

        last_template_line = lines[template_group[-1][0]]
        y0 = float(last_template_line.bbox[1]) + 0.035
        next_question_y = next(
            (
                float(line.bbox[1])
                for line in lines[template_group[-1][0] + 1:]
                if line.column == last_template_line.column
                and float(line.bbox[1]) > y0
                and _VISUAL_QUESTION_START.match(line.text)
            ),
            None,
        )
        y1 = min(
            0.93,
            y0 + 0.13,
            (next_question_y - 0.015) if next_question_y is not None else 0.93,
        )
        left_x = float(template_group[0][1].bbox[0])
        if left_x < 0.5:
            x0, x1 = max(0.01, left_x - 0.04), 0.48
        else:
            x0, x1 = 0.46, 0.96
        points = []
        for yi in range(round(y0 * 1000), round(y1 * 1000), 3):
            for xi in range(round(x0 * 1000), round(x1 * 1000), 3):
                x, y = xi / 1000, yi / 1000
                score = cls._visual_marker_ring_score(
                    gray, x, (x, y, x + 0.020, y + 0.018)
                )
                if score[0] >= 23 and score[1] >= 140:
                    points.append((x, y))
        if not points:
            return page

        def clusters(values):
            groups = []
            for value in sorted(values):
                if not groups or value - groups[-1][-1] > 0.009:
                    groups.append([value])
                else:
                    groups[-1].append(value)
            return [sum(group) / len(group) for group in groups]

        ys = clusters([point[1] for point in points])
        row_xs = [
            clusters([x for x, point_y in points if abs(point_y - y) <= 0.007])
            for y in ys
        ]
        cells = []
        if len(ys) >= 4 and all(len(values) == 3 for values in row_xs[:4]):
            xs = [
                sum(values[column] for values in row_xs[:4]) / 4
                for column in range(3)
            ]
            ys = ys[:4]
            cells = [(xs[0], xs[1], xs[2], y) for y in ys]
        elif len(ys) >= 2 and all(len(values) >= 5 for values in row_xs[:2]):
            # A damaged inner glyph can miss the ring-score threshold in one
            # row.  Recover the six stable columns from the union of both
            # rows; the stricter glyph classifier below still has to validate
            # every inferred cell before any rewrite is allowed.
            xs = clusters([
                x for x, point_y in points
                if any(abs(point_y - row_y) <= 0.007 for row_y in ys[:2])
            ])
            if len(xs) != 6 or any(
                min(abs(value - x) for x in xs) > 0.009
                for values in row_xs[:2]
                for value in values
            ):
                return page
            ys = ys[:2]
            cells = [
                (xs[offset], xs[offset + 1], xs[offset + 2], y)
                for y in ys
                for offset in (0, 3)
            ]
        if len(cells) != 4:
            return page

        width, height = gray.size

        def vector(x, y):
            crop = gray.crop((
                max(0, int((x - 0.002) * width)),
                max(0, int((y - 0.002) * height)),
                min(width, int((x + 0.020) * width)),
                min(height, int((y + 0.018) * height)),
            )).point(lambda value: 0 if value < 180 else 255)
            bbox = ImageOps.invert(crop).getbbox()
            if bbox is None:
                return None
            crop = crop.crop(bbox).resize((40, 40)).crop((10, 8, 30, 32))
            return tuple(value < 128 for value in crop.getdata())

        left_templates = [
            vector(float(item[1].bbox[0]), float(lines[item[0]].bbox[1]))
            for item in template_group
        ]
        right_templates = [
            vector(float(item[2].bbox[0]), float(lines[item[0]].bbox[1]))
            for item in template_group
        ]
        if any(template is None for template in (*left_templates, *right_templates)):
            return page

        def classify(value, templates):
            distances = [
                sum(left != right for left, right in zip(value, template)) / len(value)
                for template in templates
            ]
            ordered = sorted(distances)
            best = distances.index(ordered[0])
            return best, ordered[0], ordered[1] - ordered[0]

        recovered = []
        for _outer_x, answer_left_x, answer_right_x, y in cells:
            left_value = vector(answer_left_x, y)
            right_value = vector(answer_right_x, y)
            if left_value is None or right_value is None:
                return page
            left_result = classify(left_value, left_templates)
            right_result = classify(right_value, right_templates)
            clear_left = next(
                (
                    labels.index(str(word.text).strip())
                    for line in lines
                    if abs(float(line.bbox[1]) - y) <= 0.008
                    for word in line.words
                    if str(word.text).strip() in labels
                    and abs(float(word.bbox[0]) - answer_left_x) <= 0.012
                ),
                None,
            )
            if clear_left is not None:
                if left_result[0] != clear_left or left_result[1] > 0.26:
                    return page
                left_index = clear_left
            else:
                if left_result[1] > 0.25 or left_result[2] < 0.08:
                    return page
                left_index = left_result[0]
            if right_result[1] > 0.21 or right_result[2] < 0.06:
                return page
            recovered.append((left_index, right_result[0]))
        if sorted(left for left, _right in recovered) != [0, 1, 2, 3]:
            return page

        answer_y0 = min(cell[3] for cell in cells) - 0.008
        answer_y1 = max(cell[3] for cell in cells) + 0.025
        remove_indexes = [
            index for index, line in enumerate(lines)
            if line.column == last_template_line.column
            and answer_y0 <= float(line.bbox[1]) <= answer_y1
        ]
        if not remove_indexes:
            return page
        insert_at = min(remove_indexes)
        rewritten = []
        for choice_number, ((left_index, right_index), cell) in enumerate(
            zip(recovered, cells), start=1
        ):
            outer_x, _left_glyph_x, _right_glyph_x, y = cell
            marker = LayoutWord(
                text=_VISUAL_CHOICE_SYMBOLS[choice_number - 1],
                bbox=(outer_x, y, outer_x + 0.018, y + 0.018),
                confidence=1.0,
                column=last_template_line.column,
                visual_choice_marker=True,
            )
            content = LayoutWord(
                text=f"mapping {labels[left_index]} - {chr(ord('a') + right_index)}",
                bbox=(outer_x + 0.025, y, outer_x + 0.12, y + 0.018),
                confidence=1.0,
                column=last_template_line.column,
            )
            rewritten.append(
                LayoutLine(
                    words=(marker, content),
                    bbox=(outer_x, y, content.bbox[2], y + 0.018),
                    page=last_template_line.page,
                    column=last_template_line.column,
                )
            )
        for index, label_word, _right_word in template_group:
            template_line = lines[index]
            filtered = tuple(
                word for word in template_line.words
                if not (
                    getattr(word, "visual_choice_marker", False)
                    and float(word.bbox[0]) <= float(label_word.bbox[0]) + 0.005
                )
            )
            if filtered != template_line.words:
                lines[index] = replace(
                    template_line,
                    words=filtered,
                    bbox=(
                        min(float(word.bbox[0]) for word in filtered),
                        template_line.bbox[1],
                        template_line.bbox[2],
                        template_line.bbox[3],
                    ),
                )

        # A mapping grid can occupy the space immediately above the next
        # question and make its first (unnumbered) line look like a trailing
        # choice continuation.  Once the grid has passed the glyph checks,
        # attach that line to the following numbered line locally instead of
        # changing the parser's general question-region boundary rules.
        next_question_index = next(
            (
                index for index, line in enumerate(lines)
                if index > max(remove_indexes)
                and line.column == last_template_line.column
                and float(line.bbox[1]) > answer_y1
                and _VISUAL_QUESTION_START.match(line.text)
            ),
            None,
        )
        if next_question_index is not None and next_question_index > 0:
            prefix_index = next_question_index - 1
            prefix = lines[prefix_index]
            numbered = lines[next_question_index]
            number_match = re.match(
                r"^\s*(\d{1,3})\s*(?:[.)•])?\s*(.*)$", numbered.text
            )
            if (
                prefix_index > max(remove_indexes)
                and prefix.column == numbered.column
                and not _VISUAL_QUESTION_START.match(prefix.text)
                and not any(
                    getattr(word, "visual_choice_marker", False)
                    for word in prefix.words
                )
                and 0 < float(numbered.bbox[1]) - float(prefix.bbox[1]) <= 0.025
                and 0 < float(prefix.bbox[1]) - answer_y1 <= 0.040
                and number_match is not None
            ):
                number, remainder = number_match.groups()
                merged_text = " ".join(
                    part for part in (prefix.text.strip(), remainder.strip()) if part
                )
                merged_word = LayoutWord(
                    text=f"{number}. {merged_text}",
                    bbox=(
                        min(float(prefix.bbox[0]), float(numbered.bbox[0])),
                        float(prefix.bbox[1]),
                        max(float(prefix.bbox[2]), float(numbered.bbox[2])),
                        float(numbered.bbox[3]),
                    ),
                    confidence=min(
                        (
                            float(word.confidence)
                            for word in (*prefix.words, *numbered.words)
                            if word.confidence is not None
                        ),
                        default=1.0,
                    ),
                    column=numbered.column,
                )
                lines[next_question_index] = LayoutLine(
                    words=(merged_word,),
                    bbox=merged_word.bbox,
                    page=numbered.page,
                    column=numbered.column,
                )
                remove_indexes.append(prefix_index)
        kept = [line for index, line in enumerate(lines) if index not in set(remove_indexes)]
        kept[insert_at:insert_at] = rewritten
        return replace(page, lines=tuple(kept))

    @classmethod
    def _recover_separated_glyph_mapping(cls, page, gray):
        """Recover a two-by-two mapping grid whose a-d legend is separate."""
        try:
            from PIL import ImageDraw, ImageOps
        except Exception:
            return page

        lines = list(page.lines)
        labels = ("㉠", "㉡", "㉢", "㉣")
        left_group = None
        for first_index, first_line in enumerate(lines):
            first_word = next(
                (word for word in first_line.words if str(word.text).strip() == labels[0]),
                None,
            )
            if first_word is None:
                continue
            group = [(first_index, first_word)]
            for label in labels[1:]:
                match = next(
                    (
                        (index, word)
                        for index, line in enumerate(lines[first_index + 1:], first_index + 1)
                        if index > group[-1][0]
                        and line.column == first_line.column
                        and 0 < float(line.bbox[1]) - float(first_line.bbox[1]) <= 0.10
                        for word in line.words
                        if str(word.text).strip() == label
                        and abs(float(word.bbox[0]) - float(first_word.bbox[0])) <= 0.012
                    ),
                    None,
                )
                if match is None:
                    break
                group.append(match)
            if len(group) == 4:
                left_group = group
        if left_group is None:
            return page

        first_index, first_word = left_group[0]
        last_left_index = left_group[-1][0]
        reference_group = []
        for index, line in enumerate(lines[last_left_index + 1:], last_left_index + 1):
            if line.column != lines[first_index].column:
                continue
            if _VISUAL_QUESTION_START.match(line.text):
                break
            if not line.words:
                continue
            word = line.words[0]
            if abs(float(word.bbox[0]) - float(first_word.bbox[0])) > 0.014:
                continue
            score = cls._visual_marker_ring_score(gray, float(word.bbox[0]), line.bbox)
            if score[0] < 20 or score[1] < 120:
                continue
            reference_group.append((index, word))
            if len(reference_group) == 4:
                break
        if len(reference_group) != 4:
            return page
        reference_ys = [float(lines[index].bbox[1]) for index, _word in reference_group]
        if (
            reference_ys[-1] - reference_ys[0] > 0.13
            or any(not 0.012 <= upper - lower <= 0.050 for lower, upper in zip(reference_ys, reference_ys[1:]))
        ):
            return page

        last_reference_line = lines[reference_group[-1][0]]
        y0 = float(last_reference_line.bbox[1]) + 0.010
        next_question_y = next(
            (
                float(line.bbox[1])
                for line in lines[reference_group[-1][0] + 1:]
                if line.column == last_reference_line.column
                and _VISUAL_QUESTION_START.match(line.text)
            ),
            None,
        )
        if next_question_y is None or not 0.035 <= next_question_y - y0 <= 0.12:
            return page
        y1 = next_question_y - 0.008
        if lines[first_index].column == 0:
            x0, x1 = max(0.01, float(first_word.bbox[0]) - 0.04), 0.48
        else:
            x0, x1 = 0.45, 0.96

        points = []
        for yi in range(round(y0 * 1000), round(y1 * 1000), 3):
            for xi in range(round(x0 * 1000), round(x1 * 1000), 3):
                x, y = xi / 1000, yi / 1000
                score = cls._visual_marker_ring_score(gray, x, (x, y, x + 0.020, y + 0.018))
                if score[0] >= 23 and score[1] >= 140:
                    points.append((x, y))
        if not points:
            return page

        def clusters(values):
            groups = []
            for value in sorted(values):
                if not groups or value - groups[-1][-1] > 0.009:
                    groups.append([value])
                else:
                    groups[-1].append(value)
            return [sum(group) / len(group) for group in groups]

        row_candidates = []
        for y in clusters([point[1] for point in points]):
            values = clusters([x for x, point_y in points if abs(point_y - y) <= 0.007])
            if len(values) >= 5:
                row_candidates.append((y, values))
        if len(row_candidates) < 2:
            return page
        (first_y, first_xs), (second_y, second_xs) = row_candidates[:2]
        if not 0.012 <= second_y - first_y <= 0.030:
            return page
        xs = clusters([
            x for x, point_y in points
            if abs(point_y - first_y) <= 0.007 or abs(point_y - second_y) <= 0.007
        ])
        if len(xs) != 6:
            return page
        cells = [
            (xs[offset], xs[offset + 1], xs[offset + 2], y)
            for y in (first_y, second_y)
            for offset in (0, 3)
        ]

        width, height = gray.size

        def vector(x, y):
            crop = gray.crop((
                max(0, int((x - 0.002) * width)),
                max(0, int((y - 0.002) * height)),
                min(width, int((x + 0.020) * width)),
                min(height, int((y + 0.018) * height)),
            )).point(lambda value: 0 if value < 180 else 255)
            pixels = crop.load()
            draw = ImageDraw.Draw(crop)
            for row in range(crop.height):
                if sum(pixels[column, row] < 128 for column in range(crop.width)) / crop.width >= 0.60:
                    draw.line((0, row, crop.width - 1, row), fill=255)
            for column in range(crop.width):
                if sum(pixels[column, row] < 128 for row in range(crop.height)) / crop.height >= 0.80:
                    draw.line((column, 0, column, crop.height - 1), fill=255)
            bbox = ImageOps.invert(crop).getbbox()
            if bbox is None:
                return None
            crop = crop.crop(bbox).resize((40, 40)).crop((8, 6, 32, 34))
            return tuple(value < 128 for value in crop.getdata())

        left_templates = [
            vector(float(word.bbox[0]), float(lines[index].bbox[1]))
            for index, word in left_group
        ]
        right_templates = [
            vector(float(word.bbox[0]), float(lines[index].bbox[1]))
            for index, word in reference_group
        ]
        if any(template is None for template in (*left_templates, *right_templates)):
            return page

        def distances(value, templates):
            return [
                sum(left != right for left, right in zip(value, template)) / len(value)
                for template in templates
            ]

        left_indexes = []
        right_matrix = []
        for _outer_x, left_x, right_x, y in cells:
            left_value, right_value = vector(left_x, y), vector(right_x, y)
            if left_value is None or right_value is None:
                return page
            left_distances = distances(left_value, left_templates)
            clear_left = next(
                (
                    labels.index(str(word.text).strip())
                    for line in lines
                    if abs(float(line.bbox[1]) - y) <= 0.008
                    for word in line.words
                    if str(word.text).strip() in labels
                    and abs(float(word.bbox[0]) - left_x) <= 0.012
                ),
                None,
            )
            if clear_left is None:
                ordered = sorted(left_distances)
                if ordered[0] > 0.22 or ordered[1] - ordered[0] < 0.08:
                    return page
                clear_left = left_distances.index(ordered[0])
            left_indexes.append(clear_left)
            right_matrix.append(distances(right_value, right_templates))
        if sorted(left_indexes) != [0, 1, 2, 3]:
            return page

        assignments = sorted(
            (
                sum(right_matrix[row][assignment[row]] for row in range(4)),
                assignment,
            )
            for assignment in itertools.permutations(range(4))
        )
        best_cost, right_indexes = assignments[0]
        strong_rows = sum(
            sorted(row)[1] - sorted(row)[0] >= 0.08
            and row[right_indexes[index]] == min(row)
            for index, row in enumerate(right_matrix)
        )
        if (
            best_cost / 4 > 0.18
            or assignments[1][0] - best_cost < 0.08
            or strong_rows < 3
        ):
            return page

        answer_y0 = min(cell[3] for cell in cells) - 0.008
        answer_y1 = max(cell[3] for cell in cells) + 0.025
        remove_indexes = [
            index for index, line in enumerate(lines)
            if line.column == last_reference_line.column
            and answer_y0 <= float(line.bbox[1]) <= answer_y1
        ]
        if not remove_indexes:
            return page
        insert_at = min(remove_indexes)
        rewritten = []
        for choice_number, (left_index, right_index, cell) in enumerate(
            zip(left_indexes, right_indexes, cells), start=1
        ):
            outer_x, _left_x, _right_x, y = cell
            marker = LayoutWord(
                _VISUAL_CHOICE_SYMBOLS[choice_number - 1],
                (outer_x, y, outer_x + 0.018, y + 0.018),
                1.0,
                last_reference_line.column,
                True,
            )
            content = LayoutWord(
                f"mapping {labels[left_index]} - {chr(ord('a') + right_index)}",
                (outer_x + 0.025, y, outer_x + 0.12, y + 0.018),
                1.0,
                last_reference_line.column,
            )
            rewritten.append(LayoutLine(
                (marker, content),
                (outer_x, y, content.bbox[2], y + 0.018),
                last_reference_line.page,
                last_reference_line.column,
            ))

        for reference_index, reference_word in reference_group:
            line = lines[reference_index]
            replacement = replace(
                reference_word,
                text=chr(ord("a") + reference_group.index((reference_index, reference_word))),
                visual_choice_marker=False,
            )
            lines[reference_index] = replace(
                line,
                words=tuple(replacement if word is reference_word else word for word in line.words),
            )
        kept = [line for index, line in enumerate(lines) if index not in set(remove_indexes)]
        kept[insert_at:insert_at] = rewritten
        return replace(page, lines=tuple(kept))

    @classmethod
    def _recover_empty_visual_grid_cell(
        cls, gray, lines, selected, *, trust_selected: bool = False
    ):
        by_line = {}
        for anchor in selected:
            by_line.setdefault(anchor[0], []).append(anchor)
        if len(by_line) != 2 or any(len(anchors) != 2 for anchors in by_line.values()):
            return None
        empty_cells = []
        shared_right_edge = max(
            float(lines[index].bbox[2]) for index in by_line
        )
        for index, anchors in by_line.items():
            ordered = sorted(anchors, key=lambda anchor: anchor[1])
            for position, anchor in enumerate(ordered):
                marker_x = anchor[1]
                cell_end_x = (
                    ordered[position + 1][1] - 0.010
                    if position + 1 < len(ordered)
                    else max(float(lines[index].bbox[2]), shared_right_edge)
                )
                content = [
                    word for word in lines[index].words
                    if float(word.bbox[0]) >= marker_x + 0.020
                    and float(word.bbox[0]) < cell_end_x
                ]
                if anchor[3] and anchor[2] < len(lines[index].words):
                    fused_text = str(lines[index].words[anchor[2]].text).strip()
                    damaged_prefix = _VISUAL_DAMAGED_PREFIX.match(fused_text)
                    if damaged_prefix and damaged_prefix.end() < len(fused_text):
                        content.append(lines[index].words[anchor[2]])
                if not content:
                    empty_cells.append((index, marker_x, cell_end_x))
        if len(empty_cells) != 1:
            return None
        index, marker_x, cell_end_x = empty_cells[0]
        score, projected_x = max(
            (
                cls._visual_marker_ring_score(gray, marker_x + delta, lines[index].bbox),
                marker_x + delta,
            )
            for delta in (-0.004, -0.003, -0.002, -0.001, 0.0, 0.001, 0.002, 0.003, 0.004)
        )
        if not trust_selected and (score[0] < 23 or score[1] < 140):
            return None
        width, height = gray.size
        centers = sorted(
            (
                (float(lines[line_index].bbox[1]) + float(lines[line_index].bbox[3])) / 2,
                line_index,
            )
            for line_index in by_line
        )
        center_position = next(
            position for position, (_center, line_index) in enumerate(centers)
            if line_index == index
        )
        center_y = centers[center_position][0]
        crop_top = float(lines[index].bbox[1]) - 0.006
        crop_bottom = float(lines[index].bbox[3]) + 0.006
        if center_position:
            crop_top = max(crop_top, (centers[center_position - 1][0] + center_y) / 2)
        if center_position + 1 < len(centers):
            crop_bottom = min(
                crop_bottom,
                (center_y + centers[center_position + 1][0]) / 2,
            )
        crop = gray.crop((
            max(0, int((projected_x - 0.015) * width)),
            max(0, int(crop_top * height)),
            min(width, int((cell_end_x + 0.005) * width)),
            min(height, int(crop_bottom * height)),
        ))
        recovered_text = (
            cls._targeted_korean_cell_text(crop)
            or cls._targeted_choice_crop_text(crop)
        )
        if not recovered_text:
            return None
        return index, recovered_text, projected_x, cell_end_x

    @classmethod
    def _recover_empty_vertical_table_cells(cls, gray, lines, selected):
        if len(selected) != 4 or len({anchor[0] for anchor in selected}) != 4:
            return []
        rows = []
        for anchor in sorted(selected, key=lambda item: item[0]):
            index, marker_x, word_index, existing, _known = anchor
            content = [
                word for offset, word in enumerate(lines[index].words)
                if float(word.bbox[0]) >= marker_x + 0.040
                and not (existing and offset == word_index)
            ]
            cells = []
            for word in sorted(content, key=lambda item: item.bbox[0]):
                start_x, end_x = float(word.bbox[0]), float(word.bbox[2])
                if not cells or start_x - cells[-1][1] >= 0.035:
                    cells.append([start_x, end_x, [word]])
                else:
                    cells[-1][1] = max(cells[-1][1], end_x)
                    cells[-1][2].append(word)
            rows.append((index, marker_x, cells))

        position_clusters = []
        for value in sorted(cell[0] for _index, _marker_x, cells in rows for cell in cells):
            cluster = next((
                group for group in position_clusters
                if abs(sum(group) / len(group) - value) <= 0.030
            ), None)
            if cluster is None:
                position_clusters.append([value])
            else:
                cluster.append(value)
        if len(position_clusters) != 3:
            return []
        columns = [sum(group) / len(group) for group in position_clusters]
        if min(right - left for left, right in zip(columns, columns[1:])) < 0.060:
            return []

        sparse = []
        observed_cells = []
        for index, marker_x, cells in rows:
            occupied = []
            for start_x, end_x, cell_words in cells:
                nearest = min(range(3), key=lambda position: abs(columns[position] - start_x))
                if abs(columns[nearest] - start_x) > 0.030 or nearest in occupied:
                    return []
                occupied.append(nearest)
                observed_cells.append((
                    index, nearest, start_x, end_x, cell_words
                ))
            missing = sorted(set(range(3)) - set(occupied))
            if not missing:
                continue
            if len(missing) != 1:
                return []
            sparse.append((index, marker_x, missing[0]))
        if not sparse:
            return []

        width, height = gray.size
        recovered = []
        # A present cell can still be a damaged OCR fragment.  Correct only
        # the standalone caret-like artifacts observed in broken Hangul OCR;
        # normal punctuation such as middots, slashes, and hyphens is valid
        # choice content.  Run corrections first because these narrow crops
        # are the most sensitive to OCR engine state.
        correction_variants = (
            (0.005, 0.035, 0.007, 0.009),
            (0.005, 0.055, 0.005, 0.009),
            (0.005, 0.055, 0.007, 0.005),
            (0.005, 0.055, 0.009, 0.005),
            (0.010, 0.045, 0.003, 0.005),
        )
        for index, column_number, observed_x, _end_x, cell_words in observed_cells:
            text_value = " ".join(str(word.text).strip() for word in cell_words).strip()
            if not any(
                token in {"^", "＾", "∧"}
                for token in text_value.split()
            ):
                continue
            line = lines[index]
            column_x = observed_x
            corrected = None
            for left_pad, right_pad, top_pad, bottom_pad in correction_variants:
                for x_shift in (0.0, 0.00025, 0.00075):
                    crop = gray.crop((
                        max(0, int((column_x + x_shift - left_pad) * width)),
                        max(0, int((float(line.bbox[1]) - top_pad) * height)),
                        min(width, int((column_x + x_shift + right_pad) * width)),
                        min(height, int((float(line.bbox[3]) + bottom_pad) * height)),
                    ))
                    corrected = cls._targeted_choice_crop_text(crop)
                    if corrected:
                        break
                if corrected:
                    break
            if not corrected or len(corrected.split()) > 2:
                return []
            cell_end_x = (
                columns[column_number + 1] - 0.020
                if column_number + 1 < len(columns)
                else min(0.99, column_x + 0.060)
            )
            recovered.append((
                index, corrected, max(0.0, column_x - 0.022),
                cell_end_x, True,
            ))

        crop_variants = (
            (0.015, 0.055, 0.006, 0.006),
            (0.015, 0.055, 0.007, 0.006),
            (0.015, 0.045, 0.005, 0.007),
            (0.010, 0.045, 0.003, 0.005),
        )
        for index, _marker_x, missing_column in sparse:
            line = lines[index]
            column_x = columns[missing_column]
            value = None
            for left_pad, right_pad, top_pad, bottom_pad in crop_variants:
                crop = gray.crop((
                    max(0, int((column_x - left_pad) * width)),
                    max(0, int((float(line.bbox[1]) - top_pad) * height)),
                    min(width, int((column_x + right_pad) * width)),
                    min(height, int((float(line.bbox[3]) + bottom_pad) * height)),
                ))
                value = cls._targeted_choice_crop_text(crop)
                if value:
                    break
            if not value or len(value.split()) > 2:
                return []
            crop_end_x = min(0.99, column_x + 0.060)
            recovered.append((
                index, value, max(0.0, column_x - 0.022),
                crop_end_x, True,
            ))
        return recovered

    @classmethod
    def _recover_compact_inline_visual_layout(cls, gray, lines, region_indexes):
        for index in region_indexes:
            line = lines[index]
            words = sorted(line.words, key=lambda word: word.bbox[0])
            if len(words) < 9:
                continue
            first_text = str(words[0].text).strip()
            damaged_indexes = [
                offset for offset, word in enumerate(words)
                if str(word.text).strip() in _VISUAL_DAMAGED_MARKERS
            ]
            second_indexes = [
                offset for offset, word in enumerate(words)
                if str(word.text).strip() == "2"
            ]
            if (
                first_text not in _VISUAL_DAMAGED_MARKERS
                or len(damaged_indexes) != 2
                or damaged_indexes[0] != 0
                or len(second_indexes) != 1
                or not 0 < second_indexes[0] < damaged_indexes[1]
            ):
                continue
            second_index = second_indexes[0]
            fourth_index = damaged_indexes[1]
            gaps = [
                (
                    float(words[offset + 1].bbox[0])
                    - float(words[offset].bbox[2]),
                    offset + 1,
                )
                for offset in range(second_index + 1, fourth_index - 1)
            ]
            if not gaps:
                continue
            gap, third_index = max(gaps)
            if gap < 0.035:
                continue
            third_x = float(words[third_index].bbox[0]) - 0.029
            candidates = (
                (0, float(words[0].bbox[0])),
                (second_index, float(words[second_index].bbox[0])),
                (third_index, third_x),
                (fourth_index, float(words[fourth_index].bbox[0])),
            )
            scores = [
                cls._visual_marker_ring_score(gray, marker_x, line.bbox)
                for _word_index, marker_x in candidates
            ]
            if any(
                score[0] < (22 if choice_number in (1, 4) else 23)
                or score[1] < 140
                for choice_number, score in enumerate(scores, start=1)
            ):
                continue
            return [
                (
                    index,
                    marker_x,
                    word_index,
                    choice_number != 3,
                    choice_number if choice_number == 2 else None,
                )
                for choice_number, (word_index, marker_x) in enumerate(candidates, start=1)
            ]
        return None

    @staticmethod
    def _targeted_choice_crop_text(crop) -> str | None:
        try:
            import asyncio
            from collections import Counter
            from PIL import Image, ImageEnhance, ImageOps
        except Exception:
            return None

        def worker():
            async def recognize():
                try:
                    from winrt.windows.graphics.imaging import BitmapDecoder
                    from winrt.windows.globalization import Language
                    from winrt.windows.media.ocr import OcrEngine
                    from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream
                except Exception:
                    return []
                engine = OcrEngine.try_create_from_language(Language("ko"))
                if engine is None:
                    return []
                enlarged = crop.resize(
                    (max(1, crop.width * 4), max(1, crop.height * 4)),
                    Image.Resampling.LANCZOS,
                )
                contrasted = ImageOps.autocontrast(enlarged)
                sharpened = ImageEnhance.Sharpness(contrasted).enhance(2.5)
                variants = (
                    sharpened,
                    sharpened.point(lambda pixel: 0 if pixel < 190 else 255),
                    contrasted,
                )
                values = []
                for variant in variants:
                    buffer = io.BytesIO()
                    variant.convert("RGB").save(buffer, format="PNG")
                    stream = InMemoryRandomAccessStream()
                    writer = DataWriter(stream.get_output_stream_at(0))
                    writer.write_bytes(buffer.getvalue())
                    await writer.store_async()
                    await writer.flush_async()
                    writer.close()
                    stream.seek(0)
                    decoder = await BitmapDecoder.create_async(stream)
                    bitmap = await decoder.get_software_bitmap_async()
                    result = await engine.recognize_async(bitmap)
                    value = " ".join(
                        str(word.text).strip()
                        for line in result.lines
                        for word in line.words
                        if str(word.text).strip()
                    ).strip()
                    value = _VISUAL_DAMAGED_PREFIX.sub("", value, count=1).strip(" .")
                    if value:
                        values.append(value)
                return values

            return asyncio.run(recognize())

        try:
            values = _run_with_timeout(worker, timeout_seconds=20)
        except Exception:
            return None
        if not values:
            return None
        keys = [re.sub(r"[^0-9A-Za-z가-힣]", "", value).casefold() for value in values]
        counts = Counter(key for key in keys if key)
        if not counts:
            return None
        key, count = counts.most_common(1)[0]
        if count < 2:
            return None
        return next(value for value, candidate_key in zip(values, keys) if candidate_key == key)

    @staticmethod
    def _parse_targeted_choice_values(value: str) -> list[str] | None:
        """Split OCR text only when four visible option markers delimit it."""

        line_marker = re.compile(
            r"^\s*(?:[①②③④㉦㉨㉭@]|0[0-9OQ]{0,2}|"
            r"[@(（]?[0-9OQ]{1,2}[)）.]?)\s+",
            re.IGNORECASE,
        )
        line_values = []
        for line in value.splitlines():
            match = line_marker.match(line)
            if match is None:
                continue
            choice = re.sub(r"\s+", " ", line[match.end():]).strip(" .;|")
            if choice:
                line_values.append(choice)
        if len(line_values) >= 4:
            for start in range(len(line_values) - 3):
                choices = line_values[start:start + 4]
                if len(set(choices)) == 4:
                    return choices

        marker = re.compile(
            r"[①②③④@]|(?<![0-9A-Za-z가-힣])(?:0[0-9OQ]{0,2}|"
            r"0[0-9OQ]{0,2}[.)]?|\([0-4OQ]{1,2}\)?|[0-4OQ9][.)])(?=\s|$)",
            re.IGNORECASE,
        )
        matches = list(marker.finditer(value))
        candidates: list[list[str]] = []
        for start in range(max(1, len(matches) - 3)):
            window = matches[start:start + 4]
            if len(window) != 4:
                continue
            choices = []
            for offset, match in enumerate(window):
                end = window[offset + 1].start() if offset + 1 < 4 else len(value)
                choice = re.sub(r"\s+", " ", value[match.end():end]).strip(" \t\r\n.;|")
                choices.append(choice)
            if all(choices) and len(set(choices)) == 4:
                candidates.append(choices)
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda choices: (
                sum(bool(re.search(r"[0-9A-Za-z가-힣ㄱ-ㅎ㉠-㉭]", choice)) for choice in choices),
                -max(len(choice) for choice in choices),
                sum(len(choice) for choice in choices),
            ),
        )

    @classmethod
    def _targeted_korean_choice_values(cls, crop) -> list[str] | None:
        """Use bundled Korean OCR data to recover a complete marked answer band."""

        executable = shutil.which("tesseract")
        if executable is None:
            fallback = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
            executable = str(fallback) if fallback.exists() else None
        tessdata = Path(__file__).resolve().parent / "tessdata"
        languages = [
            language
            for language, required in (
                ("kor+eng", ("kor.traineddata", "eng.traineddata")),
                ("kor", ("kor.traineddata",)),
            )
            if all((tessdata / name).exists() for name in required)
        ]
        if executable is None or not languages:
            return None
        try:
            from PIL import Image, ImageEnhance, ImageOps

            scale = 1.5
            enlarged = crop.convert("L").resize(
                (max(1, int(crop.width * scale)), max(1, int(crop.height * scale))),
                Image.Resampling.LANCZOS,
            )
            contrasted = ImageOps.autocontrast(enlarged)
            variants = (ImageEnhance.Sharpness(contrasted).enhance(2.0),)
            for language in languages:
                for psm in (6, 11):
                    for variant in variants:
                        buffer = io.BytesIO()
                        variant.convert("RGB").save(buffer, format="PNG")
                        completed = subprocess.run(
                            [
                                executable,
                                "stdin",
                                "stdout",
                                "--tessdata-dir",
                                str(tessdata),
                                "-l",
                                language,
                                "--psm",
                                str(psm),
                            ],
                            input=buffer.getvalue(),
                            stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL,
                            timeout=20,
                            check=False,
                            creationflags=(
                                subprocess.CREATE_NO_WINDOW
                                if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW")
                                else 0
                            ),
                        )
                        value = completed.stdout.decode("utf-8", errors="ignore").strip()
                        parsed = cls._parse_targeted_choice_values(value)
                        if parsed is not None:
                            return parsed
            return None
        except Exception:
            return None

    @classmethod
    def _targeted_korean_cell_text(cls, crop) -> str | None:
        """Recover one small Korean/English answer cell with bundled models."""

        executable = shutil.which("tesseract")
        if executable is None:
            fallback = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
            executable = str(fallback) if fallback.exists() else None
        tessdata = Path(__file__).resolve().parent / "tessdata"
        if (
            executable is None
            or not (tessdata / "kor.traineddata").exists()
            or not (tessdata / "eng.traineddata").exists()
        ):
            return None
        try:
            from PIL import Image, ImageEnhance, ImageOps

            enlarged = crop.convert("L").resize(
                (max(1, crop.width * 6), max(1, crop.height * 6)),
                Image.Resampling.LANCZOS,
            )
            image = ImageEnhance.Sharpness(ImageOps.autocontrast(enlarged)).enhance(2.0)
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, format="PNG")
            values = []
            for psm in (7, 6, 11):
                completed = subprocess.run(
                    [
                        executable,
                        "stdin",
                        "stdout",
                        "--tessdata-dir",
                        str(tessdata),
                        "-l",
                        "kor+eng",
                        "--psm",
                        str(psm),
                    ],
                    input=buffer.getvalue(),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    timeout=20,
                    check=False,
                    creationflags=(
                        subprocess.CREATE_NO_WINDOW
                        if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW")
                        else 0
                    ),
                )
                value = completed.stdout.decode("utf-8", errors="ignore").strip()
                value = re.sub(
                    r"^\s*(?:[①-④㉦㉨㉭]|[@(（]?[0-9OQ]{1,2}[)）.]?)\s*",
                    "",
                    value,
                    count=1,
                    flags=re.IGNORECASE,
                ).strip(" .;|\r\n")
                if value and len(re.findall(r"[0-9A-Za-z가-힣ㄱ-ㅎ㉠-㉭]", value)) >= 2:
                    values.append(value)
            if not values:
                return None
            return min(values, key=lambda value: (value.count("\n"), -len(value)))
        except Exception:
            return None

    @staticmethod
    def _line_with_recovered_choice_text(
        line: LayoutLine,
        text_value: str,
        marker_x: float,
        cell_end_x: float,
        *,
        replace_existing: bool = False,
    ) -> LayoutLine:
        words = list(line.words)
        content_x = marker_x + 0.022
        if replace_existing:
            words = [
                word for word in words
                if not (
                    float(word.bbox[0]) >= content_x - 0.010
                    and float(word.bbox[0]) < cell_end_x
                    and not getattr(word, "visual_choice_marker", False)
                )
            ]
        words.append(LayoutWord(
            text=text_value,
            bbox=(
                content_x,
                line.bbox[1],
                max(marker_x + 0.024, cell_end_x - 0.006),
                line.bbox[3],
            ),
            confidence=0.85,
            column=line.column,
            visual_choice_marker=False,
        ))
        words.sort(key=lambda word: word.bbox[0])
        return replace(
            line,
            words=tuple(words),
            bbox=(
                min(word.bbox[0] for word in words),
                line.bbox[1],
                max(word.bbox[2] for word in words),
                line.bbox[3],
            ),
        )

    @staticmethod
    def _complete_explicit_visual_sequence(
        lines: Sequence[LayoutLine], region_indexes: Sequence[int]
    ) -> bool:
        numbers = []
        for index in region_indexes[1:]:
            for word in lines[index].words:
                text = str(word.text).strip()
                if text[:1] in _VISUAL_EXPLICIT_MARKERS:
                    numbers.append(_VISUAL_EXPLICIT_MARKERS[text[:1]])
        return numbers == [1, 2, 3, 4]

    @classmethod
    def _visual_ring_anchors(cls, gray, lines, region_indexes):
        anchors = []
        terminators = [
            position
            for position, index in enumerate(region_indexes)
            if re.search(r"[?？]", lines[index].text)
            or _VISUAL_QUESTION_TERMINATOR.search(lines[index].text)
        ]
        if terminators:
            terminator = terminators[0]
            balance = (
                lines[region_indexes[terminator]].text.count("(")
                - lines[region_indexes[terminator]].text.count(")")
            )
            while balance > 0 and terminator + 1 < len(region_indexes):
                terminator += 1
                balance += (
                    lines[region_indexes[terminator]].text.count("(")
                    - lines[region_indexes[terminator]].text.count(")")
                )
            region_indexes = region_indexes[terminator + 1:]
        markerish = (
            set(_VISUAL_EXPLICIT_MARKERS)
            | set(_VISUAL_DAMAGED_MARKERS)
            | {"@", "O", "0", "1", "2", "3", "4", "5", "9"}
        )
        trusted_markerish = (
            set(_VISUAL_EXPLICIT_MARKERS)
            | set(_VISUAL_DAMAGED_MARKERS)
            | {"@", "O", "1", "2", "3", "4", "5"}
        )
        for index in region_indexes:
            line = lines[index]
            if float(line.bbox[1]) >= 0.93:
                continue
            words = list(line.words)
            for word_index, word in enumerate(words):
                text = str(word.text).strip()
                word_x = float(word.bbox[0])
                damaged_prefix = _VISUAL_DAMAGED_PREFIX.match(text)
                parenthesized_damaged_prefix = bool(
                    text.startswith("(")
                    and damaged_prefix is not None
                    and damaged_prefix.end() < len(text)
                )
                if (
                    line.text.rstrip().endswith("?")
                    and (not text or text[:1] not in markerish)
                ):
                    continue
                if (
                    text
                    and text[:1] not in _VISUAL_PROPOSITION_MARKERS
                    and (
                        text[:1] in markerish
                        or len(text) <= 2
                        or parenthesized_damaged_prefix
                    )
                ):
                    scored_positions = [
                        (
                            cls._visual_marker_ring_score(gray, word_x + delta, line.bbox),
                            word_x + delta,
                        )
                        for delta in (-0.004, -0.003, -0.002, -0.001, 0.0, 0.001, 0.002, 0.003, 0.004)
                    ]
                    score, scored_x = max(scored_positions)
                    trusted_damaged_ring = (
                        text[:1] in _VISUAL_DAMAGED_MARKERS
                        and score[0] >= 22
                        and score[1] >= 140
                    )
                    if (score[0] >= 23 and score[1] >= 140) or trusted_damaged_ring:
                        known = _VISUAL_EXPLICIT_MARKERS.get(text[:1])
                        anchors.append((index, scored_x, word_index, True, known))
                if line.text.rstrip().endswith("?"):
                    continue
                previous_x = float(words[word_index - 1].bbox[2]) if word_index else None
                if previous_x is not None and word_x - previous_x < 0.030:
                    continue
                best_x = None
                best_score = (0, 0)
                for delta in (0.025, 0.026, 0.027, 0.028, 0.029, 0.030, 0.031):
                    marker_x = word_x - delta
                    score = cls._visual_marker_ring_score(gray, marker_x, line.bbox)
                    if score > best_score:
                        best_score = score
                        best_x = marker_x
                if best_x is not None and best_score[0] >= 23 and best_score[1] >= 140:
                    anchors.append((index, best_x, word_index, False, None))

        seed_clusters = []
        for anchor in sorted(anchors, key=lambda item: item[1]):
            cluster = next((
                group for group in seed_clusters
                if abs(group[0][1] - anchor[1]) <= 0.012
            ), None)
            if cluster is None:
                seed_clusters.append([anchor])
            else:
                cluster.append(anchor)
        for cluster in seed_clusters:
            if len({anchor[0] for anchor in cluster}) < 2:
                trusted_seed = any(
                    anchor[3]
                    and str(lines[anchor[0]].words[anchor[2]].text).strip()[:1]
                    in trusted_markerish
                    for anchor in cluster
                )
                if not trusted_seed:
                    continue
            marker_x = min(anchor[1] for anchor in cluster)
            observed_indexes = [anchor[0] for anchor in cluster]
            for index in region_indexes:
                if float(lines[index].bbox[1]) >= 0.93:
                    continue
                if any(
                    anchor[0] == index and abs(anchor[1] - marker_x) <= 0.012
                    for anchor in anchors
                ):
                    continue
                line = lines[index]
                if not line.words:
                    continue
                if line.text.rstrip().endswith("?"):
                    continue
                leading_x = float(line.words[0].bbox[0])
                leading_text = str(line.words[0].text).strip()
                if (
                    abs(leading_x - marker_x) <= 0.012
                    and len(leading_text) > 2
                    and leading_text[:1] not in _VISUAL_EXPLICIT_MARKERS
                    and leading_text[:1] not in _VISUAL_DAMAGED_MARKERS
                    and len({anchor[0] for anchor in cluster}) < 3
                    and not min(observed_indexes) < index < max(observed_indexes)
                ):
                    continue
                score, projected_x = max(
                    (
                        cls._visual_marker_ring_score(gray, marker_x + delta, line.bbox),
                        marker_x + delta,
                    )
                    for delta in (-0.004, -0.003, -0.002, -0.001, 0.0, 0.001, 0.002, 0.003, 0.004)
                )
                indented_choice_text = leading_x >= marker_x + 0.015
                weak_compact_marker = (
                    len({anchor[0] for anchor in cluster}) >= 3
                    and abs(leading_x - projected_x) <= 0.012
                    and len(leading_text) <= 2
                    and score[0] >= 20
                    and score[1] >= 120
                )
                if not (
                    (score[0] >= 23 and score[1] >= 140)
                    or (
                        len({anchor[0] for anchor in cluster}) >= 2
                        and indented_choice_text
                        and score[0] >= 20
                        and score[1] >= 120
                    )
                    or weak_compact_marker
                ):
                    continue
                if leading_x <= marker_x + 0.012:
                    damaged_prefix = _VISUAL_DAMAGED_PREFIX.match(leading_text)
                    insertion_x = (
                        leading_x
                        if damaged_prefix
                        else max(0.0, min(projected_x, leading_x) - 0.001)
                    )
                    word_index = 0
                else:
                    damaged_prefix = None
                    insertion_x = projected_x
                    word_index = next((
                        offset for offset, word in enumerate(line.words)
                        if float(word.bbox[0]) >= marker_x + 0.015
                    ), 0)
                anchors.append((
                    index,
                    insertion_x,
                    word_index,
                    bool(damaged_prefix),
                    None,
                ))

        # Projection can reveal a third strong ring only after an earlier
        # compact OCR token was visited.  Revisit compact damaged tokens once
        # three distinct rows now establish the shared marker column.
        verified_clusters = []
        for anchor in sorted(anchors, key=lambda item: item[1]):
            cluster = next((
                group for group in verified_clusters
                if abs(group[0][1] - anchor[1]) <= 0.012
            ), None)
            if cluster is None:
                verified_clusters.append([anchor])
            else:
                cluster.append(anchor)
        for cluster in verified_clusters:
            if len({anchor[0] for anchor in cluster}) < 3:
                continue
            marker_x = min(anchor[1] for anchor in cluster)
            for index in region_indexes:
                if any(
                    anchor[0] == index and abs(anchor[1] - marker_x) <= 0.012
                    for anchor in anchors
                ):
                    continue
                line = lines[index]
                if not line.words or line.text.rstrip().endswith("?"):
                    continue
                leading_word = line.words[0]
                leading_text = str(leading_word.text).strip()
                leading_x = float(leading_word.bbox[0])
                damaged_prefix = _VISUAL_DAMAGED_PREFIX.match(leading_text)
                if (
                    damaged_prefix is None
                    or damaged_prefix.end() != len(leading_text)
                    or abs(leading_x - marker_x) > 0.012
                ):
                    continue
                score, _projected_x = max(
                    (
                        cls._visual_marker_ring_score(
                            gray, marker_x + delta, line.bbox
                        ),
                        marker_x + delta,
                    )
                    for delta in (
                        -0.004, -0.003, -0.002, -0.001, 0.0,
                        0.001, 0.002, 0.003, 0.004,
                    )
                )
                if score[0] >= 20 and score[1] >= 120:
                    anchors.append((index, leading_x, 0, True, None))

        def inferred_anchor(index, marker_x):
            if lines[index].text.rstrip().endswith("?"):
                return None
            score, projected_x = max(
                (
                    cls._visual_marker_ring_score(gray, marker_x + delta, lines[index].bbox),
                    marker_x + delta,
                )
                for delta in (
                    -0.012, -0.011, -0.010, -0.009, -0.008, -0.007,
                    -0.006, -0.005, -0.004, -0.003, -0.002, -0.001,
                    0.0,
                    0.001, 0.002, 0.003, 0.004, 0.005, 0.006,
                    0.007, 0.008, 0.009, 0.010, 0.011, 0.012,
                )
            )
            if score[0] < 20 or score[1] < 120:
                return None
            leading_word = lines[index].words[0]
            leading_x = float(leading_word.bbox[0])
            leading_text = str(leading_word.text).strip()
            if (
                abs(leading_x - projected_x) <= 0.012
                and (
                    len(leading_text) <= 2
                    or _VISUAL_DAMAGED_PREFIX.match(leading_text)
                )
            ):
                return score, (index, leading_x, 0, True, None)
            word_index = next((
                offset for offset, word in enumerate(lines[index].words)
                if float(word.bbox[0]) >= projected_x + 0.015
            ), 0)
            return score, (index, projected_x, word_index, False, None)

        # A compact ①-④ row often loses exactly one marker in OCR.  Infer the
        # absent grid position only when the raster still contains its ring.
        by_line = {}
        for anchor in anchors:
            by_line.setdefault(anchor[0], []).append(anchor)
        for index, line_anchors in tuple(by_line.items()):
            ordered = sorted(line_anchors, key=lambda item: item[1])
            if len(ordered) != 3:
                continue
            candidates = []
            for missing_slot in range(4):
                slots = [slot for slot in range(4) if slot != missing_slot]
                step = (ordered[-1][1] - ordered[0][1]) / (slots[-1] - slots[0])
                if not 0.050 <= step <= 0.300:
                    continue
                origin = ordered[0][1] - slots[0] * step
                residual = max(
                    abs(anchor[1] - (origin + slot * step))
                    for anchor, slot in zip(ordered, slots)
                )
                if residual > 0.012:
                    continue
                marker_x = origin + missing_slot * step
                if not 0.01 <= marker_x <= 0.97:
                    continue
                inferred = inferred_anchor(index, marker_x)
                if inferred is not None:
                    candidates.append(inferred)
            if candidates:
                anchors.append(max(candidates, key=lambda item: item[0])[1])

        # Likewise complete an L-shaped three-ring observation in a 2x2 grid.
        by_line = {}
        for anchor in anchors:
            by_line.setdefault(anchor[0], []).append(anchor)
        ordered_lines = sorted(by_line)
        for upper_index, lower_index in zip(ordered_lines, ordered_lines[1:]):
            upper_y = float(lines[upper_index].bbox[1])
            lower_y = float(lines[lower_index].bbox[1])
            if not 0.012 <= lower_y - upper_y <= 0.080:
                continue
            upper = sorted(by_line[upper_index], key=lambda item: item[1])
            lower = sorted(by_line[lower_index], key=lambda item: item[1])
            if sorted((len(upper), len(lower))) != [1, 2]:
                continue
            pair, singleton, singleton_index = (
                (upper, lower, lower_index) if len(upper) == 2
                else (lower, upper, upper_index)
            )
            if pair[1][1] - pair[0][1] < 0.080:
                continue
            distances = [abs(singleton[0][1] - anchor[1]) for anchor in pair]
            matched = min(range(2), key=lambda position: distances[position])
            if distances[matched] > 0.035:
                continue
            inferred = inferred_anchor(singleton_index, pair[1 - matched][1])
            if inferred is not None:
                anchors.append(inferred[1])

        deduplicated = []
        for anchor in sorted(anchors, key=lambda item: (item[0], item[1], not item[3])):
            duplicate_at = next((
                offset for offset, prior in enumerate(deduplicated)
                if prior[0] == anchor[0] and abs(prior[1] - anchor[1]) <= 0.012
            ), None)
            if duplicate_at is None:
                deduplicated.append(anchor)
            elif anchor[3] and not deduplicated[duplicate_at][3]:
                deduplicated[duplicate_at] = anchor
        return deduplicated

    @staticmethod
    def _select_complete_visual_choice_layout(lines, anchors):
        if len(anchors) < 4:
            return None
        by_line = {}
        for anchor in anchors:
            by_line.setdefault(anchor[0], []).append(anchor)
        patterns = []

        def trusted_anchor(anchor):
            if not anchor[3]:
                return False
            token = str(lines[anchor[0]].words[anchor[2]].text).strip()
            return bool(token) and (
                token[:1] in (
                    set(_VISUAL_EXPLICIT_MARKERS)
                    | set(_VISUAL_DAMAGED_MARKERS)
                    | {"@", "O"}
                )
                or token in {"1", "2", "3", "4", "5"}
            )

        def fused_choice_content(anchor, offset, word):
            if not anchor[3] or offset != anchor[2]:
                return False
            token = str(word.text).strip()
            match = _VISUAL_DAMAGED_PREFIX.match(token)
            return bool(match and match.end() < len(token))

        def proposition_like_anchor(anchor):
            if anchor[2] >= len(lines[anchor[0]].words):
                return False
            token = str(lines[anchor[0]].words[anchor[2]].text).strip()
            return bool(token) and token[:1] in _VISUAL_PROPOSITION_MARKERS

        def inferred_ring_with_separate_content(anchor):
            if anchor[3] or anchor[2] >= len(lines[anchor[0]].words):
                return False
            word_x = float(lines[anchor[0]].words[anchor[2]].bbox[0])
            return word_x >= anchor[1] + 0.020

        def proposition_table_header(line):
            tokens = [str(word.text).strip() for word in line.words]
            markers = {token for token in tokens if token in _VISUAL_PROPOSITION_MARKERS}
            return (
                len(markers) >= 2
                and all(token in _VISUAL_PROPOSITION_MARKERS for token in tokens)
                and not any(
                    getattr(word, "visual_choice_marker", False)
                    for word in line.words
                )
            )

        def strong_grid(grid, *, allow_inferred_rings=False):
            span = grid[1][1] - grid[0][1]
            supported = [
                trusted_anchor(anchor)
                or (
                    allow_inferred_rings
                    and inferred_ring_with_separate_content(anchor)
                )
                for anchor in grid
            ]
            return (
                span >= 0.125
                and (
                    sum(supported) >= 3
                    or (
                        span >= 0.180
                        and all(
                            supported[offset]
                            or proposition_like_anchor(anchor)
                            for offset, anchor in enumerate(grid)
                        )
                    )
                )
            )

        for line_anchors in by_line.values():
            ordered = sorted(line_anchors, key=lambda item: item[1])
            candidates = []
            for candidate in itertools.combinations(ordered, 4):
                gaps = [
                    right[1] - left[1]
                    for left, right in zip(candidate, candidate[1:])
                ]
                if min(gaps) < 0.050:
                    continue
                mean_gap = sum(gaps) / len(gaps)
                irregularity = sum(abs(gap - mean_gap) for gap in gaps)
                line_index = candidate[0][0]
                has_cell_content = all(
                    any(
                        (
                            (
                                (not anchor[3] or offset != anchor[2])
                                and float(word.bbox[0]) >= anchor[1] + 0.020
                                and float(word.bbox[0]) < cell_end
                            )
                            or (
                                fused_choice_content(anchor, offset, word)
                            )
                        )
                        for offset, word in enumerate(lines[line_index].words)
                    )
                    for anchor, cell_end in zip(
                        candidate,
                        [
                            following[1] - 0.010
                            for following in candidate[1:]
                        ] + [float(lines[line_index].bbox[2]) + 0.005],
                    )
                )
                if irregularity <= 0.040 and has_cell_content:
                    candidates.append((irregularity, candidate))
            if candidates:
                patterns.append(list(min(candidates, key=lambda item: item[0])[1]))

        ordered_lines = sorted(by_line)
        grid_patterns = []
        two_cell_lines = [index for index in ordered_lines if len(by_line[index]) >= 2]
        for left_index, right_index in zip(two_cell_lines, two_cell_lines[1:]):
            def cell_pairs(line_index):
                ordered = sorted(by_line[line_index], key=lambda item: item[1])
                sources = ordered

                def has_content(anchor, left_x, right_x):
                    return any(
                        (
                            (
                                (not anchor[3] or offset != anchor[2])
                                and float(word.bbox[0]) >= left_x
                                and float(word.bbox[0]) < right_x
                            )
                            or (
                                fused_choice_content(anchor, offset, word)
                            )
                        )
                        for offset, word in enumerate(lines[line_index].words)
                    )

                pairs = []
                for pair in itertools.combinations(sources, 2):
                    if pair[1][1] - pair[0][1] < 0.080:
                        continue
                    content_count = sum((
                        has_content(
                            pair[0], pair[0][1] + 0.020,
                            pair[1][1] - 0.010,
                        ),
                        has_content(
                            pair[1], pair[1][1] + 0.020,
                            float(lines[line_index].bbox[2]) + 0.005,
                        ),
                    ))
                    if content_count:
                        pairs.append((pair, content_count))
                return pairs

            left_pairs = cell_pairs(left_index)
            right_pairs = cell_pairs(right_index)
            matching_pairs = []
            for left, left_content_count in left_pairs:
                for right, right_content_count in right_pairs:
                    if max(
                        abs(left[position][1] - right[position][1])
                        for position in range(2)
                    ) <= 0.030 and left_content_count + right_content_count >= 3:
                        total_span = (
                            left[1][1] - left[0][1]
                            + right[1][1] - right[0][1]
                        )
                        matching_pairs.append((total_span, list(left + right)))
            if matching_pairs:
                grid_patterns.append(max(matching_pairs, key=lambda item: item[0])[1])

        clusters = []
        for anchor in sorted(anchors, key=lambda item: item[1]):
            cluster = next((group for group in clusters if abs(group[0][1] - anchor[1]) <= 0.012), None)
            if cluster is None:
                clusters.append([anchor])
            else:
                cluster.append(anchor)
        vertical_patterns = []
        for cluster in clusters:
            distinct_lines = {}
            for anchor in cluster:
                distinct_lines.setdefault(anchor[0], anchor)
            if len(distinct_lines) >= 4:
                ordered = sorted(distinct_lines.values(), key=lambda item: item[0])
                cluster_patterns = []
                for start in range(len(ordered) - 3):
                    vertical = ordered[start:start + 4]
                    centers = [
                        (float(lines[item[0]].bbox[1]) + float(lines[item[0]].bbox[3])) / 2
                        for item in vertical
                    ]
                    gaps = [right - left for left, right in zip(centers, centers[1:])]
                    if not all(gap >= 0.012 for gap in gaps):
                        continue
                    trusted = [trusted_anchor(anchor) for anchor in vertical]
                    trusted_vertical = [
                        value and anchor[2] == 0
                        for value, anchor in zip(trusted, vertical)
                    ]
                    crosses_semantic_lead = any(
                        _VISUAL_QUESTION_LEAD.match(lines[index].text)
                        for index in range(vertical[0][0] + 1, vertical[-1][0])
                    )
                    crosses_table_header = any(
                        proposition_table_header(lines[index])
                        for index in range(vertical[0][0] + 1, vertical[-1][0])
                    )
                    cluster_patterns.append((
                        -int(crosses_semantic_lead or crosses_table_header),
                        sum(trusted_vertical),
                        int(trusted_vertical[0]) + int(trusted_vertical[-1]),
                        -sum(bool(anchor[3]) and anchor[2] != 0 for anchor in vertical),
                        sum(bool(anchor[3]) for anchor in vertical),
                        int(bool(vertical[0][3])) + int(bool(vertical[-1][3])),
                        -sum(abs(gap - sum(gaps) / len(gaps)) for gap in gaps),
                        -sum(gaps),
                        centers[-1],
                        vertical,
                    ))
                if cluster_patterns:
                    vertical_patterns.append(
                        max(cluster_patterns, key=lambda item: item[:-1])[-1]
                    )
        if vertical_patterns:
            chosen_vertical = min(
                vertical_patterns,
                key=lambda pattern: min(anchor[1] for anchor in pattern),
            )
            vertical_span = (
                float(lines[chosen_vertical[-1][0]].bbox[1])
                - float(lines[chosen_vertical[0][0]].bbox[1])
            )
            strong_grids = [
                grid for grid in grid_patterns
                if strong_grid(grid)
            ]
            compact_grid = min(
                strong_grids,
                key=lambda grid: (
                    float(lines[grid[-1][0]].bbox[1])
                    - float(lines[grid[0][0]].bbox[1])
                ),
                default=None,
            )
            if (
                compact_grid is not None
                and compact_grid[0][0] >= chosen_vertical[0][0]
                and vertical_span >= 3 * max(
                    0.001,
                    float(lines[compact_grid[-1][0]].bbox[1])
                    - float(lines[compact_grid[0][0]].bbox[1]),
                )
            ):
                patterns.append(compact_grid)
            else:
                patterns.append(chosen_vertical)
        else:
            patterns.extend(
                grid for grid in grid_patterns
                if strong_grid(grid, allow_inferred_rings=True)
            )

        if not patterns:
            return None
        def rank(pattern):
            centers = [
                (float(lines[item[0]].bbox[1]) + float(lines[item[0]].bbox[3])) / 2
                for item in pattern
            ]
            return (max(centers), -min(item[1] for item in pattern), min(centers))
        return max(patterns, key=rank)

    @classmethod
    def _has_visual_marker_ring(cls, gray, marker_x: float, bbox) -> bool:
        coverage, ring_pixels = cls._visual_marker_ring_score(gray, marker_x, bbox)
        return coverage >= 23 and ring_pixels >= 140

    @classmethod
    def _visual_marker_ring_score(cls, gray, marker_x: float, bbox) -> tuple[int, int]:
        width, height = gray.size
        center_x = (marker_x + 0.009) * width
        center_y = ((float(bbox[1]) + float(bbox[3])) / 2) * height
        crop = gray.crop((
            max(0, int(round(center_x - 0.016 * width))),
            max(0, int(round(center_y - 0.011 * height))),
            min(width, int(round(center_x + 0.016 * width))),
            min(height, int(round(center_y + 0.011 * height))),
        ))
        return cls._ring_coverage(crop)

    @staticmethod
    def _ring_coverage(crop) -> tuple[int, int]:
        gray = crop.convert("L").resize((80, 80))
        pixels = gray.load()
        buckets = set()
        ring_pixels = 0
        for y in range(12, 68):
            for x in range(12, 68):
                if pixels[x, y] >= 170:
                    continue
                radius = math.hypot(x - 40, y - 40)
                if 13 <= radius <= 22:
                    bucket = int(
                        ((math.atan2(y - 40, x - 40) + math.pi) / (2 * math.pi)) * 24
                    )
                    buckets.add(bucket)
                    ring_pixels += 1
        return len(buckets), ring_pixels

    @staticmethod
    def _line_with_visual_marker(line: LayoutLine, symbol: str) -> LayoutLine:
        first_text = str(line.words[0].text).strip()
        existing = (
            first_text[:1] in _VISUAL_DAMAGED_MARKERS
            or first_text[:1] in _VISUAL_EXPLICIT_MARKERS
            or first_text == "@"
        )
        return PDFExtractor._line_with_visual_markers(
            line, [(symbol, 0, float(line.words[0].bbox[0]), existing)]
        )

    @staticmethod
    def _line_with_visual_markers(
        line: LayoutLine,
        operations: Sequence[tuple[str, int, float, bool]],
    ) -> LayoutLine:
        words = list(line.words)
        for symbol, word_index, marker_x, existing in sorted(
            operations, key=lambda item: (item[1], item[3]), reverse=True
        ):
            if existing:
                first_text = str(words[word_index].text).strip()
                width = float(words[word_index].bbox[2]) - float(words[word_index].bbox[0])
                remainder = _VISUAL_DAMAGED_PREFIX.sub("", first_text, count=1)
                if remainder == first_text:
                    remainder = first_text[1:] if width > 0.024 and len(first_text) > 1 else ""
                words[word_index] = replace(
                    words[word_index],
                    text=symbol + remainder,
                    visual_choice_marker=True,
                )
            else:
                words.insert(
                    word_index,
                    LayoutWord(
                        text=symbol,
                        bbox=(marker_x, line.bbox[1], marker_x + 0.018, line.bbox[3]),
                        confidence=0.95,
                        column=line.column,
                        visual_choice_marker=True,
                    ),
                )
        words.sort(key=lambda word: word.bbox[0])
        return LayoutLine(
            words=tuple(words),
            bbox=(
                min(word.bbox[0] for word in words),
                line.bbox[1],
                max(word.bbox[2] for word in words),
                line.bbox[3],
            ),
            page=line.page,
            column=line.column,
        )

    @staticmethod
    def _detect_vertical_column_split(image) -> Optional[float]:
        """Detect a printed center divider on scanned two-column exam pages."""
        width, height = image.size
        if width < 700 or height < 900:
            return None

        gray = image.convert('L')
        pixels = gray.load()
        x_start = int(width * 0.30)
        x_end = int(width * 0.70)
        y_start = int(height * 0.08)
        y_end = int(height * 0.90)
        if x_end <= x_start or y_end <= y_start:
            return None

        min_dark_pixels = int((y_end - y_start) * 0.22)
        counts = []
        candidates = []
        for x in range(x_start, x_end):
            dark_count = 0
            for y in range(y_start, y_end):
                if pixels[x, y] < 90:
                    dark_count += 1
            counts.append((x, dark_count))
            if dark_count >= min_dark_pixels:
                candidates.append(x)

        low_groups = []
        current_low = []
        max_gutter_dark_pixels = max(12, int((y_end - y_start) * 0.012))
        for x, dark_count in counts:
            if dark_count <= max_gutter_dark_pixels:
                current_low.append(x)
            elif current_low:
                low_groups.append(current_low)
                current_low = []
        if current_low:
            low_groups.append(current_low)

        central_gutters = [
            group for group in low_groups
            if len(group) >= 18 and width * 0.42 <= (group[0] + group[-1]) / 2 <= width * 0.56
        ]
        gutter_split = None
        if central_gutters:
            gutter = min(
                central_gutters,
                key=lambda group: (abs(((group[0] + group[-1]) / 2) - (width / 2)), -len(group)),
            )
            gutter_split = float((gutter[0] + gutter[-1]) / 2)

        if not candidates:
            return gutter_split

        groups = []
        current = [candidates[0]]
        for x in candidates[1:]:
            if x - current[-1] <= 2:
                current.append(x)
            else:
                groups.append(current)
                current = [x]
        groups.append(current)

        # Use the first true center-divider stroke.  Some scanned forms have a
        # second, longer stroke on the right side of the gutter; splitting on
        # that stroke attaches right-column question numbers to the left row.
        # The 44% lower bound still excludes tables wholly inside the left
        # column, which was the legacy false-positive this selection replaced.
        central_groups = [
            group for group in groups
            if width * 0.44 <= sum(group) / len(group) <= width * 0.56
        ]
        if central_groups:
            divider_group = min(central_groups, key=lambda group: sum(group) / len(group))
        else:
            divider_group = groups[0]
        divider_split = float(sum(divider_group) / len(divider_group))
        if gutter_split is not None and divider_split > width * 0.52:
            return gutter_split
        return divider_split

    def _extract_positioned_text(self, page) -> str:
        """Rebuild page text from word coordinates to preserve mixed-script order."""
        try:
            words = page.get_text("words") or []
        except Exception:
            return ''
        if not words:
            return ''

        rect = getattr(page, 'rect', None)
        page_width = float(getattr(rect, 'width', 0) or 0)
        if page_width <= 0:
            page_width = max((float(word[2]) for word in words), default=0)
        midpoint = page_width / 2 if page_width > 0 else 360

        items = []
        has_left = False
        has_right = False
        for word in words:
            try:
                x0, y0, x1, y1, value = word[:5]
            except (TypeError, ValueError):
                continue
            value = str(value or '')
            if not value:
                continue
            center_x = (float(x0) + float(x1)) / 2
            has_left = has_left or center_x < midpoint
            has_right = has_right or center_x >= midpoint
            items.append({
                'x0': float(x0),
                'y0': float(y0),
                'x1': float(x1),
                'y1': float(y1),
                'text': value,
                'column': 0 if center_x < midpoint else 1,
            })
        if not items:
            return ''
        if not (has_left and has_right):
            for item in items:
                item['column'] = 0

        text_lines = []
        for column in sorted({item['column'] for item in items}):
            column_items = sorted(
                [item for item in items if item['column'] == column],
                key=lambda item: (item['y0'], item['x0']),
            )
            lines = self._group_positioned_lines(column_items)
            for line in lines:
                text_lines.append(self._join_positioned_line(line))

        return "\n".join(line for line in text_lines if line.strip())

    def _group_positioned_lines(self, items: List[dict], tolerance: float = 3.0) -> List[List[dict]]:
        lines = []
        for item in items:
            if not lines or abs(item['y0'] - lines[-1][0]['y0']) > tolerance:
                lines.append([item])
            else:
                lines[-1].append(item)
        return [
            self._split_overlapping_choice_prefixes(sorted(line, key=lambda item: item['x0']))
            for line in lines
        ]

    def _split_overlapping_choice_prefixes(self, line: List[dict]) -> List[dict]:
        """Split choice symbols from a word when PDF coordinates hide punctuation inside it."""
        output = []
        choice_symbols = {'㉮', '㉯', '㉴', '㉵'}
        opening_marks = {'(', '[', '{'}

        for item in line:
            text = item.get('text', '')
            if not text or text[0] not in choice_symbols or len(text) == 1:
                output.append(item)
                continue

            has_hidden_opening_mark = any(
                other is not item
                and other.get('text', '')[:1] in opening_marks
                and item['x0'] < other['x0'] < item['x1']
                for other in line
            )
            if not has_hidden_opening_mark:
                output.append(item)
                continue

            marker = text[0]
            rest = text[1:]
            glyph_height = max(item['y1'] - item['y0'], 1.0)
            marker_width = min(glyph_height, (item['x1'] - item['x0']) / 2)
            rest_width = self._estimated_positioned_text_width(rest, glyph_height)
            rest_x0 = max(item['x0'] + marker_width, item['x1'] - rest_width)

            marker_item = dict(item)
            marker_item['text'] = marker
            marker_item['x1'] = item['x0'] + marker_width

            rest_item = dict(item)
            rest_item['text'] = rest
            rest_item['x0'] = rest_x0

            output.extend([marker_item, rest_item])

        return sorted(output, key=lambda item: item['x0'])

    @staticmethod
    def _estimated_positioned_text_width(text: str, glyph_height: float) -> float:
        width = 0.0
        for char in text:
            if char.isspace():
                width += glyph_height * 0.33
            elif char in {'(', ')', '[', ']', '{', '}', '/', '\\'}:
                width += glyph_height * 0.42
            elif unicodedata.east_asian_width(char) in {'F', 'W'} or '\u3130' <= char <= '\ud7a3':
                width += glyph_height
            else:
                width += glyph_height * 0.55
        return width

    def _join_positioned_line(self, line: List[dict], gap_threshold: float = 2.5) -> str:
        if not line:
            return ''

        output = [line[0]['text']]
        previous = line[0]
        for item in line[1:]:
            if self._needs_positioned_space(previous, item, gap_threshold=gap_threshold):
                output.append(' ')
            output.append(item['text'])
            previous = item
        return ''.join(output).strip()

    @staticmethod
    def _needs_positioned_space(previous: dict, current: dict, gap_threshold: float = 2.5) -> bool:
        gap = current['x0'] - previous['x1']
        if gap <= gap_threshold:
            return False

        current_text = current['text']
        previous_text = previous['text']
        if current_text[:1] in {'.', ',', '?', '!', ':', ';', ')', ']', '}', '˚'}:
            return False
        if previous_text[-1:] in {'(', '[', '{', '“', '"', "'"}:
            return False
        return True

    def _extract_text_tables(
        self,
        page,
        page_number: int = 1,
        source_path: Optional[Path] = None,
        table_image_dir: Optional[Path] = None,
    ) -> List[TableData]:
        """Extract native text tables when PyMuPDF can identify a stable table."""
        if not hasattr(page, 'find_tables'):
            return []
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                finder = page.find_tables()
        except Exception:
            return []

        tables = []
        for table_index, table in enumerate(getattr(finder, 'tables', []) or []):
            try:
                rows = table.extract()
            except Exception:
                continue
            cleaned_rows = []
            for row in rows or []:
                if not row:
                    continue
                cleaned = [
                    " ".join(str(cell or '').split())
                    for cell in row
                ]
                if any(cleaned):
                    cleaned_rows.append(cleaned)
            if not cleaned_rows:
                continue
            bbox = getattr(table, 'bbox', None)
            bbox = tuple(float(value) for value in bbox) if bbox else None
            row_count = len(cleaned_rows)
            column_count = max((len(row) for row in cleaned_rows), default=0)
            cells = self._native_table_cells(table, cleaned_rows)
            column_widths, row_heights = self._table_grid_proportions(
                table,
                row_count,
                column_count,
                bbox,
            )
            source = self._save_table_crop(
                page,
                bbox,
                page_number,
                source_path,
                table_image_dir,
                table_index,
            )
            tables.append(TableData(
                rows=cleaned_rows,
                bbox=bbox,
                cells=cells,
                column_widths=column_widths,
                row_heights=row_heights,
                source=source,
                confidence={'score': 0.96, 'reasons': ['native_grid', 'all_words_assigned']},
                complexity={
                    'has_formula': False,
                    'has_embedded_image': self._table_has_embedded_image(page, bbox),
                    'has_rotated_text': False,
                    'has_complex_merge': False,
                    'has_duplicate_text_risk': False,
                },
            ))
        return tables

    @staticmethod
    def _table_grid_proportions(table, row_count, column_count, bbox):
        """Return normalized grid dimensions using native cell rectangles when available."""
        if not bbox or not row_count or not column_count:
            return [], []
        raw_cells = [cell for cell in (getattr(table, 'cells', None) or []) if cell]
        x_edges = sorted({round(float(cell[0]), 3) for cell in raw_cells} | {
            round(float(cell[2]), 3) for cell in raw_cells
        })
        y_edges = sorted({round(float(cell[1]), 3) for cell in raw_cells} | {
            round(float(cell[3]), 3) for cell in raw_cells
        })
        if len(x_edges) != column_count + 1:
            x0, _, x1, _ = bbox
            step = (x1 - x0) / column_count
            x_edges = [x0 + step * index for index in range(column_count + 1)]
        if len(y_edges) != row_count + 1:
            _, y0, _, y1 = bbox
            step = (y1 - y0) / row_count
            y_edges = [y0 + step * index for index in range(row_count + 1)]
        width_total = max(1e-9, x_edges[-1] - x_edges[0])
        height_total = max(1e-9, y_edges[-1] - y_edges[0])
        widths = [
            round((x_edges[index + 1] - x_edges[index]) / width_total, 6)
            for index in range(column_count)
        ]
        heights = [
            round((y_edges[index + 1] - y_edges[index]) / height_total, 6)
            for index in range(row_count)
        ]
        return widths, heights

    @staticmethod
    def _native_table_cells(table, rows):
        """Convert native cell rectangles to row/column spans, including merges."""
        raw_rows = getattr(table, 'rows', None) or []
        raw_cells = [
            cell
            for raw_row in raw_rows
            for cell in (getattr(raw_row, 'cells', None) or [])
            if cell
        ]
        if not raw_cells:
            return [
                {
                    'row': row_index,
                    'col': column_index,
                    'text': cell_text,
                    'row_span': 1,
                    'col_span': 1,
                    'horizontal_alignment': 'left',
                    'vertical_alignment': 'center',
                }
                for row_index, row in enumerate(rows)
                for column_index, cell_text in enumerate(row)
            ]
        x_edges = sorted({round(float(cell[0]), 3) for cell in raw_cells} | {
            round(float(cell[2]), 3) for cell in raw_cells
        })
        y_edges = sorted({round(float(cell[1]), 3) for cell in raw_cells} | {
            round(float(cell[3]), 3) for cell in raw_cells
        })

        def edge_index(edges, value):
            return min(range(len(edges)), key=lambda index: abs(edges[index] - float(value)))

        cells = []
        for row_index, raw_row in enumerate(raw_rows):
            for source_col, rect in enumerate(getattr(raw_row, 'cells', None) or []):
                if rect is None:
                    continue
                start_col = edge_index(x_edges, rect[0])
                end_col = edge_index(x_edges, rect[2])
                start_row = edge_index(y_edges, rect[1])
                end_row = edge_index(y_edges, rect[3])
                text = (
                    rows[row_index][source_col]
                    if row_index < len(rows) and source_col < len(rows[row_index])
                    else ''
                )
                cells.append({
                    'row': start_row,
                    'col': start_col,
                    'text': text,
                    'row_span': max(1, end_row - start_row),
                    'col_span': max(1, end_col - start_col),
                    'horizontal_alignment': 'left',
                    'vertical_alignment': 'center',
                })
        return cells

    @staticmethod
    def _save_table_crop(
        page,
        bbox,
        page_number,
        source_path,
        table_image_dir,
        table_index,
    ):
        source = {
            'source_pdf_relative_path': Path(source_path).name if source_path else '',
            'page': int(page_number),
            'bbox': list(bbox) if bbox else [],
        }
        if not bbox or table_image_dir is None:
            source['missing_reason'] = 'crop_output_unavailable'
            return source
        try:
            table_image_dir = Path(table_image_dir)
            table_image_dir.mkdir(parents=True, exist_ok=True)
            temporary = table_image_dir / f'p{page_number}_table{table_index + 1}.png'
            pixmap = page.get_pixmap(clip=bbox, dpi=216, alpha=False)
            pixmap.save(str(temporary))
            digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
            target = table_image_dir / f'{digest}.png'
            if target != temporary:
                if target.exists():
                    temporary.unlink()
                else:
                    temporary.replace(target)
            source['image_path'] = str(target)
            source['sha256'] = digest
        except Exception as exc:
            source['missing_reason'] = exc.__class__.__name__
        return source

    @staticmethod
    def _table_has_embedded_image(page, bbox):
        if not bbox:
            return False
        try:
            x0, y0, x1, y1 = bbox
            for image in page.get_images(full=True) or []:
                for rect in page.get_image_rects(image[0]) or []:
                    if rect.x1 > x0 and rect.x0 < x1 and rect.y1 > y0 and rect.y0 < y1:
                        return True
        except Exception:
            return False
        return False

    def _extract_ocr_grid_tables(
        self,
        page,
        structured_page: StructuredPage,
        page_number: int,
        source_path: Optional[Path],
        table_image_dir: Path,
    ) -> List[TableData]:
        """Recover line-grid tables using OCR word geometry."""
        from src.parser.table_detection import detect_grid_tables

        horizontal, vertical = self._drawing_table_segments(page)
        words = []
        for line in structured_page.lines:
            for word in line.words:
                x0, y0, x1, y1 = word.bbox
                words.append({
                    'text': word.text,
                    'bbox': (
                        x0 * structured_page.width,
                        y0 * structured_page.height,
                        x1 * structured_page.width,
                        y1 * structured_page.height,
                    ),
                    'confidence': word.confidence,
                })
        detected = detect_grid_tables(horizontal, vertical, words)
        results = []
        for table_index, spec in enumerate(detected):
            bbox = tuple(spec['bbox'])
            source = self._save_table_crop(
                page,
                bbox,
                page_number,
                source_path,
                table_image_dir,
                table_index,
            )
            results.append(TableData(
                rows=spec['rows'],
                bbox=bbox,
                cells=spec['cells'],
                column_widths=spec['column_widths'],
                row_heights=spec['row_heights'],
                source=source,
                confidence=spec['confidence'],
                complexity=spec['complexity'],
            ))
        return results

    @staticmethod
    def _drawing_table_segments(page):
        horizontal = []
        vertical = []

        def point(value):
            try:
                return float(value.x), float(value.y)
            except AttributeError:
                return float(value[0]), float(value[1])

        try:
            drawings = page.get_drawings() or []
        except Exception:
            drawings = []
        for drawing in drawings:
            for item in drawing.get('items', []) if isinstance(drawing, dict) else []:
                if not item:
                    continue
                if item[0] == 'l' and len(item) >= 3:
                    x0, y0 = point(item[1])
                    x1, y1 = point(item[2])
                    segment = (x0, y0, x1, y1)
                    if abs(y1 - y0) <= 3:
                        horizontal.append(segment)
                    if abs(x1 - x0) <= 3:
                        vertical.append(segment)
                elif item[0] == 're' and len(item) >= 2:
                    rect = item[1]
                    try:
                        x0, y0, x1, y1 = (
                            float(rect.x0), float(rect.y0),
                            float(rect.x1), float(rect.y1),
                        )
                    except AttributeError:
                        x0, y0, x1, y1 = (float(value) for value in rect[:4])
                    horizontal.extend(((x0, y0, x1, y0), (x0, y1, x1, y1)))
                    vertical.extend(((x0, y0, x0, y1), (x1, y0, x1, y1)))
        return horizontal, vertical

    @staticmethod
    def _bbox_overlap_ratio(first, second):
        if not first or not second:
            return 0.0
        x0 = max(first[0], second[0])
        y0 = max(first[1], second[1])
        x1 = min(first[2], second[2])
        y1 = min(first[3], second[3])
        intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
        first_area = max(1e-9, first[2] - first[0]) * max(1e-9, first[3] - first[1])
        return intersection / first_area

    def _attach_native_text_decorations(
        self,
        structured_page: StructuredPage,
        source_page,
    ) -> StructuredPage:
        """Attach vector underline/overline ranges to structured text lines."""

        if not structured_page.lines:
            return structured_page
        try:
            segments = self._horizontal_line_segments(source_page)
        except Exception:
            return structured_page
        if not segments:
            return structured_page

        page_width = max(float(structured_page.width), 1.0)
        page_height = max(float(structured_page.height), 1.0)
        normalized = [
            (float(x0) / page_width, float(y) / page_height, float(x1) / page_width)
            for x0, y, x1 in segments
        ]
        underline_indexes = self._underline_candidate_line_indexes(structured_page)
        rewritten = []
        changed = False
        for line_index, line in enumerate(structured_page.lines):
            decorations = list(line.decorations)
            for x0, y, x1 in normalized:
                top = float(line.bbox[1])
                bottom = float(line.bbox[3])
                if line_index in underline_indexes and bottom - 0.0035 <= y <= bottom + 0.0022:
                    kind = "underline"
                    distance = abs(y - bottom)
                elif (
                    self._line_may_contain_overline(line.text)
                    and top - 0.009 <= y <= top - 0.0002
                ):
                    kind = "overline"
                    distance = abs(y - top)
                else:
                    continue
                decoration = self._decoration_for_horizontal_segment(
                    line,
                    x0,
                    x1,
                    y,
                    kind=kind,
                    source="native_vector",
                    confidence=max(0.72, 0.98 - distance * 20),
                )
                if decoration is not None:
                    decorations.append(decoration)
            decorations = self._deduplicate_text_decorations(decorations)
            if tuple(decorations) != line.decorations:
                line = replace(line, decorations=tuple(decorations))
                changed = True
            rewritten.append(line)
        return replace(structured_page, lines=tuple(rewritten)) if changed else structured_page

    @classmethod
    def _attach_raster_text_decorations(cls, page: StructuredPage, image) -> StructuredPage:
        """Recover sub-word underline/overline ranges from a rendered scan.

        OCR engines occasionally collapse an entire visual row into one word.
        Detection therefore works against line pixels and maps the horizontal
        run back to proportional character boxes instead of relying on OCR word
        boundaries alone.
        """

        if not page.lines:
            return page
        gray = image.convert("L")
        width, height = gray.size
        pixels = gray.load()
        underline_indexes = cls._underline_candidate_line_indexes(page)
        rewritten = []
        changed = False
        for line_index, line in enumerate(page.lines):
            found = list(line.decorations)
            top = float(line.bbox[1])
            bottom = float(line.bbox[3])
            bands = []
            if line_index in underline_indexes:
                # OCR boxes often include the underline itself.  Keep the band
                # tight around the baseline so the first strokes of the next
                # row and the enclosing view-box border cannot be selected.
                bands.append(("underline", bottom - 0.0035, bottom + 0.0022, 0.014, 0.88))
            if cls._line_may_contain_overline(line.text):
                bands.append(("overline", top - 0.0105, top - 0.0002, 0.0045, 0.88))
            for kind, band_start, band_end, minimum_ratio, minimum_density in bands:
                candidates = cls._horizontal_raster_runs(
                    pixels,
                    width,
                    height,
                    float(line.bbox[0]),
                    float(line.bbox[2]),
                    band_start,
                    band_end,
                    minimum_ratio=minimum_ratio,
                    minimum_density=minimum_density,
                )
                for x0, y, x1, density in candidates:
                    decoration = cls._decoration_for_horizontal_segment(
                        line,
                        x0,
                        x1,
                        y,
                        kind=kind,
                        source="raster_geometry",
                        confidence=min(0.99, 0.68 + 0.28 * density),
                    )
                    if decoration is not None:
                        found.append(decoration)
            found = cls._deduplicate_text_decorations(found)
            if tuple(found) != line.decorations:
                line = replace(line, decorations=tuple(found))
                changed = True
            rewritten.append(line)
        return replace(page, lines=tuple(rewritten)) if changed else page

    @staticmethod
    def _horizontal_raster_runs(
        pixels,
        width: int,
        height: int,
        line_x0: float,
        line_x1: float,
        y0: float,
        y1: float,
        *,
        minimum_ratio: float = 0.010,
        minimum_density: float = 0.88,
    ) -> list[tuple[float, float, float, float]]:
        left = max(0, min(width - 1, int((line_x0 - 0.006) * width)))
        right = max(left + 1, min(width, int((line_x1 + 0.006) * width)))
        top = max(0, min(height - 1, int(y0 * height)))
        bottom = max(top + 1, min(height, int(y1 * height) + 1))
        minimum = max(9, int(width * minimum_ratio))
        raw: list[tuple[int, int, int, float]] = []
        for y in range(top, bottom):
            dark = [pixels[x, y] < 150 for x in range(left, right)]
            index = 0
            while index < len(dark):
                while index < len(dark) and not dark[index]:
                    index += 1
                if index >= len(dark):
                    break
                start = index
                last_dark = index
                gaps = 0
                index += 1
                while index < len(dark):
                    if dark[index]:
                        last_dark = index
                        gaps = 0
                    else:
                        gaps += 1
                        if gaps > 2:
                            break
                    index += 1
                run_end = last_dark + 1
                run_width = run_end - start
                if run_width < minimum:
                    continue
                dark_count = sum(dark[start:run_end])
                density = dark_count / max(1, run_width)
                if density >= minimum_density:
                    raw.append((left + start, y, left + run_end, density))

        selected: list[tuple[int, int, int, float]] = []
        for candidate in sorted(raw, key=lambda item: (-item[3], -(item[2] - item[0]))):
            cx0, cy, cx1, _density = candidate
            duplicate = False
            for sx0, sy, sx1, _score in selected:
                overlap = max(0, min(cx1, sx1) - max(cx0, sx0))
                shorter = max(1, min(cx1 - cx0, sx1 - sx0))
                if abs(cy - sy) <= 4 and overlap / shorter >= 0.72:
                    duplicate = True
                    break
            if not duplicate:
                selected.append(candidate)
        return [
            (x0 / width, y / height, x1 / width, density)
            for x0, y, x1, density in selected
        ]

    @classmethod
    def _decoration_for_horizontal_segment(
        cls,
        line: LayoutLine,
        x0: float,
        x1: float,
        y: float,
        *,
        kind: str,
        source: str,
        confidence: float,
    ) -> TextDecoration | None:
        if x1 <= x0:
            return None
        mapped = cls._line_character_boxes(line)
        selected = [
            item for item in mapped
            if item[2] > x0 - 0.0015 and item[1] < x1 + 0.0015
        ]
        if not selected:
            return None
        start = min(item[0] for item in selected)
        end = max(item[0] for item in selected) + 1
        line_text = line.text
        while start < end and line_text[start].isspace():
            start += 1
        while end > start and line_text[end - 1].isspace():
            end -= 1
        if end <= start:
            return None
        if kind == "underline":
            # OCR may expose a whole printed row as one word.  Proportional
            # mapping can then land on ``. Thi`` or the last two letters of a
            # neighbouring word.  Snap to the lexical tokens actually crossed
            # by the visual rule; the subsequent width-fit rejects glyph
            # strokes that cover only a small part of the expanded token.
            tokens = list(re.finditer(r"[0-9A-Za-z가-힣]+(?:[-'][0-9A-Za-z가-힣]+)*", line_text))
            crossed = [token for token in tokens if token.end() > start and token.start() < end]
            if crossed:
                start = crossed[0].start()
                end = crossed[-1].end()
        text = line_text[start:end]
        compact = re.sub(r"\s+", "", text)
        if not compact or compact in {"보기", "<보기>", "＜보기＞", "〈보기〉"}:
            return None
        if kind == "underline" and len(compact) < 2:
            return None
        if kind == "overline" and not cls._text_may_be_overlined_formula(compact):
            return None
        phrase_boxes = [item for item in mapped if start <= item[0] < end]
        phrase_x0 = min(item[1] for item in phrase_boxes)
        phrase_x1 = max(item[2] for item in phrase_boxes)
        phrase_width = max(1e-6, phrase_x1 - phrase_x0)
        segment_width = x1 - x0
        fit_ratio = segment_width / phrase_width
        if fit_ratio < 0.60 or fit_ratio > 1.55:
            return None
        if segment_width > max(0.82 * (float(line.bbox[2]) - float(line.bbox[0])), phrase_width * 1.45):
            return None

        if kind == "overline":
            prefix = line_text[max(0, start - 4):start]
            if re.search(r"(?:√|\ue05c|sqrt)\s*$", prefix, re.IGNORECASE):
                kind = "radical"
        confidence = min(1.0, max(0.0, confidence - min(0.18, abs(1.0 - fit_ratio) * 0.18)))
        if confidence < 0.70:
            return None
        return TextDecoration(
            kind=kind,
            text=text,
            line_text=line_text,
            start=start,
            end=end,
            bbox=(x0, y, x1, y),
            confidence=confidence,
            source=source,
        )

    @staticmethod
    def _line_may_contain_overline(text: str) -> bool:
        """Limit overline recovery to mathematical/logical expressions.

        Scanning every OCR line treats glyph strokes and table borders as
        overlines.  Exam overlines occur in compact formula rows, normally
        beside an equality/logic operator or a radical sign.
        """

        value = str(text or "")
        if re.search(r"(?:√|\ue05c|sqrt)", value, re.IGNORECASE):
            return True
        if not re.search(r"[=≠≈≤≥¬⊕∨∧·∙×÷]", value):
            return False
        compact = re.sub(r"\s+", "", value)
        # A lone OCR digit beside an equals sign is a common failure mode in
        # scanned Korean body text.  Boolean/electrical overlines in this
        # corpus always contain at least two Latin symbols in the containing
        # expression (for example ``X=A·B``).  Requiring that context prevents
        # random glyph strokes from becoming ``\\overline{9}`` while still
        # allowing a single overlined operand such as ``A``.
        latin_symbols = re.findall(r"[A-Za-z]", compact)
        return len(compact) <= 120 and len(latin_symbols) >= 2

    @staticmethod
    def _text_may_be_overlined_formula(text: str) -> bool:
        compact = re.sub(r"\s+", "", str(text or ""))
        return bool(
            compact
            and len(compact) <= 48
            and re.fullmatch(r"[A-Za-z0-9_.·∙+\-−*/()]+", compact)
        )

    @staticmethod
    def _underline_candidate_line_indexes(page: StructuredPage) -> set[int]:
        """Return body lines belonging to a question that explicitly says 밑줄.

        This semantic gate is deliberately conservative.  It prevents page
        rules, table borders and ordinary Hangul strokes from being promoted
        to rich-text underline spans while retaining the exam convention in
        which an underlined target is introduced by the word ``밑줄``.
        """

        allowed: set[int] = set()
        for column in sorted({line.column for line in page.lines}):
            indexes = sorted(
                (index for index, line in enumerate(page.lines) if line.column == column),
                key=lambda index: float(page.lines[index].bbox[1]),
            )
            active = False
            prompt_finished = False
            for index in indexes:
                text = str(page.lines[index].text or "")
                starts_question = bool(_VISUAL_QUESTION_START.match(text))
                if starts_question:
                    active = "밑줄" in text
                    prompt_finished = False
                elif "밑줄" in text:
                    active = True
                if active and re.search(r"[?？]", text):
                    prompt_finished = True
                    continue
                if active and prompt_finished:
                    allowed.add(index)
        return allowed

    @staticmethod
    def _line_character_boxes(line: LayoutLine) -> list[tuple[int, float, float]]:
        boxes: list[tuple[int, float, float]] = []
        cursor = 0
        words = tuple(sorted(line.words, key=lambda word: word.bbox[0]))
        for word_index, word in enumerate(words):
            value = str(word.text)
            if word_index:
                cursor += 1
            length = max(1, len(value))
            x0 = float(word.bbox[0])
            x1 = float(word.bbox[2])
            for offset in range(len(value)):
                boxes.append((
                    cursor + offset,
                    x0 + (x1 - x0) * offset / length,
                    x0 + (x1 - x0) * (offset + 1) / length,
                ))
            cursor += len(value)
        return boxes

    @staticmethod
    def _deduplicate_text_decorations(values) -> list[TextDecoration]:
        selected: dict[tuple[str, int, int], TextDecoration] = {}
        for value in values or []:
            key = (str(value.kind), int(value.start), int(value.end))
            current = selected.get(key)
            if current is None or float(value.confidence) > float(current.confidence):
                selected[key] = value
        ordered = [selected[key] for key in sorted(selected, key=lambda item: (item[1], item[2], item[0]))]
        reduced: list[TextDecoration] = []
        for candidate in sorted(
            ordered,
            key=lambda item: (-float(item.confidence), -(int(item.end) - int(item.start))),
        ):
            duplicate = False
            for current in reduced:
                if current.kind != candidate.kind:
                    continue
                overlap = max(0, min(current.end, candidate.end) - max(current.start, candidate.start))
                shorter = max(1, min(current.end - current.start, candidate.end - candidate.start))
                if overlap / shorter >= 0.70:
                    duplicate = True
                    break
            if not duplicate:
                reduced.append(candidate)
        return sorted(reduced, key=lambda item: (item.start, item.end, item.kind))

    def _extract_underlined_texts(self, page) -> List[str]:
        """Detect underlined text snippets from horizontal drawing lines."""
        try:
            lines = self._horizontal_line_segments(page)
            raw = page.get_text("rawdict")
        except Exception:
            return []
        if not lines:
            return []

        chars = []
        for block in raw.get('blocks', []):
            for line in block.get('lines', []):
                for span in line.get('spans', []):
                    for char in span.get('chars', []):
                        value = char.get('c')
                        bbox = char.get('bbox')
                        if value and bbox:
                            chars.append((value, tuple(bbox)))

        snippets = []
        seen = set()
        for x0, y, x1 in lines:
            overlapping = []
            for value, bbox in chars:
                cx0, cy0, cx1, cy1 = bbox
                if cx1 < x0 or cx0 > x1:
                    continue
                if cy1 - 4 <= y <= cy1 + 3:
                    overlapping.append((value, bbox))

            if not overlapping:
                continue
            overlapping.sort(key=lambda item: (item[1][1], item[1][0]))
            groups = []
            current = []
            previous_bbox = None
            for item in overlapping:
                bbox = item[1]
                if (
                    previous_bbox is not None
                    and (abs(bbox[1] - previous_bbox[1]) > 3 or bbox[0] - previous_bbox[2] > 6)
                ):
                    groups.append(current)
                    current = []
                current.append(item)
                previous_bbox = bbox
            if current:
                groups.append(current)

            line_width = abs(x1 - x0)
            for group in groups:
                text = ''.join(item[0] for item in group).strip()
                if len(text) < 2:
                    continue
                gx0 = min(item[1][0] for item in group)
                gx1 = max(item[1][2] for item in group)
                if line_width > (gx1 - gx0) + 40:
                    continue
                if text not in seen:
                    snippets.append(text)
                    seen.add(text)

        return snippets

    def _extract_overlined_texts(self, page) -> List[OverlineData]:
        """Detect text snippets with a horizontal line above them."""
        try:
            lines = self._horizontal_line_segments(page)
            raw = page.get_text("rawdict")
        except Exception:
            return []
        if not lines:
            return []

        raw_lines = self._raw_text_lines(raw)
        marks = []
        seen = set()
        for x0, y, x1 in lines:
            for chars in raw_lines:
                marked_indices = []
                for index, item in enumerate(chars):
                    bbox = item['bbox']
                    cx0, cy0, cx1, cy1 = bbox
                    if cx1 <= x0 or cx0 >= x1:
                        continue
                    if cy0 - 4 <= y <= cy0 + 3:
                        marked_indices.append(index)

                if not marked_indices:
                    continue

                groups = self._contiguous_index_groups(marked_indices)
                line_width = abs(x1 - x0)
                for group in groups:
                    text = ''.join(chars[index]['value'] for index in group).strip()
                    if not text:
                        continue
                    gx0 = min(chars[index]['bbox'][0] for index in group)
                    gx1 = max(chars[index]['bbox'][2] for index in group)
                    if line_width > (gx1 - gx0) + 40:
                        continue
                    start = group[0]
                    end = group[-1] + 1
                    line_text = ''.join(item['value'] for item in chars)
                    key = (line_text, start, end, text)
                    if key in seen:
                        continue
                    marks.append(OverlineData(
                        text=text,
                        line_text=line_text,
                        start=start,
                        end=end,
                        bbox=(gx0, y, gx1, y),
                    ))
                    seen.add(key)

        return marks

    def _raw_text_lines(self, raw) -> List[List[dict]]:
        lines = []
        for block in raw.get('blocks', []):
            for line in block.get('lines', []):
                chars = []
                for span in line.get('spans', []):
                    for char in span.get('chars', []):
                        value = char.get('c')
                        bbox = char.get('bbox')
                        if value and bbox:
                            chars.append({'value': value, 'bbox': tuple(bbox)})
                if chars:
                    chars.sort(key=lambda item: item['bbox'][0])
                    lines.append(chars)
        return lines

    @staticmethod
    def _contiguous_index_groups(indices):
        groups = []
        current = []
        previous = None
        for index in sorted(indices):
            if previous is not None and index != previous + 1:
                groups.append(current)
                current = []
            current.append(index)
            previous = index
        if current:
            groups.append(current)
        return groups

    def _horizontal_line_segments(self, page) -> List[tuple]:
        segments = []
        for drawing in page.get_drawings():
            for item in drawing.get('items', []):
                kind = item[0]
                if kind == 'l':
                    p1, p2 = item[1], item[2]
                    if abs(p1.y - p2.y) <= 1 and abs(p2.x - p1.x) >= 5:
                        segments.append((min(p1.x, p2.x), (p1.y + p2.y) / 2, max(p1.x, p2.x)))
                elif kind == 're':
                    rect = item[1]
                    if rect.height <= 2 and rect.width >= 5:
                        segments.append((rect.x0, (rect.y0 + rect.y1) / 2, rect.x1))
        return segments
    
    def cleanup(self, pdf_path: str):
        """추출된 파일 정리"""
        import shutil
        extract_dir = self.output_dir / Path(pdf_path).stem
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
