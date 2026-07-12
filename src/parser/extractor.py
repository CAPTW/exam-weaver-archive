# src/parser/extractor.py
"""PDF(ZIP) 파일에서 텍스트 추출"""

import zipfile
import json
import os
import io
import contextlib
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, field
import pypdf
import logging

from src.parser.layout import StructuredPage, build_structured_page

logging.getLogger("pypdf").setLevel(logging.ERROR)


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
        if native_page.kind == 'image_with_fake_text_layer':
            return native_page

        has_embedded_images = bool(native_page.images)
        if self._should_use_ocr_fallback(native_page.text, has_embedded_images):
            ocr_page = self._extract_ocr_structured_page(page, page_number)
            if ocr_page.lines:
                return ocr_page
        return native_page

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
        return build_structured_page(
            words,
            page_number=page_number,
            width=width,
            height=height,
            source='native',
            images=images,
        )

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
                    if self._should_use_ocr_fallback(text, bool(embedded_images)):
                        ocr_cache_path = ocr_out_dir / f"{i + 1}.txt"
                        if ocr_cache_path.exists():
                            ocr_text = ocr_cache_path.read_text(encoding='utf-8')
                        else:
                            ocr_text = (
                                self._structured_page_text(structured_page)
                                if structured_page.kind == 'scanned'
                                else self._extract_ocr_text(fitz_page)
                            )
                            if ocr_text.strip():
                                ocr_cache_path.write_text(ocr_text, encoding='utf-8')
                        if ocr_text.strip():
                            if not text.strip() or len(ocr_text.strip()) > len(text.strip()):
                                text = ocr_text
                            is_ocr_text = True
                    underlined_texts = self._extract_underlined_texts(fitz_page)
                    overlined_texts = self._extract_overlined_texts(fitz_page)
                    tables = self._extract_text_tables(fitz_page)
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

    async def _extract_ocr_structured_page_async(self, page, page_number: int) -> StructuredPage:
        try:
            import fitz
            from PIL import Image
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
        zoom = 3.0
        if page_width > 0 and page_height > 0:
            zoom = min(zoom, 2200 / page_width, 3000 / page_height)
            zoom = max(0.5, zoom)

        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        image = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')

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

        items = []
        scale_x = page_width / image.width if page_width > 0 else 1.0
        scale_y = page_height / image.height if page_height > 0 else 1.0
        if page_width <= 0:
            page_width = float(image.width)
        if page_height <= 0:
            page_height = float(image.height)
        detected_split = self._detect_vertical_column_split(image)
        column_split_x = detected_split * scale_x if detected_split is not None else None
        for line in result.lines:
            for word in line.words:
                value = str(word.text or '').strip()
                if not value:
                    continue
                rect = word.bounding_rect
                x0 = float(rect.x) * scale_x
                y0 = float(rect.y) * scale_y
                x1 = x0 + float(rect.width) * scale_x
                y1 = y0 + float(rect.height) * scale_y
                confidence = getattr(word, 'confidence', None)
                items.append({
                    'text': value,
                    'bbox': (x0, y0, x1, y1),
                    'confidence': confidence,
                })

        return build_structured_page(
            items,
            page_number=page_number,
            width=page_width,
            height=page_height,
            source='ocr',
            images=((0.0, 0.0, page_width, page_height),),
            divider_x=column_split_x,
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

        # Exam pages can contain boxed right-column questions; choose the first
        # long central divider so those box borders do not become the split.
        first_group = groups[0]
        divider_split = float(sum(first_group) / len(first_group))
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

    def _extract_text_tables(self, page) -> List[TableData]:
        """Extract native text tables when PyMuPDF can identify a stable table."""
        if not hasattr(page, 'find_tables'):
            return []
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                finder = page.find_tables()
        except Exception:
            return []

        tables = []
        for table in getattr(finder, 'tables', []) or []:
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
            tables.append(TableData(rows=cleaned_rows, bbox=tuple(bbox) if bbox else None))
        return tables

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
