import os
import sys
import faulthandler
import traceback
from pathlib import Path

try:
    from src.runtime_paths import ensure_user_database, get_base_dir
except ModuleNotFoundError:
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
    from src.runtime_paths import ensure_user_database, get_base_dir


def _get_base_dir() -> str:
    return str(get_base_dir())


BASE_DIR = _get_base_dir()
os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)
os.chdir(BASE_DIR)
os.environ.setdefault("QT_API", "pyqt5")
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")

LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
APP_TITLE = "기출문제 문제은행 관리자"
DEFAULT_WINDOW_SIZE = (1500, 860)


def _install_crash_logging():
    log_path = os.path.join(LOG_DIR, "gui-crash.log")
    log_file = open(log_path, "a", encoding="utf-8")
    faulthandler.enable(log_file)

    def excepthook(exc_type, exc, tb):
        traceback.print_exception(exc_type, exc, tb, file=log_file)
        log_file.flush()
        traceback.print_exception(exc_type, exc, tb)

    sys.excepthook = excepthook
    return log_file

if __package__ is None or __package__ == "":
    # Allow running as a script by adding repo root to sys.path for package imports.
    sys.path.insert(0, BASE_DIR)
    __package__ = "src.gui"
from PyQt5.QtWidgets import QApplication, QHBoxLayout, QWidget
from PyQt5.QtCore import Qt, QTimer
from qfluentwidgets import (
    FluentWindow, NavigationItemPosition, NavigationAvatarWidget,
    FluentTranslator, SplashScreen, PushButton, InfoBar
)
from qfluentwidgets import FluentIcon as FIF

from .interface.home import HomeInterface
from .interface.browser import BrowserInterface
from .interface.export import ExportInterface
from .interface.practice import PracticeInterface
from .interface.import_view import ImportInterface
from .interface.db_mount import DbMountInterface
from .interface.codex_panel import CodexInterface
from ..database.repository import ExamRepository
from experiments.db_mount_prototype.mount_repo import MountedExamRepository


def build_question_repository(db_path, manifest_path):
    manifest = Path(manifest_path)
    if manifest.exists():
        try:
            repository = MountedExamRepository(manifest)
            repository.init_database()
            return repository, None
        except (OSError, ValueError) as exc:
            return ExamRepository(str(db_path)), str(exc)
    return ExamRepository(str(db_path)), None

class MainWindow(FluentWindow):
    def __init__(self):
        super().__init__()
        self._disable_frameless_screen_refresh()
        self.init_window()

        # Use the writable user DB. Packaged builds create it from seed_exam_bank.db
        # when exam_bank.db is absent.
        self.db_path = str(ensure_user_database(BASE_DIR))
        # Ensure DB schema/migrations are applied (e.g., tags column)
        ExamRepository(self.db_path).init_database()

        question_repository, self.question_repository_error = build_question_repository(
            self.db_path,
            Path(BASE_DIR) / "data" / "domain_dbs" / "mount_manifest.json",
        )

        # Interfaces
        self.home_interface = HomeInterface(self)
        self.browser_interface = BrowserInterface(self.db_path, self, repository=question_repository)
        self.practice_interface = PracticeInterface(self.db_path, self)
        self.export_interface = ExportInterface(self.db_path, self)
        self.import_interface = ImportInterface(self.db_path, self)
        self.db_mount_interface = DbMountInterface(BASE_DIR, self, db_path=self.db_path)
        self.db_mount_interface.mountsChanged.connect(self.refresh_question_repository)
        self.codex_interface = CodexInterface(BASE_DIR, self, side_panel=True)
        self.codex_sidecar_expanded = True

        # Navigation
        self.init_navigation()
        self.init_codex_sidecar()
        if self.question_repository_error:
            QTimer.singleShot(0, self._show_question_repository_error)

    def refresh_question_repository(self):
        repository, error = build_question_repository(
            self.db_path,
            self.db_mount_interface.manifest_path,
        )
        self.question_repository_error = error
        self.browser_interface.set_repository(repository)
        if error:
            self._show_question_repository_error()

    def _show_question_repository_error(self):
        if not self.question_repository_error:
            return
        InfoBar.error(
            title="Mount 로드 실패",
            content=self.question_repository_error,
            parent=self,
        )

    def init_window(self):
        self.resize(*DEFAULT_WINDOW_SIZE)
        self.setWindowTitle(APP_TITLE)
        self.move(100, 100)

    def _disable_frameless_screen_refresh(self):
        """
        qframelesswindow refreshes the native frame on screenChanged via Win32
        SetWindowPos(..., SWP_FRAMECHANGED). On some multi-monitor/DPI setups
        that native path can terminate the process while dragging windows
        between screens. The app does not rely on that refresh, so keep the
        window alive and only repaint after a screen change.
        """
        if sys.platform != "win32" or not self.windowHandle():
            return

        try:
            self.windowHandle().screenChanged.disconnect()
        except TypeError:
            pass

        self.windowHandle().screenChanged.connect(
            lambda *_: QTimer.singleShot(0, self.update)
        )

    def init_navigation(self):
        self.addSubInterface(
            self.home_interface, FIF.HOME, "홈", 
            NavigationItemPosition.TOP
        )
        self.addSubInterface(
            self.browser_interface, FIF.QUESTION, "문제 관리", 
            NavigationItemPosition.TOP
        )
        self.addSubInterface(
            self.practice_interface, FIF.PLAY, "문제 풀이",
            NavigationItemPosition.TOP
        )
        self.addSubInterface(
            self.export_interface, FIF.PRINT, "시험지 출력", 
            NavigationItemPosition.TOP
        )
        self.addSubInterface(
            self.import_interface, FIF.DOWNLOAD, "문제 가져오기", 
            NavigationItemPosition.TOP
        )
        self.addSubInterface(
            self.db_mount_interface, FIF.FOLDER, "DB Mount",
            NavigationItemPosition.TOP
        )

        self.navigationInterface.addItem(
            routeKey='CodexToggle',
            icon=FIF.ROBOT,
            text='Codex',
            position=NavigationItemPosition.BOTTOM,
            onClick=self.toggle_codex_sidecar
        )
        
        self.navigationInterface.addItem(
            routeKey='Settings',
            icon=FIF.SETTING,
            text='설정',
            position=NavigationItemPosition.BOTTOM,
            onClick=lambda: print("Settings clicked")
        )

    def init_codex_sidecar(self):
        self.codex_sidecar_container = QWidget(self)
        self.codex_sidecar_layout = QHBoxLayout(self.codex_sidecar_container)
        self.codex_sidecar_layout.setContentsMargins(0, 0, 0, 0)
        self.codex_sidecar_layout.setSpacing(4)

        self.codex_toggle_button = PushButton(">", self.codex_sidecar_container)
        self.codex_toggle_button.setFixedSize(30, 86)
        self.codex_toggle_button.setToolTip("Codex 패널 접기")
        self.codex_toggle_button.clicked.connect(self.toggle_codex_sidecar)

        self.codex_interface.collapse_requested.connect(
            lambda: self.set_codex_sidecar_expanded(False)
        )
        self.codex_sidecar_layout.addWidget(
            self.codex_toggle_button,
            0,
            Qt.AlignmentFlag.AlignTop
        )
        self.codex_sidecar_layout.addWidget(self.codex_interface)
        self.widgetLayout.addWidget(self.codex_sidecar_container)
        self.widgetLayout.setStretchFactor(self.stackedWidget, 1)
        self.widgetLayout.setStretchFactor(self.codex_sidecar_container, 0)
        self.set_codex_sidecar_expanded(True)

    def toggle_codex_sidecar(self):
        self.set_codex_sidecar_expanded(not self.codex_sidecar_expanded)

    def set_codex_sidecar_expanded(self, expanded: bool):
        self.codex_sidecar_expanded = bool(expanded)
        self.codex_interface.setVisible(self.codex_sidecar_expanded)
        self.codex_toggle_button.setText(">" if self.codex_sidecar_expanded else "<")
        self.codex_toggle_button.setToolTip(
            "Codex 패널 접기" if self.codex_sidecar_expanded else "Codex 패널 펼치기"
        )
        self.codex_sidecar_container.setMaximumWidth(
            470 if self.codex_sidecar_expanded else 34
        )

def main() -> int:
    _install_crash_logging()
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    if hasattr(Qt, "HighDpiScaleFactorRoundingPolicy"):
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )

    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
