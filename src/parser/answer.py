# src/parser/answer.py
"""정답지 파싱"""

import re
import asyncio
import io
from typing import Dict, List, Tuple, Optional
from .patterns import (
    ANSWER_SESSION_LIST,
    ANSWER_CHAR_TO_NUMBER, SUBJECT_NAME_TO_CODE, EXAM_SUBJECT_ORDER,
    ANSWER_GRID_NUMBERS, ANSWER_GRID_CHARS, SESSION_MARKER_2025
)

# ... (AnswerKey class is same)

class AnswerParser:
    """정답지 파싱"""

    # 세션 정보 탐지 (예: "2022년 제1회 정기시험", "2020 1")
    _SESSION_PATTERN = re.compile(
        r'(?:◎?\s*(\d{4})\s*년?\s*제?\s*(\d)\s*회?(?:\s*정기시험)?)'
        r'|(?:정기시험\s*(\d{4})\s*(\d))'
        r'|(?:\b(\d{4})[년\s]+(?:제\s*)?(\d)\b)'
    )

    # 헤더에서 시험 종류 추출
    _ANSWER_HEADER_PATTERN_1 = re.compile(
        r'<\s*(\d)\s*급\s*([가-힣]+사)\s*(?:\(([^)]+)\))?\s*답안?\s*>'
    )
    _ANSWER_HEADER_PATTERN_2 = re.compile(
        r'급\s*([가-힣]+사)\s*([가-힣 ]+?)?\s*답안\s*<\s*(\d+)\s*.*?>'
    )
    _ANSWER_HEADER_PATTERN_3 = re.compile(
        r'([가-힣]+)\s*답안\s*<\s*[^>]*>'
    )

    _ANSWER_CHARSETS = [
        ("가나다라", {'가': 1, '나': 2, '다': 3, '라': 4}),
        ("가나사아", {'가': 1, '나': 2, '사': 3, '아': 4}),
    ]
    
    def parse_answers(
        self,
        pages: List,
        exam_type: Optional[str] = None,
        year_hint: Optional[int] = None
    ) -> Dict[Tuple, List[int]]:
        """
        정답지에서 정답 추출
        
        Args:
            pages: PageData 리스트
            exam_type: 시험 유형 (예: '3급기관사')
            year_hint: 파일명에서 추출한 연도 힌트 (텍스트에 연도 없을 때 사용)
        """
        answers = {}
        
        for page in pages:
            text = page.text

            raw_exam_type = self._extract_exam_type(text)
            if exam_type and raw_exam_type and raw_exam_type != exam_type:
                continue
            detected_exam_type = raw_exam_type or exam_type

            answer_chars, answer_map = self._select_answer_mapping(text)
            multi_grid_answers = self._extract_multi_session_grid_answers(
                text,
                year_hint=year_hint,
                exam_type=detected_exam_type,
                answer_chars=answer_chars,
                answer_map=answer_map,
            )
            if multi_grid_answers:
                for (year, session, subject_name), answer_list in multi_grid_answers.items():
                    if detected_exam_type:
                        key = (year, session, detected_exam_type, subject_name)
                    else:
                        key = (year, session, subject_name)

                    if key in answers and len(answers[key]) >= len(answer_list):
                        continue
                    answers[key] = answer_list
                continue

            session_blocks = list(self._split_session_blocks(text, year_hint=year_hint))
            if not session_blocks and year_hint:
                session_blocks = list(self._split_session_blocks_by_marker(text, year_hint))
            if not session_blocks:
                first_session = self._find_first_session(text, year_hint=year_hint)
                if first_session:
                    session_blocks = [(first_session[0], first_session[1], text)]
            
            for year, session, block_text in session_blocks:
                subject_answers = self._extract_subject_answers(block_text)
                for subject_name, answer_list in subject_answers.items():
                    if detected_exam_type:
                        key = (year, session, detected_exam_type, subject_name)
                    else:
                        key = (year, session, subject_name)

                    # 이미 존재하면 더 긴 결과를 우선
                    if key in answers and len(answers[key]) >= len(answer_list):
                        continue
                    answers[key] = answer_list

        if not answers and self._needs_visual_ocr_fallback(pages):
            source_path = getattr(pages[0], 'source_path', None) if pages else None
            if source_path:
                page_numbers = [
                    getattr(page, 'number', None)
                    for page in pages
                    if getattr(page, 'number', None)
                ]
                answers = self._parse_visual_ocr_answers(
                    source_path,
                    exam_type=exam_type,
                    year_hint=year_hint,
                    page_numbers=page_numbers or None,
                )
        elif not answers:
            source_path = getattr(pages[0], 'source_path', None) if pages else None
            if source_path:
                page_numbers = self._matching_visual_answer_page_numbers(pages, exam_type)
                answers = self._parse_visual_ocr_answers(
                    source_path,
                    exam_type=exam_type,
                    year_hint=year_hint,
                    page_numbers=page_numbers or None,
                )
        
        return answers

    def _matching_visual_answer_page_numbers(
        self,
        pages: List,
        exam_type: Optional[str],
    ) -> List[int]:
        if not exam_type:
            return [
                getattr(page, 'number', None)
                for page in pages
                if getattr(page, 'number', None)
            ]

        target_norm = exam_type.replace(' ', '')
        matches = []
        for page in pages:
            page_number = getattr(page, 'number', None)
            if not page_number:
                continue
            text = getattr(page, 'text', '') or ''
            if self._visual_text_matches_exam_type(text, target_norm):
                matches.append(page_number)
        return matches

    def _needs_visual_ocr_fallback(self, pages: List) -> bool:
        if not pages:
            return False
        return all(not (getattr(page, 'text', '') or '').strip() for page in pages)

    def _parse_visual_ocr_answers(
        self,
        pdf_path: str,
        exam_type: Optional[str],
        year_hint: Optional[int],
        page_numbers: Optional[List[int]] = None,
    ) -> Dict[Tuple, List[int]]:
        try:
            return asyncio.run(
                self._parse_visual_ocr_answers_async(pdf_path, exam_type, year_hint, page_numbers)
            )
        except Exception:
            return {}

    async def _parse_visual_ocr_answers_async(
        self,
        pdf_path: str,
        exam_type: Optional[str],
        year_hint: Optional[int],
        page_numbers: Optional[List[int]] = None,
    ) -> Dict[Tuple, List[int]]:
        import fitz
        from PIL import Image
        from winrt.windows.graphics.imaging import BitmapDecoder
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

        engine = OcrEngine.try_create_from_language(Language('ko'))
        if engine is None:
            return {}

        doc = fitz.open(pdf_path)
        target_norm = (exam_type or '').replace(' ', '')
        subject_order = EXAM_SUBJECT_ORDER.get(exam_type or '', [])
        if not subject_order:
            subject_order = ['기관1', '기관2', '기관3', '직무일반', '영어']

        answers: Dict[Tuple, List[int]] = {}
        if page_numbers:
            page_indexes = [
                page_number - 1
                for page_number in page_numbers
                if 1 <= page_number <= doc.page_count
            ]
        else:
            page_indexes = list(range(doc.page_count))

        for page_index in page_indexes:
            page = doc[page_index]
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            image = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
            words, full_text = await self._ocr_image_words(image, engine, BitmapDecoder, DataWriter, InMemoryRandomAccessStream)
            if target_norm and not self._visual_text_matches_exam_type(full_text, target_norm):
                continue

            year = year_hint or self._extract_year_from_text(full_text)
            if not year:
                continue

            table_answers: Dict[int, Dict[str, List[int]]] = {}
            for zoom in (2, 3, 4, 5, 6):
                if zoom == 2:
                    zoom_image = image
                    zoom_words = words
                else:
                    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
                    zoom_image = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
                    zoom_words, _ = await self._ocr_image_words(
                        zoom_image,
                        engine,
                        BitmapDecoder,
                        DataWriter,
                        InMemoryRandomAccessStream
                    )
                zoom_answers = self._extract_answers_from_ocr_table(
                    zoom_image.convert('L'),
                    zoom_words,
                    subject_order,
                )
                self._merge_visual_answer_tables(table_answers, zoom_answers)

            for session, subject_map in table_answers.items():
                for subject, answer_list in subject_map.items():
                    if exam_type:
                        answers[(year, session, exam_type, subject)] = answer_list
                    else:
                        answers[(year, session, subject)] = answer_list

        return answers

    def _visual_text_matches_exam_type(self, text: str, target_norm: str) -> bool:
        compact = re.sub(r'\s+', '', text or '')
        if target_norm in compact:
            return True
        base = target_norm.split('(', 1)[0]
        return bool(base and base in compact)

    def _merge_visual_answer_tables(
        self,
        target: Dict[int, Dict[str, List[int]]],
        source: Dict[int, Dict[str, List[int]]],
    ) -> None:
        for session, subject_map in source.items():
            target.setdefault(session, {})
            for subject, answer_list in subject_map.items():
                current = target[session].get(subject, [])
                if len(answer_list) > len(current):
                    target[session][subject] = answer_list

    async def _ocr_image_words(self, image, engine, BitmapDecoder, DataWriter, InMemoryRandomAccessStream):
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

        words = []
        for line in result.lines:
            for word in line.words:
                rect = word.bounding_rect
                words.append({
                    'text': word.text,
                    'x': rect.x,
                    'y': rect.y,
                    'w': rect.width,
                    'h': rect.height,
                })
        return words, result.text or ''

    def _extract_year_from_text(self, text: str) -> Optional[int]:
        match = re.search(r'(20\d{2})', text or '')
        return int(match.group(1)) if match else None

    def _extract_answers_from_ocr_table(
        self,
        image,
        words: List[dict],
        subject_order: List[str],
    ) -> Dict[int, Dict[str, List[int]]]:
        positioned_fallback = self._extract_positioned_answer_rows(words, subject_order, image)
        h_lines = self._detect_horizontal_table_lines(image)
        if len(h_lines) < 7:
            return positioned_fallback

        table_lines = [h_lines[i:i + 7] for i in range(0, min(len(h_lines), 28), 7)]
        results: Dict[int, Dict[str, List[int]]] = {}
        for table_idx, lines in enumerate(table_lines, start=1):
            if len(lines) < 7:
                continue
            x_lines = self._detect_vertical_table_lines(image, lines[0], lines[-1])
            if len(x_lines) < 27:
                continue
            x_lines = x_lines[:27]

            subject_count = min(len(subject_order), 5)
            subject_map: Dict[str, List[int]] = {
                subject_order[row_idx]: []
                for row_idx in range(subject_count)
            }
            for word in words:
                chars = [ch for ch in word['text'] if ch in ANSWER_CHAR_TO_NUMBER]
                if len(chars) != 1:
                    continue
                cx = word['x'] + word['w'] / 2
                cy = word['y'] + word['h'] / 2
                row_idx = self._find_interval(lines[1:subject_count + 2], cy)
                col_idx = self._find_interval(x_lines[1:27], cx)
                if row_idx is None or col_idx is None:
                    continue
                if row_idx >= subject_count or col_idx >= 25:
                    continue
                subject_map[subject_order[row_idx]].append((col_idx, ANSWER_CHAR_TO_NUMBER[chars[0]]))

            cleaned: Dict[str, List[int]] = {}
            for subject, indexed_answers in subject_map.items():
                by_col = {}
                for col_idx, value in indexed_answers:
                    by_col.setdefault(col_idx, value)
                if len(by_col) >= 20:
                    cleaned[subject] = [by_col[col] for col in sorted(by_col)[:25]]
            if cleaned:
                results[table_idx] = cleaned

        if (
            self._answer_row_count(positioned_fallback),
            self._answer_value_count(positioned_fallback),
        ) > (
            self._answer_row_count(results),
            self._answer_value_count(results),
        ):
            return positioned_fallback
        return results or positioned_fallback

    def _answer_row_count(self, answers: Dict[int, Dict[str, List[int]]]) -> int:
        return sum(len(subject_map) for subject_map in (answers or {}).values())

    def _extract_positioned_answer_rows(
        self,
        words: List[dict],
        subject_order: List[str],
        image=None,
    ) -> Dict[int, Dict[str, List[int]]]:
        """Read scanned answer tables by grouping OCR answer letters into rows."""
        subject_count = len(subject_order)
        if subject_count <= 0:
            return {}

        candidates = []
        for word in words:
            text = str(word.get('text') or '').strip()
            chars = [char for char in text if char in ANSWER_CHAR_TO_NUMBER]
            if len(chars) != 1:
                continue
            x = float(word.get('x', 0))
            y = float(word.get('y', 0))
            w = float(word.get('w', 0))
            h = float(word.get('h', 0))
            candidates.append({
                'text': chars[0],
                'cx': x + w / 2,
                'cy': y + h / 2,
                'x': x,
                'y': y,
                'w': w,
                'h': h,
            })

        if len(candidates) < subject_count * 20:
            return {}

        candidates.sort(key=lambda item: (item['cy'], item['cx']))
        tolerance = max(12.0, self._median([item['h'] for item in candidates]) * 0.9)
        rows = []
        for item in candidates:
            if not rows or abs(item['cy'] - rows[-1]['cy']) > tolerance:
                rows.append({'cy': item['cy'], 'items': [item]})
            else:
                rows[-1]['items'].append(item)
                rows[-1]['cy'] = sum(row_item['cy'] for row_item in rows[-1]['items']) / len(rows[-1]['items'])

        answer_rows = []
        for row in rows:
            items = sorted(row['items'], key=lambda item: item['cx'])
            if len(items) < 20:
                continue
            spread = items[-1]['cx'] - items[0]['cx']
            if spread < 300:
                continue
            answer_rows.append({'cy': row['cy'], 'items': items})

        if not answer_rows:
            return {}

        if image is not None:
            self._recover_missing_answer_cells(image, answer_rows)

        labeled_results = self._extract_labeled_positioned_answer_rows(
            words,
            answer_rows,
            subject_order,
        )

        gap_groups = self._split_positioned_answer_tables(answer_rows)
        gap_results = self._map_positioned_row_groups(gap_groups, subject_order)

        count_groups = self._chunk_positioned_answer_tables(
            answer_rows,
            len(self._answer_table_row_order(subject_order)),
        )
        count_results = self._map_positioned_row_groups(count_groups, subject_order)

        return max(
            [labeled_results, gap_results, count_results],
            key=lambda result: (self._answer_row_count(result), self._answer_value_count(result)),
        )

    def _extract_labeled_positioned_answer_rows(
        self,
        words: List[dict],
        answer_rows: List[dict],
        subject_order: List[str],
    ) -> Dict[int, Dict[str, List[int]]]:
        subject_labels = self._subject_label_positions(words, subject_order)
        session_labels = self._session_label_positions(words)
        if not subject_labels:
            return {}

        row_gap = self._median([
            answer_rows[idx + 1]['cy'] - answer_rows[idx]['cy']
            for idx in range(len(answer_rows) - 1)
        ])
        subject_tolerance = max(28.0, row_gap * 0.45)

        results: Dict[int, Dict[str, List[int]]] = {}
        inferred_session = 1
        previous_subject_index = -1
        target_subjects = set(subject_order)

        for row in sorted(answer_rows, key=lambda item: item['cy']):
            subject = self._nearest_subject_for_row(row, subject_labels, subject_tolerance)
            if subject is None:
                continue

            session = self._nearest_session_for_row(row, session_labels)
            if session is None:
                subject_index = subject_order.index(subject) if subject in target_subjects else previous_subject_index
                if subject in target_subjects and subject_index <= previous_subject_index:
                    inferred_session += 1
                session = inferred_session
                if subject in target_subjects:
                    previous_subject_index = subject_index

            if session > 4 or subject not in target_subjects:
                continue

            values = [ANSWER_CHAR_TO_NUMBER[item['text']] for item in row['items'][:25]]
            if len(values) >= 20:
                current = results.setdefault(session, {}).get(subject, [])
                if len(values) > len(current):
                    results[session][subject] = values

        return results

    def _subject_label_positions(
        self,
        words: List[dict],
        subject_order: List[str],
    ) -> List[dict]:
        label_subjects = set(subject_order) | {'상선전문', '어선전문'}
        labels = []
        for word in words:
            subject = self._normalize_answer_subject_label(str(word.get('text') or ''))
            if subject not in label_subjects:
                continue
            x = float(word.get('x', 0))
            y = float(word.get('y', 0))
            w = float(word.get('w', 0))
            h = float(word.get('h', 0))
            labels.append({
                'subject': subject,
                'cx': x + w / 2,
                'cy': y + h / 2,
            })
        return labels

    def _normalize_answer_subject_label(self, value: str) -> str:
        normalized = re.sub(r'[\s\[\]\(\)<>]+', '', value or '')
        aliases = {
            '직무': '직무일반',
            '직무일반': '직무일반',
        }
        return aliases.get(normalized, normalized)

    def _session_label_positions(self, words: List[dict]) -> List[dict]:
        labels = []
        for word in words:
            text = re.sub(r'\s+', '', str(word.get('text') or ''))
            match = re.search(r'(?:제)?([1-4])회', text)
            if not match:
                continue
            x = float(word.get('x', 0))
            y = float(word.get('y', 0))
            w = float(word.get('w', 0))
            h = float(word.get('h', 0))
            labels.append({
                'session': int(match.group(1)),
                'cx': x + w / 2,
                'cy': y + h / 2,
            })
        return labels

    def _nearest_subject_for_row(
        self,
        row: dict,
        labels: List[dict],
        tolerance: float,
    ) -> Optional[str]:
        near_labels = [
            label
            for label in labels
            if abs(label['cy'] - row['cy']) <= tolerance
        ]
        if not near_labels:
            return None
        label = min(near_labels, key=lambda item: (abs(item['cy'] - row['cy']), item['cx']))
        return label['subject']

    def _nearest_session_for_row(
        self,
        row: dict,
        labels: List[dict],
    ) -> Optional[int]:
        if not labels:
            return None
        return min(labels, key=lambda item: abs(item['cy'] - row['cy']))['session']

    def _map_positioned_row_groups(
        self,
        table_groups: List[List[dict]],
        subject_order: List[str],
    ) -> Dict[int, Dict[str, List[int]]]:
        results: Dict[int, Dict[str, List[int]]] = {}
        row_order = self._answer_table_row_order(subject_order)
        for session, group in enumerate(table_groups, start=1):
            if session > 4:
                break
            for subject_idx, row in enumerate(group[:len(row_order)]):
                subject = row_order[subject_idx]
                if subject not in subject_order:
                    continue
                values = [ANSWER_CHAR_TO_NUMBER[item['text']] for item in row['items'][:25]]
                if len(values) >= 20:
                    results.setdefault(session, {})[subject] = values
        return results

    def _chunk_positioned_answer_tables(
        self,
        answer_rows: List[dict],
        subject_count: int,
    ) -> List[List[dict]]:
        rows = sorted(answer_rows, key=lambda row: row['cy'])
        groups = []
        for start in range(0, min(len(rows), subject_count * 4), subject_count):
            group = rows[start:start + subject_count]
            if len(group) == subject_count:
                groups.append(group)
        return groups

    def _answer_table_row_order(self, subject_order: List[str]) -> List[str]:
        if '상선전문' in subject_order or '어선전문' in subject_order:
            return ['항해', '운용', '법규', '영어', '상선전문', '어선전문']
        return subject_order

    def _answer_value_count(self, answers: Dict[int, Dict[str, List[int]]]) -> int:
        return sum(
            len(answer_list)
            for subject_map in (answers or {}).values()
            for answer_list in subject_map.values()
        )

    def _recover_missing_answer_cells(self, image, answer_rows: List[dict]) -> None:
        complete_rows = [
            row for row in answer_rows
            if len(row.get('items', [])) == 25
        ]
        if not complete_rows:
            return

        column_centers = []
        for col_idx in range(25):
            col_values = [
                row['items'][col_idx]['cx']
                for row in complete_rows
                if len(row.get('items', [])) == 25
            ]
            column_centers.append(self._median(col_values))

        cell_step = self._median([
            column_centers[idx + 1] - column_centers[idx]
            for idx in range(len(column_centers) - 1)
        ])
        if cell_step <= 0:
            return

        templates = self._answer_glyph_templates(image, complete_rows)
        if not templates:
            return

        for row in answer_rows:
            items = sorted(row.get('items', []), key=lambda item: item['cx'])
            if len(items) >= 25:
                row['items'] = items[:25]
                continue
            if len(items) < 20:
                continue

            recovered = list(items)
            for col_idx, cx in enumerate(column_centers):
                if any(abs(item['cx'] - cx) <= cell_step * 0.40 for item in recovered):
                    continue
                predicted = self._classify_answer_glyph(
                    image,
                    cx,
                    row['cy'],
                    templates,
                    cell_step,
                )
                if predicted:
                    recovered.append({
                        'text': predicted,
                        'cx': cx,
                        'cy': row['cy'],
                        'h': self._median([item.get('h', 0) for item in items]),
                    })
            row['items'] = sorted(recovered, key=lambda item: item['cx'])[:25]

    def _answer_glyph_templates(self, image, answer_rows: List[dict]) -> Dict[str, List[object]]:
        templates: Dict[str, List[object]] = {key: [] for key in ANSWER_CHAR_TO_NUMBER}
        sample_items = [
            item
            for row in answer_rows
            for item in row.get('items', [])
            if item.get('text') in templates
        ]
        for item in sample_items:
            if len(templates[item['text']]) >= 40:
                continue
            templates[item['text']].append(
                self._normalized_answer_glyph(image, item['cx'], item['cy'], item.get('h', 18))
            )
        return {key: value for key, value in templates.items() if value}

    def _classify_answer_glyph(
        self,
        image,
        cx: float,
        cy: float,
        templates: Dict[str, List[object]],
        cell_step: float,
    ) -> Optional[str]:
        sample = self._normalized_answer_glyph(image, cx, cy, cell_step * 0.55)
        best_char = None
        best_score = None
        for char, char_templates in templates.items():
            for template in char_templates:
                score = self._glyph_difference(sample, template)
                if best_score is None or score < best_score:
                    best_score = score
                    best_char = char
        return best_char

    def _normalized_answer_glyph(self, image, cx: float, cy: float, size_hint: float):
        from PIL import ImageOps

        half = max(14, int(size_hint * 0.9))
        box = (
            max(0, int(cx - half)),
            max(0, int(cy - half)),
            min(image.width, int(cx + half)),
            min(image.height, int(cy + half)),
        )
        crop = image.crop(box).convert('L')
        crop = ImageOps.autocontrast(crop)
        crop = crop.resize((28, 28))
        return crop.point(lambda pixel: 0 if pixel < 180 else 255)

    def _glyph_difference(self, left, right) -> float:
        from PIL import ImageChops, ImageStat

        diff = ImageChops.difference(left, right)
        stat = ImageStat.Stat(diff)
        return stat.mean[0]

    def _split_positioned_answer_tables(self, answer_rows: List[dict]) -> List[List[dict]]:
        if len(answer_rows) <= 1:
            return [answer_rows]

        rows = sorted(answer_rows, key=lambda row: row['cy'])
        gaps = [
            rows[idx + 1]['cy'] - rows[idx]['cy']
            for idx in range(len(rows) - 1)
        ]
        normal_gap = self._median(gaps)
        threshold = max(normal_gap * 1.55, 45.0)

        groups = [[rows[0]]]
        for idx, gap in enumerate(gaps):
            next_row = rows[idx + 1]
            if gap > threshold:
                groups.append([next_row])
            else:
                groups[-1].append(next_row)
        return groups

    def _median(self, values: List[float]) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        mid = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[mid]
        return (ordered[mid - 1] + ordered[mid]) / 2

    def _detect_horizontal_table_lines(self, image) -> List[int]:
        width, height = image.size
        pixels = image.load()
        raw = []
        in_run = False
        start = 0
        threshold = int(width * 0.45)
        for y in range(height):
            count = sum(1 for x in range(width) if pixels[x, y] < 80)
            if count > threshold and not in_run:
                start = y
                in_run = True
            elif (count <= threshold or y == height - 1) and in_run:
                end = y - 1
                in_run = False
                raw.append((start + end) // 2)

        grouped = []
        for y in raw:
            if grouped and y - grouped[-1] <= 10:
                grouped[-1] = (grouped[-1] + y) // 2
            else:
                grouped.append(y)
        return grouped

    def _detect_vertical_table_lines(self, image, y_start: int, y_end: int) -> List[int]:
        width, _ = image.size
        pixels = image.load()
        raw = []
        in_run = False
        start = 0
        span = max(1, y_end - y_start)
        threshold = int(span * 0.80)
        for x in range(width):
            count = sum(1 for y in range(y_start, y_end + 1) if pixels[x, y] < 80)
            if count > threshold and not in_run:
                start = x
                in_run = True
            elif (count <= threshold or x == width - 1) and in_run:
                end = x - 1
                in_run = False
                raw.append((start + end) // 2)

        return raw

    def _find_interval(self, boundaries: List[int], value: float) -> Optional[int]:
        for idx in range(len(boundaries) - 1):
            if boundaries[idx] <= value <= boundaries[idx + 1]:
                return idx
        return None

    def _extract_subject_answers(self, text: str) -> Dict[str, List[int]]:
        """
        과목별 정답 추출 (Tri-Mode: Grid → Table → Legacy)
        """
        answer_chars, answer_map = self._select_answer_mapping(text)

        # 1. Grid 모드 시도 (2025 형식: 과목명 + 정답열)
        grid_results = self._extract_grid_answers(text, answer_chars, answer_map)
        if grid_results:
            return grid_results
        
        # 2. Table 모드 시도 (2020 형식: 회차별 표)
        table_results = self._extract_table_answers(text, answer_chars, answer_map)
        if table_results:
            return table_results
        
        # 3. Legacy 모드 (2020-2022 형식)
        return self._extract_legacy_answers(text, answer_chars, answer_map)

    def _extract_multi_session_grid_answers(
        self,
        text: str,
        year_hint: Optional[int],
        exam_type: Optional[str],
        answer_chars: str,
        answer_map: Dict[str, int],
    ) -> Dict[Tuple[int, int, str], List[int]]:
        lines = [line.strip() for line in (text or '').splitlines() if line.strip()]
        if not lines:
            return {}

        result: Dict[Tuple[int, int], Dict[str, List[int]]] = {}
        session_order: List[Tuple[int, int]] = []
        discovered_subject_order: List[str] = []
        continuation_groups: List[List[List[int]]] = []
        subject_candidates = sorted(list(SUBJECT_NAME_TO_CODE.keys()), key=len, reverse=True)

        i = 0
        while i < len(lines):
            session_info = self._parse_session_line(lines[i], year_hint)
            if session_info:
                if session_info not in session_order:
                    session_order.append(session_info)
                result.setdefault(session_info, {})
                i += 1
                if i < len(lines) and self._is_answer_number_row(lines[i]):
                    i += 1

                subjects_in_block = []
                while i < len(lines):
                    if self._parse_session_line(lines[i], year_hint) or self._is_answer_number_row(lines[i]):
                        break
                    subject, row_answers = self._parse_subject_answer_line(
                        lines[i],
                        subject_candidates,
                        answer_chars,
                        answer_map,
                    )
                    if subject and row_answers:
                        result[session_info].setdefault(subject, []).extend(row_answers)
                        subjects_in_block.append(subject)
                    i += 1

                if subjects_in_block and not discovered_subject_order:
                    discovered_subject_order = subjects_in_block
                continue

            if self._is_answer_number_row(lines[i]):
                rows = []
                i += 1
                while i < len(lines):
                    if self._parse_session_line(lines[i], year_hint) or self._is_answer_number_row(lines[i]):
                        break
                    _, row_answers = self._parse_subject_answer_line(
                        lines[i],
                        subject_candidates,
                        answer_chars,
                        answer_map,
                    )
                    if not row_answers:
                        row_answers = self._parse_answer_line(lines[i], answer_chars, answer_map)
                    if row_answers:
                        rows.append(row_answers)
                    i += 1
                if rows:
                    continuation_groups.append(rows)
                continue

            i += 1

        if not session_order:
            return {}

        subject_order = EXAM_SUBJECT_ORDER.get(exam_type or '', []) or discovered_subject_order
        if subject_order and continuation_groups:
            for group_idx, rows in enumerate(continuation_groups):
                if group_idx >= len(session_order):
                    break
                session_key = session_order[group_idx]
                result.setdefault(session_key, {})
                for row_idx, row_answers in enumerate(rows):
                    if row_idx >= len(subject_order):
                        break
                    subject = subject_order[row_idx]
                    result[session_key].setdefault(subject, []).extend(row_answers)

        flattened: Dict[Tuple[int, int, str], List[int]] = {}
        for (year, session), subject_map in result.items():
            for subject, answer_list in subject_map.items():
                if 20 <= len(answer_list) <= 30:
                    flattened[(year, session, subject)] = answer_list[:25]

        return flattened

    def _parse_session_line(
        self,
        line: str,
        year_hint: Optional[int],
    ) -> Optional[Tuple[int, int]]:
        match = self._SESSION_PATTERN.search(line)
        if match:
            year, session = self._parse_session_match(match)
            if year and session and self._is_valid_year(year, year_hint):
                return year, session

        compact = re.sub(r'\s+', '', line or '')
        compact_match = re.search(r'(20\d{2})년?제회(\d)', compact)
        if compact_match:
            year = int(compact_match.group(1))
            session = int(compact_match.group(2))
            if self._is_valid_year(year, year_hint):
                return year, session

        if year_hint:
            session_match = SESSION_MARKER_2025.search(line)
            if session_match:
                return year_hint, int(session_match.group(1))

        return None

    def _is_answer_number_row(self, line: str) -> bool:
        numbers = [int(token) for token in re.findall(r'\b\d{1,2}\b', line or '')]
        if len(numbers) < 5:
            return False
        if not all(1 <= number <= 25 for number in numbers):
            return False
        remainder = re.sub(r'[\d\s]+', '', line or '')
        return not re.search(r'[A-Za-z가-힣]', remainder)

    def _parse_subject_answer_line(
        self,
        line: str,
        subject_candidates: List[str],
        answer_chars: str,
        answer_map: Dict[str, int],
    ) -> Tuple[Optional[str], List[int]]:
        subject, end_idx = self._match_subject_prefix(line, subject_candidates)
        if not subject:
            return None, []
        return subject, self._parse_answer_line(line[end_idx:], answer_chars, answer_map)

    def _parse_answer_line(
        self,
        line: str,
        answer_chars: str,
        answer_map: Dict[str, int],
    ) -> List[int]:
        char_class = ''.join(re.escape(c) for c in answer_chars)
        return [answer_map[c] for c in re.findall(rf'[{char_class}]', line or '')]
    
    def _extract_grid_answers(
        self,
        text: str,
        answer_chars: str,
        answer_map: Dict[str, int],
    ) -> Dict[str, List[int]]:
        """
        2025 Grid 형식 정답 추출
        과목명(기관1, 기관2, ...) + 정답 문자열(가 나 사 아...) 패턴
        """
        results: Dict[str, List[int]] = {}
        
        # 2025 정답지에서 과목명 찾기
        subject_candidates = [
            '기관1', '기관2', '기관3', '기관', '직무일반', '영어',
            '상선전문', '어선전문', '항해', '운용', '법규'
        ]
        
        # 과목명 위치 찾기 (공백 무시)
        subject_matches = []
        for subject in subject_candidates:
            # 공백이 포함된 경우도 처리 (예: "기 관 1")
            pattern = r'\s*'.join([re.escape(c) for c in subject])
            for m in re.finditer(pattern, text):
                subject_matches.append((m.start(), m.end(), subject))
        
        if not subject_matches:
            return {}  # 과목명 없음 → Legacy로 fallback
        
        # 위치 순으로 정렬
        subject_matches.sort()
        char_class = ''.join(re.escape(c) for c in answer_chars)
        answer_pattern = re.compile(rf'[{char_class}]')
        
        for idx, (start, end, subject) in enumerate(subject_matches):
            # 다음 과목 시작까지를 해당 과목의 정답 블록으로
            block_end = subject_matches[idx + 1][0] if idx + 1 < len(subject_matches) else len(text)
            block_content = text[end:block_end]
            
            # 정답 문자만 추출
            answers = [answer_map[c] for c in answer_pattern.findall(block_content)]
            
            # 20~25개 정답이 있으면 유효한 과목 정답
            if 20 <= len(answers) <= 30:
                # 이미 존재하면 더 긴 결과 우선
                if subject in results and len(results[subject]) >= len(answers):
                    continue
                results[subject] = answers[:25]
        
        return results
    
    def _extract_table_answers(
        self,
        text: str,
        answer_chars: str,
        answer_map: Dict[str, int],
    ) -> Dict[str, List[int]]:
        """
        2020 Table 형식 정답 추출
        단일 페이지에 여러 과목 정답이 연속으로 나열된 형식
        예: "직종과목12345...25제2회3급기관사[기관1답...][기관2답...]"
        """
        results: Dict[str, List[int]] = {}
        
        char_class = ''.join(re.escape(c) for c in answer_chars)
        answer_pattern = re.compile(rf'[{char_class}]')

        # 정답 문자만 추출
        all_answers = [answer_map[c] for c in answer_pattern.findall(text)]
        
        # 125개 정답 = 5과목 × 25문항 형식인지 확인
        if len(all_answers) < 100:
            return {}  # Table 패턴 미충족
        
        # 과목 순서: 텍스트 내 등장 순서 우선, 없으면 기본값
        subject_candidates = ['기관1', '기관2', '기관3', '직무일반', '영어']
        positions = [(text.find(subject), subject) for subject in subject_candidates if text.find(subject) != -1]
        if len(positions) >= 3:
            subject_order = [subject for _, subject in sorted(positions)]
        else:
            subject_order = subject_candidates
        
        # 25개씩 분할하여 과목에 할당
        for idx, subject in enumerate(subject_order):
            start_idx = idx * 25
            end_idx = start_idx + 25
            if end_idx <= len(all_answers):
                results[subject] = all_answers[start_idx:end_idx]
        
        return results
    
    def _extract_legacy_answers(
        self,
        text: str,
        answer_chars: str,
        answer_map: Dict[str, int],
    ) -> Dict[str, List[int]]:
        """과목별 정답 추출 (Legacy: 과목명 기반 검색)"""
        results: Dict[str, List[int]] = {}

        # 후보 과목 이름 목록 (긴 이름 우선)
        subject_candidates = sorted(list(SUBJECT_NAME_TO_CODE.keys()), key=len, reverse=True)
        subject_aliases = {'항해사': '항해'}

        # 모든 과목 위치 찾기
        subject_matches = []
        for subject in subject_candidates:
            # 공백 무시하고 과목명 탐지 (예: "기 관 1")
            pattern = "".join([re.escape(c) + r"\s*" for c in subject])
            for m in re.finditer(pattern, text):
                subject_matches.append((m.start(), m.end(), subject))
        
        # 위치 순으로 정렬
        subject_matches.sort()

        for idx, (start, end, subject) in enumerate(subject_matches):
            canonical = subject_aliases.get(subject, subject)
            
            # 다음 과목 시작 전까지를 해당 과목 블록으로 간주
            block_end = subject_matches[idx + 1][0] if idx + 1 < len(subject_matches) else len(text)
            block_content = text[end:block_end]
            
            answers = self._parse_answer_string(block_content, answer_chars, answer_map)
            
            # 과목별 20문항 또는 25문항 대응
            if answers:
                # 이미 존재하면 더 긴 결과를 우선 (중복 탐지 방지)
                if canonical in results and len(results[canonical]) >= len(answers):
                    continue
                results[canonical] = answers
        
        return results
    
    def _parse_answer_string(
        self,
        answer_str: str,
        answer_chars: str,
        answer_map: Dict[str, int],
    ) -> List[int]:
        """정답 문자열 → 번호 리스트 (오탐 방지 강화)"""
        char_class = ''.join(re.escape(c) for c in answer_chars)
        seq_pattern = re.compile(rf'(?:[{char_class}]\s*){{5,}}')
        matches = seq_pattern.findall(answer_str)
        if not matches:
            return []
        seq = max(matches, key=len)
        letters = re.findall(rf'[{char_class}]', seq)
        found = [answer_map[c] for c in letters]
        
        # 20문항 또는 25문항 단위로 유효성 판단 (너무 짧으면 무시)
        if len(found) < 5:
            return []
        return found

    def _match_subject_prefix(self, line: str, candidates: List[str]) -> Tuple[Optional[str], int]:
        """과목명 매칭 (공백 무시)"""
        line_norm = ""
        mapping = []
        for idx, char in enumerate(line):
            if not char.isspace():
                mapping.append(idx)
                line_norm += char
        
        for subject in candidates:
            if line_norm.startswith(subject):
                end_idx = mapping[len(subject)-1] + 1
                return subject, end_idx
        return None, 0

    def _split_session_blocks(self, text: str, year_hint: Optional[int] = None):
        matches = list(self._SESSION_PATTERN.finditer(text))
        for idx, match in enumerate(matches):
            year, session = self._parse_session_match(match)
            if not year or not session:
                continue
            if not self._is_valid_year(year, year_hint):
                continue
            start = match.end()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            yield year, session, text[start:end]

    def _split_session_blocks_by_marker(self, text: str, year_hint: int):
        matches = list(SESSION_MARKER_2025.finditer(text))
        for idx, match in enumerate(matches):
            session = int(match.group(1))
            start = match.end()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            yield year_hint, session, text[start:end]

    def _parse_session_match(self, match: re.Match) -> Tuple[Optional[int], Optional[int]]:
        if match.group(1) and match.group(2):
            return int(match.group(1)), int(match.group(2))
        if match.group(3) and match.group(4):
            return int(match.group(3)), int(match.group(4))
        if match.group(5) and match.group(6):
            return int(match.group(5)), int(match.group(6))
        return None, None

    def _find_first_session(self, text: str, year_hint: Optional[int] = None) -> Optional[Tuple[int, int]]:
        """
        첫 번째 세션 정보 탐지
        
        Args:
            text: 검색할 텍스트
            year_hint: 파일명 등에서 추출한 연도 힌트 (텍스트에 연도 없을 때 사용)
        """
        # 1. 연도 + 회차 패턴 시도
        for pattern in ANSWER_SESSION_LIST:
            session_match = pattern.search(text)
            if session_match:
                year = int(session_match.group(1))
                session = int(session_match.group(2))
                if self._is_valid_year(year, year_hint):
                    return year, session
        
        # 2. 회차만 있는 패턴 (제N회) - 연도 힌트 필요
        if year_hint:
            session_only = SESSION_MARKER_2025.search(text)
            if session_only:
                return year_hint, int(session_only.group(1))
        
        # 3. 텍스트에서 연도 추출 시도 + 회차 패턴
        year_match = re.search(r'(20\d{2})', text)
        if year_match:
            year = int(year_match.group(1))
            session_only = SESSION_MARKER_2025.search(text)
            if session_only:
                return year, int(session_only.group(1))
        
        return None

    def _is_valid_year(self, year: int, year_hint: Optional[int]) -> bool:
        if year_hint:
            return abs(year - year_hint) <= 1
        return 1980 <= year <= 2100

    def _select_answer_mapping(self, text: str) -> Tuple[str, Dict[str, int]]:
        best_score = -1
        best_chars = ''.join(ANSWER_CHAR_TO_NUMBER.keys())
        best_map = ANSWER_CHAR_TO_NUMBER

        for chars, mapping in self._ANSWER_CHARSETS:
            char_class = ''.join(re.escape(c) for c in chars)
            seq_pattern = re.compile(rf'(?:[{char_class}]\s*){{10,}}')
            score = sum(len(m) for m in seq_pattern.findall(text))
            if score > best_score:
                best_score = score
                best_chars = chars
                best_map = mapping

        return best_chars, best_map

    def _extract_exam_type(self, text: str) -> Optional[str]:
        if '소형선박조종사' in text:
            return '소형선박조종사'

        compact = re.sub(r'\s+', '', text or '')
        compact_match = re.search(
            r'<([1-6])급(항해사|기관사)(상선|어선|국내한정|국내)?답안',
            compact
        )
        if compact_match:
            return self._normalize_exam_type(
                compact_match.group(1),
                compact_match.group(2),
                compact_match.group(3)
            )

        # 패턴 1: "< 3급 기관사 > 답안"
        match = self._ANSWER_HEADER_PATTERN_1.search(text)
        if match:
            grade = match.group(1)
            role = match.group(2)
            qualifier = match.group(3)
            return self._normalize_exam_type(grade, role, qualifier)

        # 패턴 2: "급 항해사 상선 답안 < 1 ( ) >"
        match = self._ANSWER_HEADER_PATTERN_2.search(text)
        if match:
            role = match.group(1)
            qualifier = match.group(2)
            grade = match.group(3)
            return self._normalize_exam_type(grade, role, qualifier)

        # 패턴 3: "소형선박조종사 답안 < >" (급 정보 없음)
        match = self._ANSWER_HEADER_PATTERN_3.search(text)
        if match:
            role = match.group(1).replace(' ', '')
            return role

        return None

    def _normalize_exam_type(
        self,
        grade: str,
        role: str,
        qualifier: Optional[str]
    ) -> str:
        exam_type = f"{grade}급{role}".replace(' ', '')
        if qualifier:
            qualifier = qualifier.replace('국내한정', '국내').strip()
            parts = []
            if '국내' in qualifier:
                parts.append('국내')
            if '상선' in qualifier:
                parts.append('상선')
            if '어선' in qualifier:
                parts.append('어선')

            normalized = ' '.join(parts) if parts else qualifier
            exam_type = f"{exam_type}({normalized})"
        return exam_type
