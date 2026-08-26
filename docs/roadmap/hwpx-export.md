# HWPX Export Roadmap

> Status: **format-neutral ExamDocument foundation implemented on this feature branch; HWPX exporter is not implemented**
>
> The production application currently exports editable exam sheets as DOCX only. This document records the implemented ExamDocument foundation and the remaining HWPX qualification boundary.

## Goal

Allow a user to compose an exam once and choose an editable output format:

- Microsoft Word document (`.docx`)
- Hancom open document (`.hwpx`)

The two exporters must consume the same ordered exam content and must not independently select, shuffle, renumber, or reinterpret questions.

## Design principle

The current `DocxExporter` combines two responsibilities:

1. deciding the final exam structure;
2. rendering that structure into WordprocessingML.

Before adding HWPX, these responsibilities should be separated.

```text
Question-bank records
        |
        v
ExamDocumentBuilder
        |
        v
Format-neutral ExamDocument
       / \
      v   v
  DOCX     HWPX
 exporter exporter
```

## Proposed modules

```text
src/exporter/
  models.py          Format-neutral exam document model
  builder.py         Repository records -> ExamDocument
  options.py         Shared and format-specific export options
  registry.py        Output-format registry
  validation.py      Semantic output checks
  docx.py            DOCX renderer
  hwpx.py            HWPX renderer
  table_layout.py    Shared table-layout decisions where applicable
  templates/
    default_exam.hwpx
```

## Format-neutral document model

The exact implementation can use dataclasses or validated models, but it should represent at least:

```text
ExamDocument
  title
  subtitle
  page_profile
  sections[]
    heading
    blocks[]
      SharedPassageBlock
      QuestionBlock
      ImageBlock
      TableBlock
      PageBreakBlock
  answer_key[]
```

A `QuestionBlock` should preserve:

- display number;
- question type;
- stem and shared passage;
- ordered choices;
- correct answer or model answer;
- source images and graphical choices;
- tables and their ownership;
- rich-text spans such as underline, overline, superscript, and subscript;
- warnings produced during export preparation.

## HWPX implementation strategy

Use a **template-first** workflow rather than assembling every OWPML part from scratch.

1. Create a small, clean `default_exam.hwpx` in Hancom Office.
2. Predefine A4 size, margins, two-column layout, title styles, body styles, choice styles, and answer-key styles.
3. Open the template through an isolated HWPX backend adapter.
4. Insert content from `ExamDocument` only.
5. Save to a new path.
6. Reopen and validate the generated HWPX before reporting success.

A candidate pure-Python backend may be qualified, but no dependency should be added until its exact version passes the project corpus and packaging checks. Application code should depend on an internal backend protocol rather than on a third-party API directly.

```text
HwpxExporter
  -> HwpxBackend protocol
       -> qualified backend adapter
```

## MVP support matrix

| Surface | HWPX MVP behavior |
|---|---|
| Title and subtitle | Native text and styles |
| A4, margins, two columns | Preserved by template |
| Section headings | Native paragraphs |
| Four- and five-choice questions | Native text |
| Variable choice count | Native text |
| Shared passages | Native text block |
| Descriptive questions | Native text |
| Model answers | Native text |
| Answer key | Native table |
| Question images | Native picture |
| Graphical choices | Ordered pictures |
| Simple tables | Native table |
| Complex tables | Source-image fallback with warning |
| Basic inline formatting | Native where qualified |
| Complex equations | Image fallback until equation objects are qualified |

Fallbacks must be explicit in `ExportResult.warnings`. The exporter must not silently omit or corrupt unsupported content.

## User interface

Rename the current DOCX-specific surface to a format-neutral export surface.

```text
시험지 내보내기

출력 형식
[ Word 문서 (.docx)        v ]

Options:
- Word 문서 (.docx)
- 한글 개방형 문서 (.hwpx)
```

The save-file extension and filter follow the selected format. Shared options remain visible for both formats; format-specific options appear only when relevant.

## Required validation

### Package validation

- output file exists and is non-empty;
- HWPX ZIP package is structurally valid;
- required OWPML parts are present;
- all XML parts parse;
- every referenced media asset exists;
- the selected backend can reopen the generated document.

### Semantic validation

Compare the source `ExamDocument` with a readback representation:

- title and section count;
- question count and numbering;
- choice count, order, and text;
- shared-passage membership;
- image and table ownership;
- answer-key rows;
- descriptive model answers.

DOCX and HWPX may lay out content differently, but they must preserve the same exam semantics.

### Native acceptance corpus

Before release, open representative outputs in supported Hancom Office versions:

- plain multiple-choice exam;
- shared-passage question set;
- image question;
- graphical-choice question;
- simple and complex table cases;
- descriptive question;
- mixed Korean, English, symbols, and equations;
- long 50- to 100-question exam;
- content crossing a column or page boundary.

## Current implementation status

Gate 1 is implemented on `feature/exam-document-format-neutral-foundation`:

- `src/exporter/exam_document.py` — immutable format-neutral contracts
- `src/exporter/builder.py` — `ExamDocumentBuilder` composition
- `DocxExporter.export_document(...)` renders an `ExamDocument`
- legacy `DocxExporter.export(...)` remains a compatible facade
- GUI export still says DOCX only and still uses the same save-dialog strings

Not implemented in this gate:

- HWPX exporter
- HWPX dependency
- HWPX template
- output format selector
- any user-facing HWPX support claim

The next HWPX work requires a separate qualification Gate after this foundation is independently accepted. The current legacy DOCX API remains compatible.

## Delivery gates

1. **Export-model extraction** — existing DOCX output remains semantically unchanged.
2. **HWPX backend qualification** — exact dependency and package-build behavior are pinned.
3. **HWPX MVP** — core content, images, simple tables, and answer key.
4. **Format-selection UI** — DOCX and HWPX use the same prepared document.
5. **Native Hancom acceptance** — corpus opens and renders without data loss.
6. **Advanced parity** — richer tables, equations, and page-flow controls.

No HWPX badge or README claim should be presented as a current feature before gates 1 through 5 pass.
