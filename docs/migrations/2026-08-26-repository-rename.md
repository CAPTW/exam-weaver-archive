# Repository Rename Migration Note — 2026-08-26

The GitHub repository was renamed from:

```text
CAPTW/exam-weaver-archive
```

to:

```text
CAPTW/exam-generator
```

## What changed

- canonical repository URL;
- HTTPS, SSH, Git, API, pull-request, workflow, and release paths now use `CAPTW/exam-generator`;
- product-facing documentation and application branding use **Exam Generator**.

## What did not change

- stable GitHub repository ID `1002195620`;
- Git history, branches, tags, pull requests, workflow history, stars, and releases;
- default branch `main`;
- accepted rebrand merge commit `e6033668eb8daa0ed6467c3382db48840f943d56`;
- `data/exam_bank.db` and local runtime paths;
- SQLite schema and migrations;
- `.examdb.zip` package compatibility;
- Parser, importer, practice, DB mount, and current DOCX export behavior.

## Existing local clones

Set the canonical remote explicitly:

```powershell
git remote set-url origin https://github.com/CAPTW/exam-generator.git
git remote -v
git fetch --prune origin
```

The retired repository URL currently resolves to the renamed repository. It should not be reused for a different repository while that redirect remains necessary.

## Data compatibility

This repository rename is not a data migration. Existing user databases and `.examdb.zip` packages do not need conversion solely because the GitHub slug changed.
