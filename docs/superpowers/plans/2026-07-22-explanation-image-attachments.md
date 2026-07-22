# Explanation Image Attachments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one managed image attachment to each question explanation in problem management, the question editor, and practice mode while keeping a multi-image-ready database model.

**Architecture:** Store attachment metadata in a new `question_explanation_images` table and copy committed files into `data/explanation_images`. A focused image-store module owns validation, relative-path resolution, candidate staging, and safe deletion; repositories own database transactions and reference checks. A reusable editor widget supplies the same select/paste/delete behavior to both editing surfaces, while practice mode renders the first attachment read-only.

**Tech Stack:** Python 3, PyQt5, QFluentWidgets, SQLite, pytest

## Global Constraints

- Phase 1 exposes at most one explanation image per question, always at `display_order = 0`.
- Persist metadata as a list so phase 2 can support multiple inline images without moving phase-1 rows.
- Store committed images beneath `data/explanation_images` with UUID filenames and database-relative paths.
- Accept PNG, JPG, and JPEG files only after successful Qt image decoding; clipboard candidates are PNG.
- Never delete an external file or any managed file still referenced by another attachment row.
- Problem management and the question editor can select, paste, and remove an image; practice mode is read-only.
- DOCX export, multiple-image editing, HTML storage, and inline placement are out of scope.
- Preserve the existing exam/subject stacked filter layout and its tests while modifying `browser.py`.

---

### Task 1: Managed explanation image store

**Files:**
- Create: `src/explanation_images.py`
- Modify: `src/runtime_paths.py`
- Create: `tests/test_explanation_images.py`

**Interfaces:**
- Produces: `ExplanationImageChange.keep()`, `.remove()`, and `.replace(source_path)`.
- Produces: `ExplanationImageStore(base_dir=None)` with `resolve()`, `validate_source()`, `import_file()`, `save_clipboard_candidate()`, `discard_candidate()`, `is_managed()`, and `remove_managed()`.
- Produces: `get_explanation_image_dir()` and `get_explanation_image_candidate_dir()` runtime paths.

- [ ] **Step 1: Write failing store tests**

```python
from pathlib import Path

from PyQt5.QtGui import QImage

from src.explanation_images import ExplanationImageChange, ExplanationImageStore


def test_store_imports_valid_image_with_relative_uuid_path(tmp_path):
    source = tmp_path / "source.jpg"
    assert QImage(8, 6, QImage.Format_RGB32).save(str(source), "JPG")
    store = ExplanationImageStore(tmp_path / "app")

    stored = store.import_file(source)

    assert stored.startswith("data/explanation_images/")
    assert stored.endswith(".jpg")
    assert store.resolve(stored).is_file()
    assert store.resolve(stored).read_bytes() == source.read_bytes()


def test_store_rejects_invalid_or_unsupported_files(tmp_path):
    invalid = tmp_path / "bad.png"
    invalid.write_text("not an image", encoding="utf-8")
    unsupported = tmp_path / "image.gif"
    assert QImage(2, 2, QImage.Format_RGB32).save(str(unsupported), "PNG")
    store = ExplanationImageStore(tmp_path / "app")

    with pytest.raises(ValueError, match="읽을 수 없는 이미지"):
        store.import_file(invalid)
    with pytest.raises(ValueError, match="PNG, JPG, JPEG"):
        store.import_file(unsupported)


def test_store_only_removes_managed_files_and_discards_candidates(tmp_path):
    store = ExplanationImageStore(tmp_path / "app")
    external = tmp_path / "external.png"
    assert QImage(2, 2, QImage.Format_RGB32).save(str(external), "PNG")
    candidate = store.save_clipboard_candidate(QImage(str(external)))
    managed = store.import_file(candidate)

    assert store.remove_managed(str(external)) is False
    assert external.exists()
    assert store.remove_managed(managed) is True
    assert not store.resolve(managed).exists()
    assert store.discard_candidate(candidate) is True
    assert not Path(candidate).exists()


def test_image_change_value_object_is_explicit():
    assert ExplanationImageChange.keep().action == "keep"
    assert ExplanationImageChange.remove().action == "remove"
    assert ExplanationImageChange.replace("source.png").source_path == "source.png"
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_explanation_images.py -q`

Expected: collection fails because `src.explanation_images` does not exist.

- [ ] **Step 3: Add runtime paths and the store implementation**

```python
# src/runtime_paths.py
def get_explanation_image_dir(base_dir=None) -> Path:
    return get_data_dir(base_dir) / "explanation_images"


def get_explanation_image_candidate_dir() -> Path:
    return Path(tempfile.gettempdir()) / "exam_weaver" / "explanation_image_candidates"
```

```python
# src/explanation_images.py
@dataclass(frozen=True)
class ExplanationImageChange:
    action: Literal["keep", "remove", "replace"]
    source_path: str | None = None

    @classmethod
    def keep(cls):
        return cls("keep")

    @classmethod
    def remove(cls):
        return cls("remove")

    @classmethod
    def replace(cls, source_path):
        if not str(source_path or "").strip():
            raise ValueError("교체할 해설 이미지 경로가 필요합니다.")
        return cls("replace", str(source_path))


class ExplanationImageStore:
    allowed_suffixes = {".png", ".jpg", ".jpeg"}

    def __init__(self, base_dir=None):
        self.base_dir = Path(base_dir).resolve() if base_dir else get_base_dir()
        self.image_dir = get_explanation_image_dir(self.base_dir)
        self.candidate_dir = get_explanation_image_candidate_dir()

    def resolve(self, stored_path):
        path = Path(str(stored_path or ""))
        return path.resolve() if path.is_absolute() else (self.base_dir / path).resolve()

    def validate_source(self, source_path):
        path = Path(source_path).resolve()
        if path.suffix.lower() not in self.allowed_suffixes:
            raise ValueError("해설 이미지는 PNG, JPG, JPEG만 사용할 수 있습니다.")
        if not path.is_file() or QImage(str(path)).isNull():
            raise ValueError("읽을 수 없는 이미지 파일입니다.")
        return path

    def import_file(self, source_path):
        source = self.validate_source(source_path)
        self.image_dir.mkdir(parents=True, exist_ok=True)
        target = self.image_dir / f"{uuid.uuid4().hex}{source.suffix.lower()}"
        shutil.copy2(source, target)
        return target.relative_to(self.base_dir).as_posix()

    def save_clipboard_candidate(self, image):
        if image is None or image.isNull():
            raise ValueError("클립보드에 이미지가 없습니다.")
        self.candidate_dir.mkdir(parents=True, exist_ok=True)
        target = self.candidate_dir / f"{uuid.uuid4().hex}.png"
        if not image.save(str(target), "PNG"):
            raise OSError("클립보드 이미지를 임시 파일로 저장하지 못했습니다.")
        return str(target)
```

Add the boundary-safe deletion methods:

```python
    @staticmethod
    def _is_within(path, directory):
        try:
            path.resolve().relative_to(directory.resolve())
            return True
        except ValueError:
            return False

    def is_managed(self, stored_path):
        return self._is_within(self.resolve(stored_path), self.image_dir)

    def remove_managed(self, stored_path):
        path = self.resolve(stored_path)
        if not self._is_within(path, self.image_dir):
            return False
        path.unlink(missing_ok=True)
        return True

    def discard_candidate(self, candidate_path):
        path = Path(candidate_path).resolve()
        if not self._is_within(path, self.candidate_dir):
            return False
        path.unlink(missing_ok=True)
        return True
```

- [ ] **Step 4: Run store tests and verify GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_explanation_images.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit the store**

```powershell
git add src/explanation_images.py src/runtime_paths.py tests/test_explanation_images.py
git commit -m "Add managed explanation image store"
```

---

### Task 2: Attachment schema and read model

**Files:**
- Modify: `src/database/schema.sql`
- Modify: `src/database/repository.py`
- Modify: `tests/test_repository.py`

**Interfaces:**
- Consumes: `ExplanationImageStore` from Task 1.
- Produces: `ExamRepository(db_path, explanation_image_store=None)`.
- Produces: question dictionaries with `explanation_images: list[dict]` sorted by `display_order`.

- [ ] **Step 1: Write failing migration and query tests**

```python
def test_explanation_image_table_is_migrated_and_exposed(repo, sample_metadata, sample_question):
    repo.save_questions([sample_question], sample_metadata)
    question = repo.get_questions_with_choices(limit=1)[0]
    with sqlite3.connect(repo.db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(question_explanation_images)")}
        conn.execute(
            "INSERT INTO question_explanation_images "
            "(question_id, image_path, display_order, alt_text) VALUES (?, ?, 0, ?)",
            (question["id"], "data/explanation_images/a.png", "출력 계산식"),
        )

    loaded = repo.get_question(question["id"])
    listed = repo.get_questions_with_choices(limit=1)[0]

    assert columns == {"id", "question_id", "image_path", "display_order", "alt_text", "created_at"}
    assert loaded["explanation_images"][0]["alt_text"] == "출력 계산식"
    assert listed["explanation_images"][0]["image_path"].endswith("a.png")
```

- [ ] **Step 2: Run the test and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_repository.py::test_explanation_image_table_is_migrated_and_exposed -q`

Expected: fail because the table or `explanation_images` key is missing.

- [ ] **Step 3: Add schema and batch attachment loading**

```sql
CREATE TABLE IF NOT EXISTS question_explanation_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    image_path TEXT NOT NULL,
    display_order INTEGER NOT NULL DEFAULT 0,
    alt_text TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(question_id, display_order)
);
CREATE INDEX IF NOT EXISTS idx_explanation_images_question
ON question_explanation_images(question_id, display_order);
```

```python
def _explanation_images_by_question(self, conn, question_ids):
    result = {question_id: [] for question_id in question_ids}
    if not question_ids:
        return result
    placeholders = ",".join("?" for _ in question_ids)
    rows = conn.execute(
        f"SELECT id, question_id, image_path, display_order, alt_text "
        f"FROM question_explanation_images WHERE question_id IN ({placeholders}) "
        "ORDER BY question_id, display_order",
        question_ids,
    ).fetchall()
    for row in rows:
        item = dict(row)
        result[item["question_id"]].append(item)
    return result
```

Call this helper from `get_question()` and `get_questions_with_choices()`. Initialize every returned question with an empty list when no attachment exists. Enable `PRAGMA foreign_keys = ON` in `_get_connection()`.

- [ ] **Step 4: Run repository tests and verify GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_repository.py -q`

Expected: all repository tests pass.

- [ ] **Step 5: Commit schema and read model**

```powershell
git add src/database/schema.sql src/database/repository.py tests/test_repository.py
git commit -m "Add explanation attachment read model"
```

---

### Task 3: Transactional attachment writes and cleanup

**Files:**
- Modify: `src/database/repository.py`
- Modify: `tests/test_repository.py`

**Interfaces:**
- Consumes: `ExplanationImageChange` and `ExplanationImageStore`.
- Extends: `update_question_explanation(question_id, explanation, image_change=None)`.
- Consumes: `data["explanation_image_change"]` in `update_question()` and `create_manual_question()`.

- [ ] **Step 1: Write failing lifecycle tests**

```python
def test_explanation_image_add_replace_remove_and_question_delete(tmp_path, sample_metadata, sample_question):
    store = ExplanationImageStore(tmp_path / "app")
    repo = ExamRepository(str(tmp_path / "bank.db"), explanation_image_store=store)
    repo.init_database()
    repo.save_questions([sample_question], sample_metadata)
    question_id = repo.get_questions_with_choices(limit=1)[0]["id"]
    first = _png(tmp_path / "first.png")
    second = _png(tmp_path / "second.png")

    assert repo.update_question_explanation(question_id, "해설", ExplanationImageChange.replace(first))
    first_stored = repo.get_question(question_id)["explanation_images"][0]["image_path"]
    assert store.resolve(first_stored).exists()

    assert repo.update_question_explanation(question_id, "교체", ExplanationImageChange.replace(second))
    second_stored = repo.get_question(question_id)["explanation_images"][0]["image_path"]
    assert not store.resolve(first_stored).exists()
    assert store.resolve(second_stored).exists()

    assert repo.update_question_explanation(question_id, "텍스트만", ExplanationImageChange.remove())
    assert repo.get_question(question_id)["explanation_images"] == []
    assert not store.resolve(second_stored).exists()


def test_failed_database_write_removes_new_managed_file_and_keeps_old_state(
    tmp_path, sample_metadata, sample_question, monkeypatch
):
    store = ExplanationImageStore(tmp_path / "app")
    repo = ExamRepository(str(tmp_path / "bank.db"), explanation_image_store=store)
    repo.init_database()
    repo.save_questions([sample_question], sample_metadata)
    question_id = repo.get_questions_with_choices(limit=1)[0]["id"]
    first = _png(tmp_path / "first.png")
    second = _png(tmp_path / "second.png")
    assert repo.update_question_explanation(
        question_id, "원본", ExplanationImageChange.replace(first)
    )
    original = repo.get_question(question_id)
    original_path = original["explanation_images"][0]["image_path"]
    original_files = set(store.image_dir.glob("*"))

    def fail_write(*_args, **_kwargs):
        raise sqlite3.OperationalError("forced failure")

    monkeypatch.setattr(repo, "_write_explanation_image_row", fail_write)
    assert repo.update_question_explanation(
        question_id, "변경", ExplanationImageChange.replace(second)
    ) is False

    loaded = repo.get_question(question_id)
    assert loaded["explanation"] == "원본"
    assert loaded["explanation_images"][0]["image_path"] == original_path
    assert set(store.image_dir.glob("*")) == original_files
```

Add these explicit tests in the same file:

```python
def test_update_question_persists_explanation_image_change(
    tmp_path, sample_metadata, sample_question
):
    store = ExplanationImageStore(tmp_path / "app")
    repo = ExamRepository(str(tmp_path / "bank.db"), explanation_image_store=store)
    repo.init_database()
    repo.save_questions([sample_question], sample_metadata)
    question_id = repo.get_questions_with_choices(limit=1)[0]["id"]
    source = _png(tmp_path / "update.png")
    loaded = repo.get_question(question_id)
    loaded["question_text"] = "수정된 문제"
    loaded["explanation_image_change"] = ExplanationImageChange.replace(source)
    assert repo.update_question(question_id, loaded)
    assert len(repo.get_question(question_id)["explanation_images"]) == 1


def test_create_and_clone_copy_explanation_images_independently(
    tmp_path, sample_metadata, sample_question
):
    store = ExplanationImageStore(tmp_path / "app")
    repo = ExamRepository(str(tmp_path / "bank.db"), explanation_image_store=store)
    repo.init_database()
    repo.save_questions([sample_question], sample_metadata)
    source_id = repo.get_questions_with_choices(limit=1)[0]["id"]
    source = _png(tmp_path / "clone.png")
    template = repo.get_manual_question_clone_template(source_id)
    template["explanation_image_change"] = ExplanationImageChange.replace(source)
    first_id = repo.create_manual_question(template)
    first_path = repo.get_question(first_id)["explanation_images"][0]["image_path"]
    clone = repo.get_manual_question_clone_template(first_id)
    clone["explanation_image_change"] = ExplanationImageChange.replace(
        repo.explanation_image_store.resolve(first_path)
    )
    second_id = repo.create_manual_question(clone)
    second_path = repo.get_question(second_id)["explanation_images"][0]["image_path"]
    assert first_path != second_path
    assert repo.explanation_image_store.resolve(first_path).read_bytes() == repo.explanation_image_store.resolve(second_path).read_bytes()


def test_single_and_bulk_question_delete_remove_unreferenced_managed_files(
    tmp_path, sample_metadata, sample_question
):
    store = ExplanationImageStore(tmp_path / "app")
    repo = ExamRepository(str(tmp_path / "bank.db"), explanation_image_store=store)
    repo.init_database()
    repo.save_questions([sample_question], sample_metadata)
    source_id = repo.get_questions_with_choices(limit=1)[0]["id"]
    ids = []
    paths = []
    for number in range(1, 4):
        source = _png(tmp_path / f"delete-{number}.png")
        template = repo.get_manual_question_clone_template(source_id)
        template["question_number"] = number
        template["explanation_image_change"] = ExplanationImageChange.replace(source)
        question_id = repo.create_manual_question(template)
        ids.append(question_id)
        paths.append(repo.get_question(question_id)["explanation_images"][0]["image_path"])

    first_id, second_id, third_id = ids
    first_path, second_path, third_path = paths
    assert repo.delete_question(first_id)
    assert not store.resolve(first_path).exists()
    assert repo.delete_questions([second_id, third_id]) == 2
    assert not store.resolve(second_path).exists()
    assert not store.resolve(third_path).exists()
```

- [ ] **Step 2: Run lifecycle tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_repository.py -k "explanation_image" -q`

Expected: fail because write APIs do not accept or persist `ExplanationImageChange`.

- [ ] **Step 3: Implement transactional preparation and row updates**

```python
def _prepare_explanation_image(self, change):
    if change is None or change.action == "keep":
        return None
    if change.action == "remove":
        return ""
    return self.explanation_image_store.import_file(change.source_path)


@staticmethod
def _write_explanation_image_row(cursor, question_id, prepared_path):
    if prepared_path is None:
        return
    cursor.execute(
        "DELETE FROM question_explanation_images WHERE question_id = ? AND display_order = 0",
        (question_id,),
    )
    if prepared_path:
        cursor.execute(
            "INSERT INTO question_explanation_images "
            "(question_id, image_path, display_order) VALUES (?, ?, 0)",
            (question_id, prepared_path),
        )
```

Construct `self.explanation_image_store` in `__init__`. Before each write, collect the current attachment path. Import replacements before opening the SQL transaction, apply text and attachment changes in the same transaction, and remove the newly imported file on rollback. After commit, query for remaining references and remove only unreferenced old managed paths. Extend single and bulk question deletion to collect paths before deletion and clean them only after commit.

For `create_manual_question()`, persist a replacement change after the new question ID exists. For cloning, the editor will send a replacement pointing at the resolved original image, so `import_file()` creates an independent managed file.

- [ ] **Step 4: Run lifecycle and full repository tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_repository.py tests/test_explanation_images.py -q`

Expected: all tests pass and no managed test files remain after remove/delete/failure cases.

- [ ] **Step 5: Commit transactional persistence**

```powershell
git add src/database/repository.py tests/test_repository.py
git commit -m "Persist explanation images transactionally"
```

---

### Task 4: Mounted repository attachment routing

**Files:**
- Modify: `experiments/db_mount_prototype/mount_repo.py`
- Modify: `tests/test_db_mount_prototype.py`
- Modify: `tests/test_mounted_browser.py`

**Interfaces:**
- Consumes: `ExamRepository.update_question_explanation(question_id, explanation, image_change)`.
- Extends: `MountedExamRepository(manifest_path, explanation_image_store=None)` for deterministic managed storage in tests and delegated writes.
- Produces: namespaced `explanation_images` entries from writable and legacy read-only mounts.

- [ ] **Step 1: Write failing mounted repository tests**

```python
def test_mounted_repository_reads_and_writes_explanation_image(tmp_path):
    first_db = tmp_path / "first.db"
    second_db = tmp_path / "second.db"
    _make_db(first_db, "첫 문제")
    _make_db(second_db, "둘 문제")
    manifest = tmp_path / "mounts.json"
    write_manifest(
        manifest,
        [
            MountedDatabase(id="first", label="First", path=first_db),
            MountedDatabase(id="second", label="Second", path=second_db),
        ],
    )
    store = ExplanationImageStore(tmp_path / "app")
    mounted = MountedExamRepository(manifest, explanation_image_store=store)
    source_image = _png(tmp_path / "mounted.png")
    assert mounted.update_question_explanation(
        "first::1",
        "이미지 해설",
        ExplanationImageChange.replace(source_image),
    )
    loaded = mounted.get_question("first::1")
    assert loaded["explanation_images"][0]["image_path"].startswith("data/explanation_images/")
    assert mounted.get_question("second::1")["explanation_images"] == []


def test_legacy_read_only_mount_without_attachment_table_returns_empty_list(tmp_path):
    db_path = tmp_path / "legacy.db"
    _make_db(db_path, "레거시 문제")
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TABLE question_explanation_images")
    manifest = tmp_path / "mounts.json"
    write_manifest(
        manifest,
        [MountedDatabase(id="legacy", label="Legacy", path=db_path, read_only=True)],
    )
    mounted = MountedExamRepository(manifest)

    assert mounted.get_question("legacy::1")["explanation_images"] == []
    assert mounted.get_questions_with_choices(limit=None)[0]["explanation_images"] == []
```

- [ ] **Step 2: Run mounted tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_db_mount_prototype.py tests/test_mounted_browser.py -k "explanation" -q`

Expected: fail because mounted reads do not attach rows and the write method accepts only text.

- [ ] **Step 3: Implement mounted attachment batching and forwarding**

```python
def _explanation_images_for_mount(self, mount, local_question_ids):
    result = {question_id: [] for question_id in local_question_ids}
    with self._connect(mount) as conn:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='question_explanation_images'"
        ).fetchone()
        if not exists:
            return result
        # Fetch ordered rows, namespace attachment id, and retain local_id.
    return result


def update_question_explanation(self, question_id, explanation, image_change=None):
    mount, local_id = self._write_target(question_id)
    if not self._write_repo(mount).update_question_explanation(local_id, explanation, image_change):
        raise RuntimeError(f"{mount.label} DB에서 해설을 저장하지 못했습니다.")
    return True
```

Store the optional image store in `MountedExamRepository.__init__` and pass it from `_write_repo()`:

```python
def __init__(self, manifest_path, explanation_image_store=None):
    self.manifest_path = Path(manifest_path).resolve()
    self.mounts = [mount for mount in load_manifest(self.manifest_path) if mount.enabled]
    self._mounts_by_id = {mount.id: mount for mount in self.mounts}
    self.explanation_image_store = explanation_image_store

def _write_repo(self, mount):
    repo = ExamRepository(
        str(mount.path),
        explanation_image_store=self.explanation_image_store,
    )
    repo.init_database()
    return repo
```

Attach batched image lists in both `get_question()` and `get_questions_with_choices()`. Keep an empty list for legacy read-only databases without the table. Continue using `_write_target()` so this feature preserves the existing namespaced edit-routing policy rather than changing mount permissions.

- [ ] **Step 4: Run mounted tests and verify GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_db_mount_prototype.py tests/test_mounted_browser.py -q`

Expected: all mounted repository and browser tests pass.

- [ ] **Step 5: Commit mounted support**

```powershell
git add experiments/db_mount_prototype/mount_repo.py tests/test_db_mount_prototype.py tests/test_mounted_browser.py
git commit -m "Route explanation images through mounted repositories"
```

---

### Task 5: Reusable explanation image editor widget

**Files:**
- Create: `src/gui/explanation_image_editor.py`
- Create: `tests/test_explanation_image_editor.py`

**Interfaces:**
- Consumes: `ExplanationImageStore` and `ExplanationImageChange`.
- Produces: `ExplanationImageEditor(parent=None, image_store=None)`.
- Produces: `set_attachment(attachment)`, `set_candidate(source_path)`, `image_change(force_copy=False)`, and `discard_pending()`.

- [ ] **Step 1: Write failing widget tests**

```python
def test_editor_select_paste_delete_and_change_state(tmp_path, monkeypatch):
    store = ExplanationImageStore(tmp_path / "app")
    widget = ExplanationImageEditor(image_store=store)
    source = _png(tmp_path / "selected.png")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(source), ""))

    widget.select_image()
    assert widget.preview.isHidden() is False
    assert widget.image_change().action == "replace"
    assert widget.image_change().source_path == str(source)

    widget.remove_image()
    assert widget.image_change().action == "remove"
    assert widget.preview.isHidden() is True


def test_editor_keeps_candidate_when_clipboard_is_empty(tmp_path, monkeypatch):
    store = ExplanationImageStore(tmp_path / "app")
    widget = ExplanationImageEditor(image_store=store)
    source = _png(tmp_path / "selected.png")
    widget.set_candidate(str(source))
    monkeypatch.setattr(widget, "_clipboard_image", lambda: QImage())

    widget.paste_image()

    assert widget.image_change() == ExplanationImageChange.replace(str(source))
    assert widget.statusLabel.text() == "클립보드에 이미지가 없습니다."


def test_editor_force_copy_for_clone_resolves_saved_attachment(tmp_path):
    store = ExplanationImageStore(tmp_path / "app")
    source = _png(tmp_path / "saved.png")
    stored = store.import_file(source)
    widget = ExplanationImageEditor(image_store=store)
    widget.set_attachment({"image_path": stored, "display_order": 0})

    change = widget.image_change(force_copy=True)

    assert change.action == "replace"
    assert Path(change.source_path).is_file()
```

- [ ] **Step 2: Run widget tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_explanation_image_editor.py -q`

Expected: collection fails because the reusable widget does not exist.

- [ ] **Step 3: Implement the widget**

```python
class ExplanationImageEditor(QWidget):
    def __init__(self, parent=None, image_store=None):
        super().__init__(parent)
        self.store = image_store or ExplanationImageStore()
        self._attachment = None
        self._candidate_path = None
        self._candidate_is_temporary = False
        self._action = "keep"
        self.preview = ImageLabel(self)
        self.statusLabel = BodyLabel("이미지 없음", self)
        self.selectButton = PushButton("이미지 선택", self)
        self.pasteButton = PushButton("붙여넣기", self)
        self.removeButton = PushButton("삭제", self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.statusLabel)
        buttons = QHBoxLayout()
        buttons.addWidget(self.selectButton)
        buttons.addWidget(self.pasteButton)
        buttons.addWidget(self.removeButton)
        layout.addLayout(buttons)
        self.selectButton.clicked.connect(self.select_image)
        self.pasteButton.clicked.connect(self.paste_image)
        self.removeButton.clicked.connect(self.remove_image)

    def image_change(self, force_copy=False):
        if force_copy and self._action == "keep" and self._attachment:
            return ExplanationImageChange.replace(
                self.store.resolve(self._attachment["image_path"])
            )
        if self._action == "replace":
            return ExplanationImageChange.replace(self._candidate_path)
        if self._action == "remove":
            return ExplanationImageChange.remove()
        return ExplanationImageChange.keep()
```

`select_image()` validates without copying, `paste_image()` stages a PNG candidate, and `remove_image()` hides the preview. `set_attachment()` first discards only temporary candidates, then loads the first saved row. Missing or corrupt saved paths show `이미지 파일 없음` or `이미지를 읽을 수 없음` without raising. Scale the preview to a 300×180 bounding box while preserving aspect ratio.

- [ ] **Step 4: Run widget tests and verify GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_explanation_image_editor.py -q`

Expected: all widget tests pass.

- [ ] **Step 5: Commit the widget**

```powershell
git add src/gui/explanation_image_editor.py tests/test_explanation_image_editor.py
git commit -m "Add reusable explanation image editor"
```

---

### Task 6: Problem management and question editor integration

**Files:**
- Modify: `src/gui/interface/browser.py`
- Modify: `src/gui/interface/editor.py`
- Modify: `tests/test_explanation_workflow.py`
- Modify: `tests/test_editor_layout.py`

**Interfaces:**
- Consumes: `ExplanationImageEditor.image_change()` and Repository image-aware writes.
- Produces: `QuestionEditor.get_data()["explanation_image_change"]`.

- [ ] **Step 1: Write failing integration tests**

```python
def test_browser_sidecar_saves_and_reloads_explanation_image(
    repo, sample_metadata, sample_question, tmp_path
):
    repo.save_questions([sample_question], sample_metadata)
    question = repo.get_questions_with_choices(limit=1)[0]
    source_image = _png(tmp_path / "explanation.png")
    widget = BrowserInterface(repository=repo)
    widget.open_explanation(question["id"])
    widget.explanationImageEditor.set_candidate(str(source_image))
    widget.explanationEditor.setPlainText("그림 해설")
    widget.save_current_explanation()

    saved = repo.get_question(question["id"])
    assert saved["explanation"] == "그림 해설"
    assert len(saved["explanation_images"]) == 1
    assert widget.explanationImageEditor.image_change().action == "keep"


def test_question_editor_returns_explanation_image_change_for_update_and_clone(tmp_path):
    source_image = _png(tmp_path / "explanation.png")
    editor = QuestionEditor(
        parent=None,
        question_data=_question_editor_data(),
        subject_options=[{"code": "engine1", "name_ko": "기관1"}],
    )
    editor.explanationImageEditor.set_candidate(str(source_image))
    assert editor.get_data()["explanation_image_change"].action == "replace"
```

Add `test_browser_failed_save_retains_explanation_image_candidate` by replacing
`widget.repo.update_question_explanation` with a function that raises `RuntimeError`, invoking
`save_current_explanation()`, and asserting `image_change().action == "replace"`. Add
`test_browser_clear_explanation_only_clears_text` and assert the editor still returns `keep`
for a loaded attachment after `clearExplanationButton.click()`.

- [ ] **Step 2: Run integration tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_explanation_workflow.py tests/test_editor_layout.py -k "explanation" -q`

Expected: fail because neither screen owns an explanation image editor.

- [ ] **Step 3: Integrate the shared widget**

```python
# BrowserInterface._init_explanation_sidecar
self.explanationImageEditor = ExplanationImageEditor(self.explanationSidecar)
sideLayout.addWidget(self.explanationImageEditor)

# BrowserInterface.open_explanation
self.explanationImageEditor.set_attachment(
    (q.get("explanation_images") or [None])[0]
)

# BrowserInterface.save_current_explanation
updated = self.repo.update_question_explanation(
    self.current_explanation_question_id,
    self.explanationEditor.toPlainText(),
    self.explanationImageEditor.image_change(),
)
if updated:
    refreshed = self.repo.get_question(self.current_explanation_question_id)
    self.explanationImageEditor.set_attachment(
        (refreshed.get("explanation_images") or [None])[0]
    )
```

Construct the browser widget with `getattr(self.repo, "explanation_image_store", None)` so
custom test stores and mounted stores resolve the same relative paths. Extend `QuestionEditor.__init__`
with `explanation_image_store=None`, pass the owning repository's store from every Browser call site,
and add the same widget below the text editor. Initialize it from the first attachment. In
`get_data()`, add:

```python
"explanation_image_change": self.explanationImageEditor.image_change(
    force_copy=self.create_mode and bool(self.question_data.get("explanation_images"))
),
```

Do not change `clear_current_explanation()` beyond clearing text. Ensure repository failures leave the Browser candidate selected for retry.
Call `discard_pending()` when the browser switches repositories or opens another question, and when
the question editor is cancelled. A successful save reloads the stored attachment through
`set_attachment()`, which also discards its temporary clipboard candidate.

- [ ] **Step 4: Run editing UI tests and verify GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_explanation_workflow.py tests/test_editor_layout.py tests/test_browser_filters.py -q`

Expected: all tests pass, including the pre-existing stacked filter layout tests.

- [ ] **Step 5: Commit editing surfaces**

```powershell
git add src/gui/interface/browser.py src/gui/interface/editor.py tests/test_explanation_workflow.py tests/test_editor_layout.py
git commit -m "Edit explanation images in question screens"
```

---

### Task 7: Practice-mode read-only rendering

**Files:**
- Modify: `src/gui/interface/practice.py`
- Modify: `tests/test_explanation_workflow.py`
- Modify: `tests/test_practice_interface.py`

**Interfaces:**
- Consumes: `question["explanation_images"]` and `ExplanationImageStore.resolve()`.
- Produces: `explanationImage`, `explanationImageStatusLabel`, and image-aware `_render_explanation()`.

- [ ] **Step 1: Write failing practice tests**

```python
def test_practice_can_reveal_image_only_explanation(
    repo, sample_metadata, sample_question, tmp_path
):
    repo.save_questions([sample_question], sample_metadata)
    question = repo.get_questions_with_choices(limit=1)[0]
    source_image = _png(tmp_path / "explanation.png")
    repo.update_question_explanation(
        question["id"],
        None,
        ExplanationImageChange.replace(source_image),
    )
    widget = PracticeInterface(repository=repo)
    _select_subject(widget, "engine1", 1)
    widget.gradingModeCombo.setCurrentIndex(
        widget.gradingModeCombo.findData(GRADING_MODE_INSTANT)
    )
    widget.start_quiz()
    widget.select_answer(2)

    assert widget.explanationToggleButton.isHidden() is False
    widget.toggle_current_explanation()
    assert widget.explanationImage.isHidden() is False
    assert widget.explanationBox.isHidden() is True


def test_practice_missing_explanation_image_keeps_text_visible(
    repo, sample_metadata, sample_question, tmp_path
):
    repo.save_questions([sample_question], sample_metadata)
    question = repo.get_questions_with_choices(limit=1)[0]
    source_image = _png(tmp_path / "explanation.png")
    repo.update_question_explanation(
        question["id"],
        "파일이 없어도 보이는 해설",
        ExplanationImageChange.replace(source_image),
    )
    stored = repo.get_question(question["id"])["explanation_images"][0]["image_path"]
    repo.explanation_image_store.resolve(stored).unlink()
    widget = PracticeInterface(repository=repo)
    _select_subject(widget, "engine1", 1)
    widget.gradingModeCombo.setCurrentIndex(
        widget.gradingModeCombo.findData(GRADING_MODE_INSTANT)
    )
    widget.start_quiz()
    widget.select_answer(2)
    widget.toggle_current_explanation()

    assert widget.explanationBox.toPlainText() == "파일이 없어도 보이는 해설"
    assert widget.explanationBox.isHidden() is False
    assert widget.explanationImageStatusLabel.text() == "이미지 파일 없음"
```

- [ ] **Step 2: Run practice tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_explanation_workflow.py tests/test_practice_interface.py -k "explanation" -q`

Expected: fail because image-only explanations are hidden and no image widget exists.

- [ ] **Step 3: Add read-only explanation image rendering**

```python
self.explanationImage = ImageLabel(self)
self.explanationImage.setVisible(False)
self.explanationImageStatusLabel = BodyLabel("", self)
self.explanationImageStatusLabel.setVisible(False)
self.quizContentLayout.addWidget(self.explanationImage)
self.quizContentLayout.addWidget(self.explanationImageStatusLabel)
```

Initialize `self.explanation_image_store` from the repository when available, falling back to
`ExplanationImageStore()`. Update `_render_explanation()` to treat either non-empty text or the first
attachment as available. When expanded, show text only when present; resolve and validate the
attachment with the store, then display it inside a 420×260 bounding box with preserved aspect ratio.
For missing/corrupt files, hide the image and show the corresponding status label. Collapse hides all
three explanation content widgets.

- [ ] **Step 4: Run practice and workflow tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_explanation_workflow.py tests/test_practice_interface.py -q`

Expected: all tests pass for text-only, image-only, combined, and missing-file explanations.

- [ ] **Step 5: Commit practice rendering**

```powershell
git add src/gui/interface/practice.py tests/test_explanation_workflow.py tests/test_practice_interface.py
git commit -m "Render explanation images in practice mode"
```

---

### Task 8: Full regression and scope gate

**Files:**
- Verify only; modify failing files only when a failure is caused by this feature.

**Interfaces:**
- Consumes all outputs from Tasks 1–7.
- Produces a verified phase-1 feature with no DOCX or inline-image behavior.

- [ ] **Step 1: Run focused feature tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_explanation_images.py tests/test_explanation_image_editor.py tests/test_explanation_workflow.py tests/test_repository.py tests/test_db_mount_prototype.py tests/test_mounted_browser.py tests/test_editor_layout.py tests/test_practice_interface.py -q
```

Expected: all focused tests pass.

- [ ] **Step 2: Run the full suite**

Run: `.\.venv\Scripts\python.exe -m pytest -q`

Expected: all tests pass; the existing Pillow `Image.getdata` deprecation warnings may remain.

- [ ] **Step 3: Inspect final scope and diff**

Run:

```powershell
git diff --check
git status --short
rg -n "explanation_image|question_explanation_images" src tests
```

Expected: no whitespace errors; only phase-1 image storage, editing, and practice rendering are present. No DOCX exporter or inline HTML code is changed.

- [ ] **Step 4: Commit any final test-only corrections**

```powershell
git add tests
git commit -m "Verify explanation image workflows"
```

Skip this commit when no final corrections are required.
