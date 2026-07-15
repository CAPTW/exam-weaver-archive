# Multi-Exam DOCX Export Design

## Context

The Export Exam screen currently supports one selected exam at a time. Its
multi-subject table can combine subjects only because every row reuses the
single `exam_code` selected in the exam combo box. After mounted repositories
were connected to Export, users can see every mounted exam, but they still
cannot compose one DOCX from subjects that belong to different exams.

`DocxExporter` already accepts ordered sections, so this change is limited to
the Export screen's selection model, repository queries, validation, and
document metadata. The DOCX rendering engine does not need a new output model.

## Goals

- Allow subjects from different exams and mounted databases to be selected for
  one DOCX.
- Assign an independent positive question count to every selected subject.
- Apply one shared year range and hashtag filter to all selected subjects.
- Preserve the existing single-exam export workflow without behavior changes.
- Preserve group-aware selection, random-eligibility validation, and logical
  duplicate removal across the entire composed document.
- Keep mounted exam and subject identifiers namespaced for repository queries,
  while displaying readable mount, exam, and subject labels.

## Non-Goals

- Per-exam or per-subject year ranges and hashtag filters.
- Mixing different grading or answer-key policies within one document.
- Persisting reusable export presets.
- Changing the DOCX page layout or question rendering format.

## User Interface

Add a `Combine subjects from multiple exams` checkbox above the subject
selection table.

When the checkbox is off:

- The exam and subject combo boxes retain their current behavior.
- The table lists only the subjects of the selected exam.
- Existing single-subject, whole-exam, and same-exam multi-subject exports work
  as before.

When the checkbox is on:

- The exam and subject combo boxes and the single random-count control are
  disabled because they do not participate in composed selection.
- The table is rebuilt from every exam returned by
  `repository.get_filter_options()` and every subject returned by
  `repository.get_subject_options(exam_code)`.
- The table columns are `Use`, `Database`, `Exam`, `Subject`, and `Questions`.
- Every row has an independent checkbox and question-count spin box.
- `Apply to all subjects` selects every displayed row and applies the shared
  count value to it.
- Switching modes or replacing the repository rebuilds the table and clears
  hidden selections so stale rows cannot affect a later export.

The labels use the mounted repository metadata when available. Database labels
come from `mount_label`; exam and subject names use their human-readable names
and local codes rather than namespaced codes.

## Selection Model

Each table row stores these values independently of its widgets:

- `exam_code`: repository-facing exam code, including its mount namespace.
- `exam_name`: readable exam name.
- `subject_code`: repository-facing subject code, including its mount
  namespace.
- `subject_name`: readable subject name.
- `mount_label`: readable database label when available.
- `section_title`: `Database · Exam · Subject`, omitting empty components.
- Checkbox and question-count spin-box references.

The selected-request collector returns the row's exam and subject codes along
with its count and section title. A checked row with a count of zero is invalid;
its section title is included in the validation error.

## Data Flow

For each selected request, in visible table order:

1. Query `get_questions_with_choices()` with that request's own `exam_code` and
   `subject_code`, plus the shared year range and hashtag filter.
2. Enforce the year range defensively on returned records.
3. Remove question groups containing a random-ineligible child.
4. Deduplicate logical content within that request.
5. Count available questions after excluding content already selected by an
   earlier section.
6. Select the requested number with the existing group-aware random selector.
7. Add selected content fingerprints to the document-wide exclusion set.
8. Append a DOCX section using the request's `section_title`.

This keeps grouped questions atomic and prevents exact or similarity-based
logical duplicates from appearing in different exam sections.

## Document Metadata

Multi-exam composition uses a neutral document title rather than the currently
selected exam combo-box text:

`YYYY.MM.DD Multi-exam mock exam`

The default filename is:

`multi_exam_<from>-<to>_rand<total>.docx`

For a single-year range, the filename uses that year once. Namespaced database
codes never enter the filename.

Each DOCX section heading uses the row's `Database · Exam · Subject`
label. Question numbering continues across section boundaries.

## Validation and Error Handling

- At least one composed row must be selected.
- Every selected row must request at least one question.
- The shared start year must not exceed the end year.
- If a section has fewer valid unique questions than requested after global
  duplicate exclusion, export stops before opening or writing the output file.
- The error identifies the failing database, exam, and subject and reports the
  requested and available counts.
- Repository or file-export exceptions continue to use the existing error
  notification path.

## Backward Compatibility

- Multi-exam mode is off by default.
- Existing constructor injection and `set_repository()` behavior remain the
  source of Export repository data.
- Existing single-exam export tests and filenames remain unchanged.
- The composed selection path reuses the current validator, deduplication, and
  group-aware selection functions rather than introducing a parallel algorithm.

## Test Strategy

Automated tests will verify:

- Multi-exam mode populates exam-subject pairs from multiple mounted exams and
  renders database, exam, and subject labels separately.
- Mode switching disables the irrelevant single-exam controls and rebuilds
  rows without retaining hidden selections.
- Selected requests retain the correct namespaced `exam_code` and
  `subject_code` for every row.
- Repository calls use each row's exam and subject codes with the common year
  and hashtag filters.
- One DOCX receives ordered sections from different exams with continuous
  question numbering.
- Logical duplicates across exams are not selected twice.
- Grouped questions remain atomic.
- Invalid counts and insufficient unique-question errors identify the affected
  section.
- Multi-exam titles and filenames do not depend on the single exam combo box or
  contain namespaced filename separators.
- Existing Export interface and full application regression suites continue to
  pass.

## Acceptance Criteria

With the current mount manifest loaded, a user can enable multi-exam mode,
select subjects belonging to at least two different exam codes, assign a count
to each, apply one year range and optional hashtag filter, and export one DOCX.
The document contains a clearly labeled section for every selected row, uses
the requested number of valid unique questions per section, contains no logical
duplicate across sections, and leaves the existing single-exam mode unchanged.
