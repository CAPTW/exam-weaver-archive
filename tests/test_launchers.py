from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_latest_app_launcher_runs_source_gui_with_venv_pythonw():
    launcher = ROOT / "Run_Latest_App.bat"

    content = launcher.read_text(encoding="utf-8")

    assert ".venv\\Scripts\\pythonw.exe" in content
    assert "-m src.gui.main" in content
    assert "start \"\" \"%PYTHONW%\" -m src.gui.main" in content


def test_silent_launcher_uses_pythonw_without_hiding_gui_window():
    launcher = ROOT / "Run_Latest_App_Silent.vbs"

    content = launcher.read_text(encoding="utf-8")

    assert ".venv\\Scripts\\pythonw.exe" in content
    assert "-m src.gui.main" in content
    assert "shell.Run" in content
    assert ", 1, False" in content


def test_packaged_app_launcher_tests_builds_and_runs_dist_exe():
    launcher = ROOT / "Build_And_Run_Packaged_App.bat"

    content = launcher.read_text(encoding="utf-8")

    assert ".venv\\Scripts\\python.exe" in content
    assert "-m pytest -q" in content
    assert "%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" in content
    assert "scripts\\build_exe.ps1" in content
    assert "-NoZip" in content
    assert "dist\\ExamGenerator\\ExamGenerator.exe" in content
    assert "start \"\" \"%PACKAGED_EXE%\"" in content


def test_github_portable_launcher_builds_no_db_zip():
    launcher = ROOT / "Build_GitHub_Portable_App.bat"

    content = launcher.read_text(encoding="utf-8")

    assert ".venv\\Scripts\\python.exe" in content
    assert "scripts\\build_exe.ps1" in content
    assert "-GithubPortable" in content
    assert "-IsolatedDist" in content
    assert "without a question DB" in content


def test_pyinstaller_spec_declares_app_icon_asset():
    spec = ROOT / "ExamGenerator.spec"

    content = spec.read_text(encoding="utf-8")

    assert r"assets\\icons\\exam_generator_icon.ico" in content
    assert r"icon='assets\\icons\\exam_generator_icon.ico'" in content


def test_run_readme_explains_both_non_programmer_paths():
    readme = ROOT / "README_APP_RUN.txt"

    content = readme.read_text(encoding="utf-8")

    assert "Run_Latest_App.bat" in content
    assert "Build_And_Run_Packaged_App.bat" in content
    assert "Portable ZIP" in content
    assert "최신 코드" in content
    assert "패키징" in content
