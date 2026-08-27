# ExamDocument foundation

Production export path:

`ExportInterface` selects questions, then `ExamDocumentBuilder.build(...)` produces an immutable `ExamDocument`, then `DocxExporter.export_document(...)` renders DOCX.

`DocxExporter.export(...)` remains a thin compatibility facade over the same builder and renderer.

DOCX is the only user-facing editable export. HWPX export is not implemented.

## Import vs export IRs

- `DocumentSourceIR` (`src/document_source`) is import-side source structure (pages, runs, tables, attachments, diagnostics).
- `ExamDocument` is export-side exam semantics (questions, choices, answer key).
- Neither replaces the other.
- A future exam-structure parser may connect `DocumentSource` to the existing question/database model, then `ExamDocumentBuilder` as today.
