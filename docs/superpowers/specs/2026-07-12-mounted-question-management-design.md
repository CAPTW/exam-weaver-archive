# Mounted database question management design

## Goal

The Question Management tab must treat every enabled database mount as one searchable question collection while routing every write back to the database that owns the selected question. Users can directly customize mounted databases by editing, deleting, and changing explanations.

## Scope

- Aggregate questions, exam filters, and subject filters from all enabled mounts.
- Display the owning mount in filters and question rows so identical exam or subject codes remain distinguishable.
- Route question lookup, edit, deletion, bulk deletion, explanation updates, and validation to the owning mount.
- Refresh Question Management immediately after mount settings are saved or a database is imported, created, renamed, or otherwise changes the active mount list.
- Preserve the existing single-database behavior when no mount manifest exists.

Practice, export, import, and mock-exam authoring are outside this change. Their existing repository wiring remains unchanged.

## Architecture

`MountedExamRepository` becomes the repository used by `BrowserInterface` when a mount manifest exists. It remains an aggregate facade for reads and gains write routing methods compatible with the subset of `ExamRepository` used by Question Management and `QuestionValidator`.

Each aggregate question ID has the form `mount_id::local_id`. Filter values use the existing namespaced exam and subject codes. The facade splits these values, resolves the enabled mount, opens an `ExamRepository` for that database, and passes only the local ID or code to it. The UI never guesses a destination database from the current filter.

If no manifest exists, `BrowserInterface` continues to receive a normal `ExamRepository` for the application database. This keeps development, first-run, and legacy installations working.

## Read behavior

- `get_filter_options()` returns namespaced exam codes and mount metadata.
- `get_subject_options()` returns namespaced subject codes and mount metadata.
- `search_questions()` returns namespaced question IDs plus `mount_id`, `mount_label`, and `local_id`.
- The aggregate limit is applied after results from all matching mounts are merged and globally sorted. A limit must not be consumed independently by an earlier mount.
- Question rows show the mount label in the information column.
- Exam and subject filter labels include the mount label.
- `get_question()` resolves one namespaced ID, loads its choices from its owning database, and returns the same namespaced identity fields used by search results.

## Write behavior

Mounted databases are directly customizable. The manifest's `read_only` field does not block Question Management writes. It remains useful for read-only connection choices in other flows, but write routing opens the target through `ExamRepository`.

The facade provides these operations:

- `update_question(namespaced_id, data)`
- `update_question_explanation(namespaced_id, explanation)`
- `delete_question(namespaced_id)`
- `delete_questions(namespaced_ids)`

Each operation rejects an unnamespaced ID in mounted mode, an unknown mount ID, or a mount that is no longer enabled. Bulk deletion groups IDs by mount and executes each group against its owning database. Existing `ExamRepository` transactions and cascade cleanup remain authoritative within each database.

The editor receives local subject options for the owning exam but submits through the aggregate facade. Any database-level write failure is surfaced to the user with the mount label and the original error summary; the application must not silently redirect a write to the default database.

## Validation

`QuestionValidator` continues to depend on repository-style read methods. It receives the mounted facade from `BrowserInterface`, so validation results retain namespaced IDs and all fix, edit, explanation, and delete actions route correctly.

## Mount lifecycle and refresh

`MainWindow` constructs the Question Management repository from `data/domain_dbs/mount_manifest.json` when present, otherwise from the application DB. `DbMountInterface` emits a mount-change signal after persisted mount selection, import, creation, rename, and other manifest-changing actions. `MainWindow` responds by rebuilding or reloading the browser repository and refreshing filters and rows.

Unsaved checkbox changes do not affect Question Management until Mount settings are saved. A mount removed or disabled between display and write produces a clear stale-selection error and triggers a refresh.

## Error handling

- Missing manifest: use the application DB.
- Malformed manifest or missing enabled database: show a mount-load error and keep the application DB available rather than leaving the tab unusable.
- OS-level permission or SQLite write failure: keep the row visible, make no fallback write, and show the owning mount and error.
- Duplicate local IDs across databases: safe because all UI and facade operations use namespaced IDs.
- Empty enabled-mount set: use the application DB fallback mount so Question Management remains useful.

## Tests

Repository tests will prove:

- Aggregate filters and searches include enabled mounts and exclude disabled mounts.
- Global limit and sorting work across mounts.
- Namespaced lookup returns choices from the owning database.
- Edit, explanation update, single delete, and multi-mount bulk delete affect only the owning databases.
- Writes work even when a mount is marked `read_only` in the manifest.
- Invalid, unknown, disabled, and unnamespaced identifiers cannot write to another database.

GUI tests will prove:

- The Question Management table shows rows from multiple mounts with mount labels.
- Namespaced exam and subject filters select the correct mount.
- Editor, explanation, and delete actions pass the namespaced ID through the facade.
- Saving mount settings refreshes browser filters and rows without restarting the app.
- Missing or invalid manifests fall back to the application DB with a visible error for invalid configuration.

The existing repository, browser filter, mount-management, and explanation workflow tests must remain green.
