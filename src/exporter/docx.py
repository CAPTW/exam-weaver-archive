# src/exporter/docx.py
"""Word 문서(DOCX) 내보내기"""

from docx import Document
from docx.shared import Pt, Mm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.text import WD_COLOR_INDEX
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from pathlib import Path
import logging
import random
import json
import io
import re

from ..parser.formatting import normalize_private_math_glyphs, repair_extracted_text_artifacts
from ..parser.patterns import NUMBER_TO_CHOICE_SYMBOL, CHOICE_SYMBOL_TO_NUMBER

logger = logging.getLogger(__name__)

class DocxExporter:
    FONT_NAME = '경기천년제목OTF Light'
    BODY_LINE_TWIPS = '160'
    COLUMN_SPACE_TWIPS = '425'

    def __init__(self):
        pass

    def export(
        self,
        title: str,
        questions: list,
        output_path: str,
        shuffle_choices: bool = False,
        include_answer_key: bool = False,
        sections: list = None
    ):
        """
        Export questions to a DOCX document matching the exam handout style.

        Args:
            title: Document title. Use newlines for title/subtitle lines.
            questions: Questions to export.
            output_path: Destination DOCX path.
            shuffle_choices: Shuffle four-choice options before rendering.
            include_answer_key: Append a separate answer key page when needed.
            sections: Optional grouped sections, each with title and questions.
        """
        doc = Document()

        self._set_document_defaults(doc)

        section = doc.sections[0]
        section.page_width = Mm(210)
        section.page_height = Mm(297)
        section.left_margin = Mm(15)
        section.right_margin = Mm(15)
        section.top_margin = Mm(15)
        section.bottom_margin = Mm(15)

        self._set_columns(section, 2)

        for title_line in self._split_title(title):
            header = doc.add_paragraph()
            self._format_paragraph(header, alignment=WD_ALIGN_PARAGRAPH.CENTER)
            run = header.add_run(f"{title_line} ")
            self._format_run(run, size_pt=16, bold=True)

        rng = random.Random()
        answer_key = []
        display_number = 1
        if sections:
            for section_spec in sections:
                last_group_id = None
                section_title = (section_spec or {}).get('title')
                if section_title:
                    self._add_subject_heading(doc, section_title)
                    spacer = doc.add_paragraph()
                    self._format_paragraph(spacer)
                for q in (section_spec or {}).get('questions') or []:
                    last_group_id = self._add_group_shared_passage_if_needed(
                        doc,
                        q,
                        last_group_id,
                    )
                    answer = self._add_question(
                        doc,
                        q,
                        display_number=display_number,
                        shuffle_choices=shuffle_choices,
                        rng=rng
                    )
                    answer_key.append((display_number, answer))
                    display_number += 1
                    spacer = doc.add_paragraph()
                    self._format_paragraph(spacer)
        else:
            last_group_id = None
            for q in questions:
                last_group_id = self._add_group_shared_passage_if_needed(
                    doc,
                    q,
                    last_group_id,
                )
                answer = self._add_question(
                    doc,
                    q,
                    display_number=display_number,
                    shuffle_choices=shuffle_choices,
                    rng=rng
                )
                answer_key.append((display_number, answer))
                display_number += 1
                spacer = doc.add_paragraph()
                self._format_paragraph(spacer)

        if include_answer_key and answer_key:
            self._add_answer_key(doc, answer_key)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        doc.save(output_path)
        logger.info(f"Exported to {output_path}")

    def _add_group_shared_passage_if_needed(self, doc, question, last_group_id):
        group_id = question.get('group_id')
        shared_passage = (
            question.get('shared_passage')
            or question.get('group_shared_text')
        )
        if group_id is not None and shared_passage and group_id != last_group_id:
            self._add_shared_passage(doc, shared_passage)
        return group_id if group_id is not None else None

    def _add_shared_passage(self, doc, shared_passage):
        paragraph = doc.add_paragraph()
        self._format_paragraph(paragraph)
        label = paragraph.add_run("[공통지문] ")
        self._format_run(label, bold=True)
        self._add_text_with_inline_math(
            paragraph,
            self._normalize_plain_export_text(shared_passage),
        )

    def _add_subject_heading(self, doc, title):
        paragraph = doc.add_paragraph()
        self._format_paragraph(paragraph, alignment=WD_ALIGN_PARAGRAPH.CENTER)
        run = paragraph.add_run(str(title or '').strip())
        self._format_run(run, size_pt=16, bold=True)

    def _add_question(
        self,
        doc,
        q,
        display_number: int,
        shuffle_choices: bool = False,
        rng: random.Random = None
    ):
        """Add a question and its choices. Returns answer symbol or None."""
        p = doc.add_paragraph()
        self._format_paragraph(p)
        self._add_formatted_text(
            p,
            q.get('question_text', ''),
            q.get('question_format_json'),
            prefix=f"{display_number}. "
        )

        self._add_format_tables(doc, q.get('question_format_json'))
        question_image_path = q.get('image_path')
        if self._image_exists(question_image_path):
            self._keep_paragraph_together(p, keep_with_next=True)
        self._add_image(
            doc,
            question_image_path,
            width_mm=60,
            alignment=WD_ALIGN_PARAGRAPH.CENTER,
            keep_with_next=bool(q.get('choices')),
            keep_together=True,
        )

        answer_number = q.get('correct_answer')

        # Choices
        if q.get('choices'):
            choices = [self._normalize_choice(c) for c in q['choices']]

            if shuffle_choices and len(choices) == 4:
                rng = rng or random.Random()
                rng.shuffle(choices)

            if answer_number is not None and shuffle_choices and len(choices) == 4:
                new_answer = None
                for idx, choice in enumerate(choices, start=1):
                    if choice.get('_orig_number') == answer_number:
                        new_answer = idx
                        break
                answer_number = new_answer

            if shuffle_choices and len(choices) == 4:
                for idx, choice in enumerate(choices, start=1):
                    choice['choice_number'] = idx
                    choice['choice_symbol'] = NUMBER_TO_CHOICE_SYMBOL.get(idx, str(idx))

            for choice in choices:
                p = doc.add_paragraph()
                self._format_paragraph(p)
                symbol = choice.get('choice_symbol') or NUMBER_TO_CHOICE_SYMBOL.get(choice.get('choice_number')) or ''
                is_correct = choice.get('choice_number') == answer_number
                self._add_formatted_text(
                    p,
                    choice.get('choice_text', ''),
                    choice.get('choice_format_json') or choice.get('format_json'),
                    prefix=f"{symbol} " if symbol else '',
                    size_pt=10,
                    highlight=is_correct
                )
                self._add_image(
                    doc,
                    choice.get('choice_image_path'),
                    width_mm=42,
                    paragraph=p,
                )

        if answer_number is None:
            return None

        return NUMBER_TO_CHOICE_SYMBOL.get(answer_number, str(answer_number))

    def _normalize_choice(self, choice):
        """Normalize choice object to a dict."""
        if isinstance(choice, dict):
            data = dict(choice)
            orig_number = data.get('choice_number')
            if orig_number is None and data.get('choice_symbol'):
                orig_number = CHOICE_SYMBOL_TO_NUMBER.get(data['choice_symbol'])
            data['_orig_number'] = orig_number
            data['choice_image_path'] = data.get('choice_image_path') or data.get('image_path')
            data['choice_format_json'] = data.get('choice_format_json') or data.get('format_json')
            return data

        orig_number = getattr(choice, 'number', None)
        if orig_number is None:
            sym = getattr(choice, 'symbol', None)
            if sym:
                orig_number = CHOICE_SYMBOL_TO_NUMBER.get(sym)

        return {
            'choice_number': getattr(choice, 'number', None),
            'choice_symbol': getattr(choice, 'symbol', None),
            'choice_text': getattr(choice, 'text', None),
            'choice_image_path': getattr(choice, 'choice_image_path', None) or getattr(choice, 'image_path', None),
            'choice_format_json': getattr(choice, 'choice_format_json', None) or getattr(choice, 'format_json', None),
            '_orig_number': orig_number
        }

    def _parse_format_json(self, value):
        if not value:
            return {}
        if isinstance(value, dict):
            return value
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}

    def _add_formatted_text(
        self,
        paragraph,
        text,
        format_json=None,
        prefix='',
        size_pt=None,
        highlight=False
    ):
        text = str(text or '')
        format_spec = self._parse_format_json(format_json)
        spans = self._valid_spans(text, format_spec.get('spans') or [])
        if not spans:
            text = self._normalize_plain_export_text(text)
            if prefix:
                run = paragraph.add_run(prefix)
                self._format_run(run, size_pt=size_pt, highlight=highlight)
            self._add_text_with_inline_math(
                paragraph,
                text,
                size_pt=size_pt,
                highlight=highlight
            )
            return

        if prefix:
            run = paragraph.add_run(prefix)
            self._format_run(run, size_pt=size_pt, highlight=highlight)

        position = 0
        for start, end, options in spans:
            if start > position:
                self._add_text_with_inline_math(
                    paragraph,
                    self._normalize_plain_export_text(text[position:start], strip=False),
                    size_pt=size_pt,
                    highlight=highlight
                )
            if options.get('latex'):
                self._add_math_from_latex(paragraph, options.get('latex'))
            else:
                run = paragraph.add_run(text[start:end])
                self._format_run(
                    run,
                    size_pt=size_pt,
                    highlight=highlight,
                    underline=bool(options.get('underline'))
                )
            position = end

        if position < len(text) or not spans:
            self._add_text_with_inline_math(
                paragraph,
                self._normalize_plain_export_text(text[position:], strip=False),
                size_pt=size_pt,
                highlight=highlight
            )

    def _normalize_plain_export_text(self, text, strip=True):
        """Remove PDF extraction layout artifacts before writing plain DOCX text."""
        if strip:
            return repair_extracted_text_artifacts(text)

        raw = str(text or '')
        leading = re.match(r'^\s*', raw).group(0)
        trailing = re.search(r'\s*$', raw).group(0)
        core_end = len(raw) - len(trailing) if trailing else len(raw)
        core = raw[len(leading):core_end]
        return leading + repair_extracted_text_artifacts(core) + trailing

    def _normalize_private_math_glyphs(self, text):
        return normalize_private_math_glyphs(text)

    def _private_digit(self, value):
        return {
            '\ue034': '1',
            '\ue035': '2',
            '\ue036': '3',
            '\ue037': '4',
        }.get(value, value)

    def _add_text_with_inline_math(self, paragraph, text, size_pt=None, highlight=False):
        position = 0
        for match in re.finditer(r'√\s*([0-9]+|[A-Za-z]+)', str(text or '')):
            if match.start() > position:
                run = paragraph.add_run(text[position:match.start()])
                self._format_run(run, size_pt=size_pt, highlight=highlight)
            self._add_radical_math(paragraph, match.group(1))
            position = match.end()

        if position < len(text) or not text:
            run = paragraph.add_run(text[position:])
            self._format_run(run, size_pt=size_pt, highlight=highlight)

    def _add_math_from_latex(self, paragraph, latex):
        latex = str(latex or '').strip()
        element = self._math_element_from_latex(latex)
        if element is None:
            element = self._math_text_element(latex)
        paragraph._p.append(element)

    def _math_element_from_latex(self, latex):
        sqrt_match = re.fullmatch(r'\\?sqrt\{(.+)\}', latex)
        if sqrt_match:
            return self._radical_math_element(sqrt_match.group(1))

        overline_match = re.fullmatch(r'\\?overline\{(.+)\}', latex)
        if overline_match:
            return self._bar_math_element(overline_match.group(1))

        frac_match = re.fullmatch(r'\\?frac\{(.+)\}\{(.+)\}', latex)
        if frac_match:
            return self._fraction_math_element(frac_match.group(1), frac_match.group(2))

        if self._looks_like_linear_latex_formula(latex):
            return self._linear_math_element(latex)

        return None

    def _add_radical_math(self, paragraph, inner):
        paragraph._p.append(self._radical_math_element(inner))

    def _math_text_element(self, text):
        math = OxmlElement('m:oMath')
        math.append(self._math_run(text))
        return math

    def _radical_math_element(self, inner):
        math = OxmlElement('m:oMath')
        math.append(self._radical_component(inner))
        return math

    def _radical_component(self, inner):
        rad = OxmlElement('m:rad')
        rad_pr = OxmlElement('m:radPr')
        deg_hide = OxmlElement('m:degHide')
        deg_hide.set(qn('m:val'), '1')
        rad_pr.append(deg_hide)
        rad.append(rad_pr)
        rad.append(OxmlElement('m:deg'))
        expr = OxmlElement('m:e')
        expr.append(self._math_run(inner))
        rad.append(expr)
        return rad

    def _looks_like_linear_latex_formula(self, latex):
        return bool(re.search(r'=|\\sqrt|\\times|\\cdot|\\theta|\\cos|\\sin|\\tan', str(latex or '')))

    def _linear_math_element(self, latex):
        math = OxmlElement('m:oMath')
        position = 0
        text = str(latex or '')
        for match in re.finditer(r'\\sqrt\{([^{}]+)\}', text):
            if match.start() > position:
                self._append_math_text(math, text[position:match.start()])
            math.append(self._radical_component(match.group(1)))
            position = match.end()

        if position < len(text):
            self._append_math_text(math, text[position:])
        return math

    def _append_math_text(self, math, latex_text):
        display = self._latex_text_to_display_text(latex_text)
        if display:
            math.append(self._math_run(display))

    def _latex_text_to_display_text(self, text):
        display = str(text or '')
        replacements = [
            (r'\times', '×'),
            (r'\cdot', '·'),
            (r'\theta', 'θ'),
            (r'\Theta', 'θ'),
            (r'\cos', 'cos'),
            (r'\sin', 'sin'),
            (r'\tan', 'tan'),
        ]
        for source, target in replacements:
            display = display.replace(source, target)
        return display

    def _bar_math_element(self, inner):
        math = OxmlElement('m:oMath')
        bar = OxmlElement('m:bar')
        bar_pr = OxmlElement('m:barPr')
        pos = OxmlElement('m:pos')
        pos.set(qn('m:val'), 'top')
        bar_pr.append(pos)
        bar.append(bar_pr)
        expr = OxmlElement('m:e')
        expr.append(self._math_run(inner))
        bar.append(expr)
        math.append(bar)
        return math

    def _fraction_math_element(self, numerator, denominator):
        math = OxmlElement('m:oMath')
        frac = OxmlElement('m:f')
        num = OxmlElement('m:num')
        num.append(self._math_run(numerator))
        den = OxmlElement('m:den')
        den.append(self._math_run(denominator))
        frac.append(num)
        frac.append(den)
        math.append(frac)
        return math

    def _math_run(self, text):
        run = OxmlElement('m:r')
        text_element = OxmlElement('m:t')
        text_element.text = str(text or '')
        run.append(text_element)
        return run

    def _repair_parenthetical_note_artifacts(self, text):
        text = re.sub(
            (
                r'^(?P<head>.+?)\s+단\s+는\s+'
                r'(?P<desc>[^?()]+?)\s+이다\?\s*'
                r'\(\s*,\s*(?P<var>[A-Za-z][A-Za-z0-9]*)\s*'
                r'(?P<unit>\[[^\]]+\])?\s*\.\s*\)\s*$'
            ),
            self._rebuild_variable_note_before_question_mark,
            text,
        )
        text = re.sub(
            (
                r'^(?P<head>.+?\?)\s*단\s+는\s+'
                r'(?P<desc>[^()]+?)이다\s*'
                r'\(\s*,\s*(?P<var>[A-Za-z][A-Za-z0-9]*)\s*\.\s*\)\s*$'
            ),
            self._rebuild_variable_note_after_question_mark,
            text,
        )
        text = re.sub(
            (
                r'^(?P<head>.+?)\s+단\s+의\s+값(?P<angle>\d+)\s*\?\s*'
                r'\(\s*,\s*(?P<expr>sin\s*(?P=angle)˚)\s*'
                r'은\s+이다(?P<value>[0-9.]+)\s*\.\s*\)\s*$'
            ),
            self._rebuild_trig_value_note,
            text,
        )
        return text

    def _rebuild_variable_note_before_question_mark(self, match):
        desc = re.sub(r'\s+', ' ', match.group('desc')).strip()
        unit = match.group('unit') or ''
        return f"{match.group('head').strip()}? (단, {match.group('var')}는 {desc}{unit}이다.)"

    def _rebuild_variable_note_after_question_mark(self, match):
        desc = re.sub(r'\s+', ' ', match.group('desc')).strip()
        return f"{match.group('head').strip()} (단, {match.group('var')}는 {desc}이다.)"

    def _rebuild_trig_value_note(self, match):
        expr = re.sub(r'\s+', '', match.group('expr'))
        return f"{match.group('head').strip()}? (단, {expr}의 값은 {match.group('value')}이다.)"

    def _valid_spans(self, text, spans):
        normalized = []
        for span in spans:
            try:
                start = int(span.get('start'))
                end = int(span.get('end'))
            except (TypeError, ValueError, AttributeError):
                continue
            if start < 0 or end <= start or end > len(text):
                continue
            normalized.append((start, end, span))

        normalized.sort(key=lambda item: (item[0], item[1]))
        merged = []
        last_end = -1
        for start, end, span in normalized:
            if start < last_end:
                continue
            merged.append((start, end, span))
            last_end = end
        return merged

    def _add_format_tables(self, doc, format_json):
        spec = self._parse_format_json(format_json)
        for table_spec in spec.get('tables') or []:
            rows = table_spec.get('rows') if isinstance(table_spec, dict) else None
            rows = [
                [str(cell or '') for cell in row]
                for row in rows or []
                if isinstance(row, list)
            ]
            if not rows:
                continue

            column_count = max((len(row) for row in rows), default=0)
            if column_count == 0:
                continue

            table = doc.add_table(rows=len(rows), cols=column_count)
            try:
                table.style = 'Table Grid'
            except Exception:
                pass

            for row_idx, row in enumerate(rows):
                for col_idx in range(column_count):
                    cell = table.cell(row_idx, col_idx)
                    text = row[col_idx] if col_idx < len(row) else ''
                    paragraph = cell.paragraphs[0]
                    self._format_paragraph(paragraph)
                    run = paragraph.add_run(text)
                    self._format_run(run, size_pt=9)

    def _add_image(
        self,
        doc,
        image_path,
        width_mm,
        paragraph=None,
        alignment=None,
        keep_with_next=False,
        keep_together=False,
    ):
        """Add an image paragraph when the path exists."""
        if not self._image_exists(image_path):
            return None

        try:
            if paragraph is None:
                paragraph = doc.add_paragraph()
                self._format_paragraph(paragraph, alignment=alignment)
            if keep_with_next or keep_together:
                self._keep_paragraph_together(
                    paragraph,
                    keep_with_next=keep_with_next,
                    keep_together=keep_together,
                )
            run = paragraph.add_run()
            picture_source = self._normalized_image_stream(image_path) or image_path
            run.add_picture(picture_source, width=Mm(width_mm))
            return paragraph
        except Exception as e:
            logger.error(f"Failed to add image {image_path}: {e}")
            return None

    def _image_exists(self, image_path):
        return bool(image_path and Path(image_path).exists())

    def _normalized_image_stream(self, image_path):
        """Return a PNG stream so Word export survives malformed PDF-extracted JPEG metadata."""
        try:
            from PIL import Image
        except Exception:
            return None

        try:
            with Image.open(image_path) as image:
                if image.mode not in ('RGB', 'RGBA'):
                    image = image.convert('RGB')
                else:
                    image = image.copy()

            buffer = io.BytesIO()
            image.save(buffer, format='PNG', dpi=(96, 96))
            buffer.seek(0)
            return buffer
        except Exception as exc:
            logger.debug("Image normalization failed for %s: %s", image_path, exc)
            return None

    def _keep_paragraph_together(self, paragraph, keep_with_next=False, keep_together=False):
        if keep_with_next:
            paragraph.paragraph_format.keep_with_next = True
        if keep_together:
            paragraph.paragraph_format.keep_together = True

    def _add_answer_key(self, doc, answer_key):
        """Append answer key section."""
        doc.add_page_break()

        header = doc.add_paragraph()
        self._format_paragraph(header)
        run = header.add_run("Answer Key")
        self._format_run(run, size_pt=14, bold=True)

        line = []
        for idx, ans in answer_key:
            ans_text = ans or ''
            line.append(f"{idx}. {ans_text}")
            if len(line) == 5:
                p = doc.add_paragraph()
                self._format_paragraph(p)
                run = p.add_run("  ".join(line))
                self._format_run(run, size_pt=10)
                line = []

        if line:
            p = doc.add_paragraph()
            self._format_paragraph(p)
            run = p.add_run("  ".join(line))
            self._format_run(run, size_pt=10)

    def _set_columns(self, section, cols):
        """섹션을 다단으로 설정 (OpenXML 조작)"""
        sectPr = section._sectPr
        cols_xml = sectPr.xpath('w:cols')[0]
        cols_xml.set(qn('w:num'), str(cols))
        cols_xml.set(qn('w:sep'), '1')
        cols_xml.set(qn('w:space'), self.COLUMN_SPACE_TWIPS)

    def _set_document_defaults(self, doc):
        normal = doc.styles['Normal']
        normal.font.name = self.FONT_NAME
        normal.font.size = Pt(11)
        self._set_style_font(normal, self.FONT_NAME)
        normal.paragraph_format.space_after = Pt(0)
        normal.paragraph_format.line_spacing = Pt(8)

    def _split_title(self, title):
        lines = [line.strip() for line in str(title).splitlines() if line.strip()]
        return lines or ['']

    def _format_paragraph(self, paragraph, alignment=None):
        paragraph.alignment = alignment
        paragraph.paragraph_format.space_after = Pt(0)
        paragraph.paragraph_format.line_spacing = Pt(8)

        pPr = paragraph._p.get_or_add_pPr()
        spacing = pPr.find(qn('w:spacing'))
        if spacing is None:
            spacing = OxmlElement('w:spacing')
            pPr.append(spacing)
        spacing.set(qn('w:after'), '0')
        spacing.set(qn('w:line'), self.BODY_LINE_TWIPS)
        spacing.set(qn('w:lineRule'), 'atLeast')

        rPr = pPr.find(qn('w:rPr'))
        if rPr is None:
            rPr = OxmlElement('w:rPr')
            pPr.append(rPr)
        self._set_rpr_font(rPr, self.FONT_NAME)

    def _format_run(self, run, size_pt=None, bold=False, highlight=False, underline=False):
        run.bold = bold
        if underline:
            run.underline = True
        if size_pt is not None:
            run.font.size = Pt(size_pt)
        run.font.name = self.FONT_NAME
        if highlight:
            run.font.highlight_color = WD_COLOR_INDEX.YELLOW
        self._set_font(run, self.FONT_NAME)

    def _set_style_font(self, style, font_name):
        rPr = style._element.get_or_add_rPr()
        self._set_rpr_font(rPr, font_name)

    def _set_font(self, run, font_name):
        """한글 폰트 설정"""
        rPr = run._element.get_or_add_rPr()
        self._set_rpr_font(rPr, font_name)

    def _set_rpr_font(self, rPr, font_name):
        rFonts = rPr.get_or_add_rFonts()
        rFonts.set(qn('w:ascii'), font_name)
        rFonts.set(qn('w:eastAsia'), font_name)
        rFonts.set(qn('w:hAnsi'), font_name)

        lang = rPr.find(qn('w:lang'))
        if lang is None:
            lang = OxmlElement('w:lang')
            rPr.append(lang)
        lang.set(qn('w:eastAsia'), 'ko-KR')
