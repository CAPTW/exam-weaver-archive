# Repository Rename Record

> Product name: **Exam Generator**
>
> Canonical repository: `CAPTW/exam-generator`
>
> Previous repository slug: `CAPTW/exam-weaver-archive`
>
> Status: **completed and remotely verified on 2026-08-26**

## Accepted authority

- Stable GitHub repository ID: `1002195620`
- Default branch: `main`
- Accepted rebrand merge commit: `e6033668eb8daa0ed6467c3382db48840f943d56`
- Commit tree: `018c99efbbd6111c8b42a2de61456c476e688758`
- Merge source: PR `#6`, `Rebrand foundation: Exam Generator`
- Final pre-merge contract workflow: `Rebrand foundation checks` run `#17`
- Workflow result: `completed / success`
- Windows contract tests: `34 passed`
- Portable contract tests: `15 passed`

## Completed changes

- desktop window title changed to `Exam Generator`;
- Windows AppUserModelID changed to `CAPTW.ExamGenerator`;
- home-screen value proposition refreshed;
- export navigation renamed to format-neutral wording;
- Korean and English menu packs aligned;
- product-first README introduced;
- HWPX and Exam Pack boundaries documented;
- focused Windows and portable CI contracts added;
- PR #6 reviewed and squash-merged into `main`;
- GitHub repository renamed from `exam-weaver-archive` to `exam-generator`;
- new HTTPS clone URL confirmed as `https://github.com/CAPTW/exam-generator.git`;
- the previous repository identifier confirmed to resolve to the same stable repository ID and canonical new slug;
- README and roadmap paths confirmed under the renamed repository;
- the successful pre-rename workflow run confirmed accessible under the renamed repository URL.

## Compatibility preserved

The rename did not relocate or invalidate user data. The following remain unchanged:

- `data/exam_bank.db` and current runtime paths;
- SQLite schema and migration history;
- `.examdb.zip` package format;
- `ExamGenerator.spec` and `ExamGenerator.exe` packaging identity;
- existing launchers;
- current parser, importer, practice, and DOCX behavior;
- existing Git history, pull requests, workflow runs, stars, and releases.

Internal package and database identifiers should change only when a migration provides backward compatibility.

## Local clone update

Existing clones may continue to work through GitHub redirect handling, but the canonical remote should be set explicitly:

```powershell
git remote set-url origin https://github.com/CAPTW/exam-generator.git
git remote -v
git fetch --prune origin
```

Expected canonical output:

```text
origin  https://github.com/CAPTW/exam-generator.git (fetch)
origin  https://github.com/CAPTW/exam-generator.git (push)
```

Do not create a new repository using the retired `exam-weaver-archive` slug while the redirect is required.

## Remaining repository-profile hygiene

The repository rename is complete. The following profile-level improvements are separate, non-blocking follow-ups:

### GitHub About

```text
Local-first exam document parser and question-bank workspace for reviewing, practising, and exporting editable exams.
```

### GitHub topics

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

## Post-rename source audit policy

Search active source and current user-facing documentation for obsolete product identifiers:

```text
Exam Weaver Archive
exam-weaver-archive
CAPTW.ExamWeaverArchive
기출문제 문제은행 관리자
```

Historical plans, old release notes, commit messages, and archived technical references may retain old names when changing them would rewrite history. Current README, app UI, launch instructions, packaging metadata, and new release documentation should use the new brand and canonical repository slug.

## Rollback boundary

No rollback is currently required. If a future clone, CI, packaging, or release-path failure is traced specifically to the rename:

1. stop affected release publication;
2. preserve the failing evidence;
3. verify the stable repository ID and canonical remote;
4. repair stale URLs or local remotes before considering a repository rename reversal;
5. keep data migration, schema migration, HWPX implementation, and Exam Pack extraction outside the rename recovery boundary.
