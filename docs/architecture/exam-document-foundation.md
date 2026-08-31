# ExamDocument foundation

Production export path:

`ExportInterface` selects questions and an output format, then `ExamDocumentBuilder.build(...)` produces one immutable `ExamDocument`, then exactly one sibling renderer runs: `DocxExporter.export_document(...)` or `HwpxCompiler.export_document(...)`.

`DocxExporter.export(...)` remains a thin compatibility facade and is not used by the production GUI route.

User-facing editable export is DOCX or HWPX. HWP binary output is not implemented.

## Import vs export IRs

- `DocumentSourceIR` (`src/document_source`) is import-side source structure (pages, runs, tables, attachments, diagnostics).
- `ExamDocument` is export-side exam semantics (questions, choices, answer key).
- Neither replaces the other.
- A future exam-structure parser may connect `DocumentSource` to the existing question/database model, then `ExamDocumentBuilder` as today.
