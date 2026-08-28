# Multiformat import roadmap

Current user-facing import remains PDF only. HWPX parsing exists as a local adapter candidate and is not reachable from GUI or CLI.

## Phase 1 (merged)

- Immutable `DocumentSourceIR`
- Content signature detection for PDF / HWP 5 CFB / HWPX package
- Thin `PdfSourceAdapter` over the existing PDF extractor

## Phase 2 (this local feature candidate)

- `HwpxSourceAdapter` using exact `hwpxkit==0.2.1`
- Private sanitized HWPX fixtures remain local-only and are not committed

## Future phases (not implemented)

3. HWP adapter using `hwp-hwpx-parser==1.0.0` (`SELECTED_NOT_INTEGRATED`)
4. Direct HWP vs conversion-fallback qualification
5. Common `ExamStructureParser`
6. Unified GUI import routing
7. Packaging qualification beyond the candidate spec collection
8. Optional differential oracles

Do not present HWP or HWPX import as a current product feature.
