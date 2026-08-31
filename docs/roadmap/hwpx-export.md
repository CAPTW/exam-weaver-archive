# HWPX Export Roadmap

> Status: **Direct HWPX compiler MVP implemented on a local feature candidate**
>
> Canonical `main` and user-facing editable export remain DOCX only.

## Goal

Compose an exam once as `ExamDocument` and later compile both DOCX and HWPX from that same ordered content. Compilers must not independently shuffle or renumber questions.

## Current export

`ExamDocumentBuilder` → immutable `ExamDocument` → `DocxExporter.export_document(...)`.

Legacy `DocxExporter.export(...)` is a compatibility facade.

## HWPX compiler candidate

Implemented on the local feature candidate:

- direct HWPX ZIP/OWPML compiler MVP from immutable `ExamDocument`
- title lines, semantic sections, questions, and variable-count choices
- descriptive questions and model answers
- question, passage, and choice images with byte deduplication
- simple and merged native tables
- explicit image/text fallback for complex tables
- deterministic 12×8 answer-key tables and continuation
- internal package validation and canonical `HwpxSourceAdapter` semantic readback
- atomic output with stable warning and failure codes
- repository-owned clean-room profile with no runtime private template
- no Hancom Office runtime dependency

Still not implemented:

- GUI DOCX/HWPX selector
- canonical `main` integration
- public release
- HWP binary output
- advanced equations and drawings
- native Hancom acceptance corpus

## Output selector

A GUI format selector is not implemented. The save dialog remains DOCX.

## Delivery gates (future)

1. Export-model extraction — **done** (ExamDocument + DOCX).
2. Direct OWPML compiler MVP — **local feature candidate implemented**.
3. Format-selection UI — not started.
4. Optional native smoke — after compiler exists.
5. Advanced fidelity — later.

No README or UI claim should present HWPX output as a current feature.
