from pathlib import Path

from src.runtime_paths import (
    FACTORY_DB_NAME,
    USER_DB_NAME,
    ensure_user_database,
    get_clipboard_image_dir,
    get_factory_db_path,
    get_user_db_path,
)


def test_ensure_user_database_copies_factory_db_once(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    factory_db = data_dir / FACTORY_DB_NAME
    factory_db.write_bytes(b"factory")

    user_db = ensure_user_database(tmp_path)

    assert user_db == data_dir / USER_DB_NAME
    assert user_db.read_bytes() == b"factory"

    user_db.write_bytes(b"user edits")
    ensure_user_database(tmp_path)

    assert user_db.read_bytes() == b"user edits"


def test_runtime_paths_resolve_external_data_folder(tmp_path):
    assert get_factory_db_path(tmp_path) == tmp_path / "data" / FACTORY_DB_NAME
    assert get_user_db_path(tmp_path) == tmp_path / "data" / USER_DB_NAME
    assert get_clipboard_image_dir(tmp_path) == tmp_path / "data" / "clipboard_images"
