# HWPX Export Roadmap

> Status: **Compiler is on canonical `main`. GUI DOCX/HWPX selector is this feature candidate.**
>
> Remaining: independent review, PR/main integration, public release validation.

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

- public release
- HWP binary output
- HWPX import selector
- HWPX-to-question parsing
- advanced equations and drawings
- native Hancom acceptance corpus

## Output selector

This feature candidate adds a session-only `출력 형식` ComboBox (`docx` / `hwpx`), format-specific save dialogs, and exclusive routing of one `ExamDocument` to `DocxExporter` or `HwpxCompiler`. Default remains DOCX.

## Delivery gates

1. Export-model extraction — **done**.
2. Direct OWPML compiler — **done on main**.
3. Format-selection UI — **this feature candidate**.
4. Independent review / push / merge — later.
5. Advanced fidelity — later.
