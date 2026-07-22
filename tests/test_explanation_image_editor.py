import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import QApplication, QFileDialog

from src.explanation_images import ExplanationImageChange, ExplanationImageStore
from src.gui.explanation_image_editor import ExplanationImageEditor


APP = QApplication.instance() or QApplication([])


def _image(path: Path) -> str:
    image = QImage(80, 40, QImage.Format.Format_RGB32)
    image.fill(0xFF4488AA)
    assert image.save(str(path), "PNG")
    return str(path)


def test_editor_selects_and_removes_image(tmp_path, monkeypatch):
    store = ExplanationImageStore(tmp_path / "app")
    widget = ExplanationImageEditor(image_store=store)
    source = _image(tmp_path / "selected.png")
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (source, ""),
    )

    widget.select_image()

    assert widget.preview.isHidden() is False
    assert widget.image_change() == ExplanationImageChange.replace(source)

    widget.remove_image()

    assert widget.image_change() == ExplanationImageChange.remove()
    assert widget.preview.isHidden() is True
    widget.deleteLater()
    APP.processEvents()


def test_editor_pastes_temporary_candidate_and_discards_it(tmp_path, monkeypatch):
    store = ExplanationImageStore(tmp_path / "app")
    widget = ExplanationImageEditor(image_store=store)
    clipboard_image = QImage(30, 20, QImage.Format.Format_RGB32)
    clipboard_image.fill(0xFFAA6633)
    monkeypatch.setattr(widget, "_clipboard_image", lambda: clipboard_image)

    widget.paste_image()
    candidate = Path(widget.image_change().source_path)

    assert candidate.is_file()
    assert candidate.parent == store.candidate_dir
    assert widget.preview.isHidden() is False

    widget.discard_pending()

    assert not candidate.exists()
    assert widget.image_change() == ExplanationImageChange.keep()
    widget.deleteLater()
    APP.processEvents()


def test_editor_keeps_candidate_when_clipboard_is_empty(tmp_path, monkeypatch):
    store = ExplanationImageStore(tmp_path / "app")
    widget = ExplanationImageEditor(image_store=store)
    source = _image(tmp_path / "selected.png")
    widget.set_candidate(source)
    monkeypatch.setattr(widget, "_clipboard_image", lambda: QImage())

    widget.paste_image()

    assert widget.image_change() == ExplanationImageChange.replace(source)
    assert widget.statusLabel.text() == "클립보드에 이미지가 없습니다."
    widget.deleteLater()
    APP.processEvents()


def test_editor_force_copy_for_clone_resolves_saved_attachment(tmp_path):
    store = ExplanationImageStore(tmp_path / "app")
    source = _image(tmp_path / "saved.png")
    stored = store.import_file(source)
    widget = ExplanationImageEditor(image_store=store)
    widget.set_attachment({"image_path": stored, "display_order": 0})

    change = widget.image_change(force_copy=True)

    assert change.action == "replace"
    assert Path(change.source_path).is_file()
    assert widget.preview.isHidden() is False
    widget.deleteLater()
    APP.processEvents()


def test_editor_reports_missing_or_corrupt_saved_image(tmp_path):
    store = ExplanationImageStore(tmp_path / "app")
    widget = ExplanationImageEditor(image_store=store)

    widget.set_attachment({"image_path": "data/explanation_images/missing.png"})
    assert widget.statusLabel.text() == "이미지 파일 없음"
    assert widget.preview.isHidden() is True

    corrupt = store.image_dir / "corrupt.png"
    corrupt.parent.mkdir(parents=True, exist_ok=True)
    corrupt.write_text("not image", encoding="utf-8")
    widget.set_attachment(
        {"image_path": corrupt.relative_to(store.base_dir).as_posix()}
    )
    assert widget.statusLabel.text() == "이미지를 읽을 수 없음"
    assert widget.preview.isHidden() is True
    widget.deleteLater()
    APP.processEvents()
