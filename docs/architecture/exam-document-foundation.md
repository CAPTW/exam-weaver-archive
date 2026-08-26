# ExamDocument foundation

Production path:

`ExportInterface` selects questions, then `ExamDocumentBuilder.build(...)` produces an immutable `ExamDocument`, then `DocxExporter.export_document(...)` renders DOCX.

`DocxExporter.export(...)` remains a thin compatibility facade over the same builder and renderer.

DOCX is the only user-facing editable export. HWPX is not implemented.
