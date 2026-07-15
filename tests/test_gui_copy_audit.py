from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_pyinstaller_bundles_builtin_menu_language_packs():
    spec = (PROJECT_ROOT / "ExamGenerator.spec").read_text(encoding="utf-8")

    assert r"assets\\language_packs\\menu\\*.json" in spec


def test_gui_source_has_no_disallowed_visible_legacy_copy():
    interface_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((PROJECT_ROOT / "src" / "gui" / "interface").glob("*.py"))
    )
    main_source = (PROJECT_ROOT / "src" / "gui" / "main.py").read_text(
        encoding="utf-8"
    )
    visible_source = interface_source + "\n" + main_source

    disallowed = (
        'BodyLabel("EXAM"',
        'BodyLabel("SUBJECT"',
        'SubtitleLabel("Export Exam',
        'PrimaryPushButton("Export"',
        'SubtitleLabel("DB Mount',
        'BodyLabel("Source"',
        'BodyLabel("Target"',
        'PrimaryPushButton("Dry-run"',
        'BodyLabel("Model"',
        'setPlaceholderText("태그',
        'BodyLabel("태그"',
        'text=\'DB Mount\'',
        '"DB Mount",',
    )
    for legacy in disallowed:
        assert legacy not in visible_source, legacy


def test_builtin_language_pack_assets_exist_and_are_utf8_json():
    pack_dir = PROJECT_ROOT / "assets" / "language_packs" / "menu"

    for filename in ("ko.json", "en.json"):
        payload = (pack_dir / filename).read_text(encoding="utf-8")
        assert '"strings"' in payload
        assert '"menu.settings"' in payload
