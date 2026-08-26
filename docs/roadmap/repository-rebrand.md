# Repository Rebrand Checklist

> Target product name: **Exam Generator**
>
> Target repository name: `exam-generator`
>
> Status: application and documentation foundation prepared on a review branch; repository rename remains a separate owner action after merge acceptance.

## Changes included in the foundation

- desktop window title changed to `Exam Generator`;
- Windows AppUserModelID changed to `CAPTW.ExamGenerator`;
- home screen value proposition refreshed;
- export navigation renamed to format-neutral wording;
- Korean and English menu packs aligned;
- product-first README introduced;
- HWPX and Exam Pack boundaries documented;
- focused Windows CI added for branding, menu, and launcher contracts.

## Compatibility intentionally preserved

The rebrand must not silently relocate or invalidate user data. The foundation therefore preserves:

- `data/exam_bank.db` and current runtime paths;
- SQLite schema and migration history;
- `.examdb.zip` package format;
- `ExamGenerator.spec` and `ExamGenerator.exe` packaging identity;
- existing launchers;
- current parser, importer, practice, and DOCX behavior;
- existing Git history and releases.

Internal package and database identifiers should change only when a migration provides backward compatibility.

## Rename sequence

1. Merge the accepted rebrand foundation.
2. Record the accepted main-branch commit and green checks.
3. Create a repository backup or verified mirror.
4. Rename the GitHub repository from `exam-weaver-archive` to `exam-generator`.
5. Confirm GitHub redirects for the old repository URL.
6. Update local clones:

   ```powershell
   git remote set-url origin https://github.com/CAPTW/exam-generator.git
   git remote -v
   git fetch --prune origin
   ```

7. Update README badges, raw asset URLs, release references, issue templates, and external documentation that still use the old path.
8. Verify clone, source launch, packaged launch, and pull-request checks from the renamed repository.
9. Update GitHub About and topics.
10. Publish a short migration note explaining that user databases and `.examdb.zip` packages are unchanged.

## Proposed GitHub About

```text
Local-first exam document parser and question-bank workspace for reviewing, practising, and exporting editable exams.
```

## Proposed topics

```text
exam-generator
question-bank
pdf-parsing
ocr
pymupdf
pyqt5
sqlite
docx
korean-exams
local-first
```

Add `hwpx` only after the HWPX acceptance gates pass and the feature is present in a released build.

## Post-rename search audit

Search the active source and user-facing documentation for:

```text
Exam Weaver Archive
exam-weaver-archive
CAPTW.ExamWeaverArchive
기출문제 문제은행 관리자
```

Historical plans and archived technical references may retain old names when changing them would rewrite project history. Current README, app UI, launch instructions, packaging metadata, and release documentation should use the new brand.

## Rollback

If the renamed repository fails a required clone, CI, packaging, or release-path check:

1. stop further release publication;
2. preserve the failing evidence;
3. restore references or rename the repository back;
4. verify the original remote and launch path;
5. correct the rebrand on a branch before attempting the rename again.

A GitHub repository rename must not be combined with an unverified data migration, schema migration, HWPX implementation, or Exam Pack extraction.
