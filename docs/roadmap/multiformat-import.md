# Multiformat import roadmap

Current user-facing import remains PDF only.

## Phase 1 (this branch)

- Immutable `DocumentSourceIR`
- Content signature detection for PDF / HWP 5 CFB / HWPX package
- Thin `PdfSourceAdapter` over the existing PDF extractor
- No HWP/HWPX runtime dependency

## Future phases (not implemented)

2. HWPX adapter using `hwpxkit==0.2.1` (`SELECTED_HWPX_PARSER_NOT_INTEGRATED`)
3. HWP adapter using `hwp-hwpx-parser==1.0.0` (`SELECTED_HWP_PARSER_NOT_INTEGRATED`)
4. Direct HWP vs conversion-fallback qualification
5. Common `ExamStructureParser`
6. Unified GUI import routing
7. Packaging integration
8. Optional differential oracles

Do not present HWP or HWPX import as a current product feature.
