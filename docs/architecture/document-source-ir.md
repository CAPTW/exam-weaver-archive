# DocumentSourceIR

Import-side immutable intermediate representation. It is **not** `ExamDocument`.

## Purpose

Convert a source file into backend-neutral structure before any exam-domain parsing:

`source file` → `probe_document_format` → `DocumentSourceAdapter` → immutable `DocumentSource` → future `ExamStructureParser` → existing question/database model.

## Distinction from ExamDocument

| IR | Side | Role |
|---|---|---|
| `DocumentSourceIR` (`src/document_source`) | import | physical document structure, coordinates, diagnostics, attachments |
| `ExamDocument` (`src/exporter`) | export | composed exam semantics for DOCX (and future HWPX) |

Neither replaces the other. Third-party parser objects do not cross the IR boundary. `HwpxSourceAdapter` is the first backend-specific non-PDF adapter candidate. `HwpSourceAdapter` is not implemented. GUI import remains PDF-only.

## Model

Frozen slotted dataclasses with tuple collections: `DocumentSource`, `DocumentSection`, `DocumentParagraph`, `DocumentRun`, `DocumentTable*`, `DocumentImage`, `DocumentField`, `DocumentMasterPage`, `DocumentLayoutBreak`, `SourceCoordinate`, `SourceDiagnostic`, `SourceAttachment`.

Unsupported content is recorded as diagnostics, not dropped silently.

## Signature detection

`probe_document_format(path)` inspects content, not extension:

- PDF: `%PDF-` in a bounded header window
- HWPX: ZIP plus `mimetype=application/hwp+zip` and required OWPML parts; generic ZIP is rejected
- HWP 5: CFB container plus `FileHeader` stream starting with `HWP Document File`; generic OLE/CFB is rejected

Resource caps apply to ZIP entries and CFB FAT chains. Extension/signature mismatch is a warning.

## PDF mapping

One `DocumentSection` per PDF page (`page-N`). Text comes from existing extractor lines when present, otherwise page text with `PDF_ADAPTER_TEXT_ONLY_PAGE`. Tables and images map when the extractor exposes them. Images become `SourceAttachment` hashes, not raw bytes in the IR.

## Adapters

- `PdfSourceAdapter`: implemented thin mapping over the existing extractor
- `HwpxSourceAdapter`: local feature candidate using `hwpxkit==0.2.1` (MIT). Not GUI-integrated.
- `HwpSourceAdapter`: not implemented. `hwp-hwpx-parser==1.0.0` remains `SELECTED_NOT_INTEGRATED`
- Native Hancom UI automation: `DEPRIORITIZED_RESEARCH_ONLY_NOT_PRODUCT_PATH`
