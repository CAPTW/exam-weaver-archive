# HWPX source adapter

Status: local implementation candidate. Not user-facing.

## Backend

- Package: `hwpxkit==0.2.1`
- License: MIT (`third_party_licenses/hwpxkit-MIT.txt`)
- Artifact: Windows x86-64 CPython ABI3 wheel
- Lazy import: `src.document_source` does not load `hwpxkit`
- Parse uses `parse_file` only. Unbounded `parse(bytes)` is not used.

## Sequence

Signature probe → size policy → exact version → `parse_file` → structured `to_json` → bounded package supplement → immutable `DocumentSource`.

Markdown/HTML conversion is not semantic authority. Backend objects do not leave `src.document_source.adapters.hwpx`.

## Mapping

Sections, paragraph/run text, tables and spans, image attachment hashes, diagnostics, and source locators are mapped. Master-page identity and page/column/margin properties come from the package supplement.

## Package supplement

Standard library ZIP/XML only. Media size/hash, section `pagePr`/`colPr`, master-page parts. No text re-parse, no extractall, no writes beside the source.

## Packaging

`ExamGenerator.spec` collects `hwpxkit` and the MIT notice. HWPX import is not exposed in the GUI.
