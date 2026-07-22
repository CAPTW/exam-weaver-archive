from pathlib import Path

import pytest
from PyQt5.QtGui import QImage

from src.explanation_images import ExplanationImageChange, ExplanationImageStore


def _image(path: Path, image_format="PNG") -> Path:
    image = QImage(8, 6, QImage.Format.Format_RGB32)
    image.fill(0xFF336699)
    assert image.save(str(path), image_format)
    return path


def test_store_imports_valid_image_with_relative_uuid_path(tmp_path):
    source = _image(tmp_path / "source.jpg", "JPG")
    store = ExplanationImageStore(tmp_path / "app")

    stored = store.import_file(source)

    assert stored.startswith("data/explanation_images/")
    assert stored.endswith(".jpg")
    assert store.resolve(stored).is_file()
    assert store.resolve(stored).read_bytes() == source.read_bytes()


def test_store_rejects_invalid_or_unsupported_files(tmp_path):
    invalid = tmp_path / "bad.png"
    invalid.write_text("not an image", encoding="utf-8")
    unsupported = _image(tmp_path / "image.gif")
    store = ExplanationImageStore(tmp_path / "app")

    with pytest.raises(ValueError, match="읽을 수 없는 이미지"):
        store.import_file(invalid)
    with pytest.raises(ValueError, match="PNG, JPG, JPEG"):
        store.import_file(unsupported)


def test_store_only_removes_managed_files_and_discards_candidates(tmp_path):
    store = ExplanationImageStore(tmp_path / "app")
    external = _image(tmp_path / "external.png")
    candidate = store.save_clipboard_candidate(QImage(str(external)))
    managed = store.import_file(candidate)

    assert store.remove_managed(str(external)) is False
    assert external.exists()
    assert store.remove_managed(managed) is True
    assert not store.resolve(managed).exists()
    assert store.discard_candidate(candidate) is True
    assert not Path(candidate).exists()


def test_store_rejects_empty_clipboard_image(tmp_path):
    store = ExplanationImageStore(tmp_path / "app")

    with pytest.raises(ValueError, match="클립보드에 이미지가 없습니다"):
        store.save_clipboard_candidate(QImage())


def test_image_change_value_object_is_explicit():
    assert ExplanationImageChange.keep().action == "keep"
    assert ExplanationImageChange.remove().action == "remove"
    assert ExplanationImageChange.replace("source.png").source_path == "source.png"

    with pytest.raises(ValueError, match="경로가 필요"):
        ExplanationImageChange.replace("")
