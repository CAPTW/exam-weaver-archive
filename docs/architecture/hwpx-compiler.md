# Direct OWPML HWPX compiler

## Status

This implementation is a **local feature candidate**. It is not integrated into canonical `main`, exposed by the GUI, or released to users.

## Input and output

`HwpxCompiler.export_document(document, output_path)` consumes the same immutable, already ordered `ExamDocument` used by the DOCX exporter and produces an editable `.hwpx` package. The compiler does not query the database, build or reorder an exam, renumber questions, reinterpret answers, or mutate source paths and formatting payloads.

## Direct OWPML architecture

The data flow is:

`ExamDocument` → renderer-owned semantic manifest → repository-authored OWPML XML parts → deterministic HWPX ZIP → internal package validation → canonical `HwpxSourceAdapter` readback → atomic replacement → `HwpxExportResult`.

The writer uses Python's XML and ZIP support directly. It does not automate Hancom Office and does not use `hwpxkit` as a writer; `hwpxkit==0.2.1` is reached only through the existing canonical readback adapter.

Responsibilities are split across the public compiler, immutable profile, package/XML builder, semantic renderer, and validation modules. Export-local allocators and registries are reset on every call.

## Clean-room template profile

The repository-owned `HwpxTemplateProfile` contains only authored structural constants: portrait `72852 × 103180` HWPUNIT pages, margins `3402/3402/5102/1984`, header/footer margins `3968/2835`, one-column cover, two-column body with gap `2268`, and a one-column answer-key segment. Empty EVEN and ODD master-page roles are authored by the package builder. No binary template, logo, image, embedded font, text, identifier, or metadata from a private source is present.

The accepted sanitized derivative was used read-only as a structural oracle for those safe dimensions, roles, and the final 12×8 answer-table topology. It is neither a runtime dependency nor a source of copied XML parts. Generated packages are clean-room outputs and are not expected to be byte-identical to that derivative.

## Package parts and determinism

The package contains an uncompressed first `mimetype` entry, version and settings XML, container and manifest metadata, content metadata, a deterministic header/style resource, empty master pages, ordered section parts, and content-hash-named `BinData` parts when images are used. Every declared rootfile, spine item, master-page reference, and media reference is checked.

ZIP member order and timestamps are fixed. IDs are allocated in stable document order; media IDs and names derive from content hashes. No timestamp, UUID, process ID, memory address, source path, or random value enters output bytes. Identical semantic input, profile, and image bytes therefore produce byte-identical packages and the same package SHA-256 and semantic digest.

## Rendering semantics

Title lines render in a one-column cover segment. Semantic section headings, shared passages, numbered questions, ordered choices, descriptive instructions, and model answers render in the two-column body without reordering. Choice markers follow the existing marker policy and tuple order, including variable choice counts.

Supported inline spans include underline, bold, italic, superscript, subscript, safe font size, and text color. Unsupported properties and equations remain visible as text and emit stable warnings. `hwpxkit 0.2.1` trims whitespace at styled run boundaries in its normalized readback representation; the authored package XML retains the exact visible whitespace, and readback validation permits only that whitespace-only backend normalization while requiring identical paragraph boundaries and non-whitespace code points.

## Tables and images

Rectangular simple and merged tables render as native OWPML tables with validated coordinates and spans. Invalid or overlapping topology fails closed. A complex table uses its valid source image when supplied; otherwise it has an explicit visible-text fallback. Both paths emit stable fallback warnings rather than silently dropping content.

Question, shared-passage, and choice images retain source order and ownership. PNG, JPEG, and BMP are embedded directly after validation; other Pillow-readable formats are deterministically converted to PNG with a warning. Identical image bytes are deduplicated. Missing or unreadable required images fail closed.

## Answer-key layout

When requested and nonempty, the answer key starts a new one-column segment. Entries render in deterministic native 12×8 tables, four number/answer pairs per row and 44 answers per table. Additional tables continue at 45 and 89 entries. Objective markers, descriptive answers, all-correct answers, and unavailable answers are rendered explicitly without inference.

## Warning and failure policy

Nonfatal warnings are ordered and deduplicated. They cover unsupported formatting as text, equation text fallback, complex-table image or text fallback, image conversion, answer-table continuation, and unavailable optional metadata.

`HwpxCompileError.code` provides stable fail-closed categories for invalid destinations, missing images, invalid table topology, unresolved content loss, XML/package construction, package structure, unresolved relationships, semantic readback, and atomic replacement. No output is published before structural and semantic validation succeeds.

## Atomic output and semantic readback

The compiler creates a unique temporary sibling, writes and closes the complete package, validates ZIP and XML invariants, runs the canonical `HwpxSourceAdapter`, checks sections, layout, paragraph semantics, tables, images, and attachments, computes result hashes, and finally calls atomic replacement. On failure it removes the temporary sibling and preserves any pre-existing destination bytes.

Readback proves the supported document semantics and package relationships; it does not prove pixel-level visual parity or native Hancom acceptance.

## Privacy boundary

Tracked code contains safe authored constants only. It has no runtime access to a private or sanitized HWPX, no external relationship, no absolute source path in the package, and no embedded private text, media, author, institution, database, generated output, wheel, or native binary.

## Unsupported and advanced features

Advanced equations, drawings, arbitrary complex-table native reconstruction, HWP binary output, and native Hancom acceptance are outside this candidate. Complex content follows the documented warning or fail-closed policy. A user-facing DOCX/HWPX selector is not implemented.

