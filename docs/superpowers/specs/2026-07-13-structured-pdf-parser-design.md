# Structured PDF Parser Design

## Goal

Replace the duplicated string-only offline PDF parsing path with a shared, position-aware parser, reparse all exam PDFs under the user-specified coast-guard folder into a staging database, validate every exam set, and replace the mounted Maritime database only after a backup and successful validation.

## Evidence and scope

The folder contains 30 PDFs: 12 question papers, 15 answer or explanation files, and 3 recruitment notices. Ten question papers are scanned Ronpark collections across engineering, navigation, maritime law, and maritime English; two 2023 papers contain native two-column text.

The mounted database contains 3,226 `ronpark_pdf` questions. Of these, 2,320 contain a generic `원문 보기 참조` choice and 2,272 carry `choice_split_review`. The 2026 maritime-law question 8 failure is reproducible: Windows OCR reads the answer row `① 44 ② 46 ③ 48 ④ 50` as `㉦ 44 246 48 ㉦ 50`, then the importer treats `<보기>` labels `㉠` through `㉣` as final answer choices.

This change covers the four offline subject importers and the shared extraction/parser code they require. It does not alter unrelated web-import semantics.

## Architecture

### Structured extraction

Introduce immutable OCR layout records retaining page, word text, bounding box, OCR confidence when available, detected column, and line membership. `PDFExtractor` returns both reconstructed text for compatibility and structured lines for the new parser. Native PDF words and WinRT OCR words use the same coordinate model.

Page classification is based on body text density, repeated text ratio, embedded full-page images, and column geometry. It distinguishes native text, scanned image, image plus repeated fake text layer, and non-question pages. Column detection is recalculated per page.

### Shared semantic parser

A new shared offline parser consumes structured page lines and produces question candidates. It performs, in order:

1. document-role filtering;
2. header/footer and advertisement removal using position and repetition;
3. page/column reading order;
4. question-region detection;
5. semantic block classification for stem, `<보기>` propositions, final answer choices, images/tables, and answer rows;
6. subject-adapter metadata normalization.

`㉠` through `㉭` are proposition labels inside the stem. `①` through `⑤` are final-choice markers. When OCR loses circled-number glyphs, a same-baseline row with four stable horizontal cells is recovered from coordinates. A text-only fallback may parse explicit numbered choices, but it cannot promote proposition labels to answer choices.

The four subject importers call the shared parser and retain only subject metadata, topic tagging, known exam grouping, and answer-table association. Their duplicated choice-splitting regexes are removed.

### Quality gate

Every candidate receives structural diagnostics. An importable question must have:

- a non-empty stem;
- exactly four or five non-placeholder choices;
- unique sequential choice numbers;
- no proposition-label sequence promoted into choices;
- no footer, page counter, advertisement, next-question header, or answer-table row in any choice;
- a valid answer where an answer source exists;
- confidence at or above the configured import threshold.

Candidates that fail are written to a review queue with source PDF, page, crop reference, reason codes, OCR text, and detected blocks. They are never converted to generic placeholder choices and never saved as valid questions.

## Reprocessing and database replacement

Create a reprocessing command that inventories the 30 PDFs, filters roles, extracts/caches structured pages, parses all 12 question papers, associates the 15 answer/explanation files, and writes a new staging SQLite database. It produces JSON/CSV validation reports but does not mutate the mounted DB during parsing.

Validation is performed per source exam set. Required checks include expected question count, question-number coverage, answer coverage, structural-quality pass rate, zero placeholder choices, source provenance, and duplicate detection. The 2026 law Q8 golden assertion requires the complete `㉠`–`㉣` proposition block in the stem and choices `44`, `46`, `48`, `50`.

After all required sets pass, the command:

1. closes connections;
2. creates a timestamped backup of `data/domain_dbs/exam_bank.Maritime.db`;
3. verifies the staging DB with SQLite integrity and application schema validation;
4. atomically replaces the mounted DB;
5. writes a replacement receipt containing hashes, counts, validation summary, and backup path.

On any failure the mounted DB remains unchanged.

## Tests and acceptance

Unit tests cover coordinate normalization, per-page columns, fake text layers, semantic block roles, proposition/choice separation, four-cell choice-row recovery, footer removal, and quality rejection. Golden regression tests use sanitized OCR tokens and a cropped fixture derived from the 2026 maritime-law page 2 without committing the source PDF.

Integration tests cover native two-column 2023 papers, scanned multi-year papers, document-role filtering, staging database creation, replacement rollback, and mounted repository readability.

Completion requires:

- full project test suite passing;
- all 30 files inventoried and 12 question papers classified;
- zero generic placeholder choices in staging;
- the 2026 maritime-law Q8 golden result passing;
- all required exam sets passing validation or the replacement being blocked;
- mounted DB backup, replacement receipt, and post-replacement smoke query;
- source changes committed and pushed, while PDFs, OCR caches, reports containing source content, backups, and databases remain untracked.
