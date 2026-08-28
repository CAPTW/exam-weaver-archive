# HWPX Export Roadmap

> Status: **ExamDocument foundation implemented; HWPX compiler is not implemented**
>
> User-facing editable export remains DOCX only.

## Goal

Compose an exam once as `ExamDocument` and later compile both DOCX and HWPX from that same ordered content. Compilers must not independently shuffle or renumber questions.

## Current export

`ExamDocumentBuilder` → immutable `ExamDocument` → `DocxExporter.export_document(...)`.

Legacy `DocxExporter.export(...)` is a compatibility facade.

## HWPX compiler strategy (future)

Not implemented in this Gate.

Required direction:

- one `ExamDocument` build
- direct HWPX ZIP/OWPML package compiler
- private sanitized external template derivative (uncommitted until separate clearance): `PRIVATE_LOCAL_DERIVATIVE_NOT_CLEARED_FOR_COMMIT`
- **direct OWPML package layer as correctness authority**
- `python-hwpx` only where reliable (`SELECTED_HWPX_WRITER_STRATEGY_NOT_IMPLEMENTED`)
- known limitation: `python-hwpx` save can fail open-safety on stale `lineseg` caches after text replacement
- package validation and semantic readback
- explicit fallback warnings
- no Hancom Office runtime requirement
- optional native open-smoke only after a direct compiler exists
- native Hancom UI automation is `DEPRIORITIZED_RESEARCH_ONLY_NOT_PRODUCT_PATH` and is not a template-authoring prerequisite

## Output selector

A GUI format selector is not implemented. The save dialog remains DOCX.

## Delivery gates (future)

1. Export-model extraction — **done** (ExamDocument + DOCX).
2. Direct OWPML compiler MVP — not started.
3. Format-selection UI — not started.
4. Optional native smoke — after compiler exists.
5. Advanced fidelity — later.

No README or UI claim should present HWPX output as a current feature.
