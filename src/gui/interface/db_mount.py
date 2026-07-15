from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QMessageBox,
    QFileDialog,
    QListWidget,
    QListWidgetItem,
    QInputDialog,
)
from PyQt5.QtCore import Qt, pyqtSignal
from qfluentwidgets import (
    BodyLabel,
    ComboBox,
    InfoBar,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
)

from experiments.db_mount_prototype.exam_move import (
    ExamMoveConflict,
    ExamMovePlan,
    apply_exam_move,
    dry_run_exam_move,
)
from experiments.db_mount_prototype.db_management import (
    copy_exam_to_mount,
    create_empty_mount_database,
    export_database_package,
    export_mount_database,
    export_mount_database_package,
    export_sqlite_database,
    import_database_to_mount,
    rename_mount_database,
)
from experiments.db_mount_prototype.mount_repo import MountedDatabase, load_manifest


class DbMountInterface(QWidget):
    mountsChanged = pyqtSignal()

    def __init__(self, base_dir, parent=None, db_path=None):
        super().__init__(parent)
        self.base_dir = Path(base_dir)
        self.db_path = Path(db_path).resolve() if db_path else self.base_dir / "data" / "exam_bank.db"
        self.manifest_path = self.base_dir / "data" / "domain_dbs" / "mount_manifest.json"
        self.mounts = []
        self.active_mounts = []
        self.exam_rows = []
        self.last_plan: ExamMovePlan | None = None
        self.setObjectName("DbMountInterface")

        self.vBoxLayout = QVBoxLayout(self)
        self.init_ui()
        self.refresh_mounts()

    def init_ui(self):
        self.vBoxLayout.setContentsMargins(30, 30, 30, 30)
        self.vBoxLayout.setSpacing(16)

        self.titleLabel = SubtitleLabel("문제은행 연결 관리", self)
        self.vBoxLayout.addWidget(self.titleLabel)
        self.descriptionLabel = BodyLabel(
            "사용할 문제은행을 선택하고 시험 단위 복사·이동과 파일 내보내기·가져오기를 관리합니다.",
            self,
        )
        self.vBoxLayout.addWidget(self.descriptionLabel)
        self.connectionStatusLabel = BodyLabel(
            "연결된 문제은행 0개 · 쓰기 가능 0개",
            self,
        )
        self.vBoxLayout.addWidget(self.connectionStatusLabel)

        self.mountList = QListWidget(self)
        self.mountList.setMinimumHeight(118)
        self.mountList.setMaximumHeight(172)
        self.mountList.setSelectionMode(QListWidget.NoSelection)
        self.mountList.itemChanged.connect(self.on_mount_selection_changed)
        self.vBoxLayout.addWidget(BodyLabel("사용할 문제은행", self))
        self.vBoxLayout.addWidget(self.mountList)

        self.selectionLayout = QHBoxLayout()
        self.sourceDbCombo = ComboBox(self)
        self.targetDbCombo = ComboBox(self)
        self.examCombo = ComboBox(self)
        self.sourceDbCombo.setMinimumWidth(280)
        self.targetDbCombo.setMinimumWidth(280)
        self.examCombo.setMinimumWidth(420)

        self.sourceDbCombo.currentIndexChanged.connect(self.on_source_changed)
        self.targetDbCombo.currentIndexChanged.connect(self._reset_plan)
        self.examCombo.currentIndexChanged.connect(self._reset_plan)

        self.sourceLabel = BodyLabel("원본 문제은행", self)
        self.selectionLayout.addWidget(self.sourceLabel)
        self.selectionLayout.addWidget(self.sourceDbCombo)
        self.targetLabel = BodyLabel("대상 문제은행", self)
        self.selectionLayout.addWidget(self.targetLabel)
        self.selectionLayout.addWidget(self.targetDbCombo)
        self.examLabel = BodyLabel("시험 종류", self)
        self.selectionLayout.addWidget(self.examLabel)
        self.selectionLayout.addWidget(self.examCombo)
        self.vBoxLayout.addLayout(self.selectionLayout)

        self.actionLayout = QHBoxLayout()
        self.refreshBtn = PushButton("새로고침", self)
        self.saveMountBtn = PushButton("연결 설정 저장", self)
        self.renameDbBtn = PushButton("원본 문제은행 이름 변경", self)
        self.createDbBtn = PushButton("새 문제은행 만들기", self)
        self.exportDbBtn = PushButton("원본 문제은행 내보내기", self)
        self.importDbBtn = PushButton("문제은행 가져오기", self)
        self.copyExamBtn = PrimaryPushButton("시험 사본 만들기", self)
        self.dryRunBtn = PrimaryPushButton("연결 사전 검사", self)
        self.applyBtn = PrimaryPushButton("이동 저장", self)
        self.applyBtn.setEnabled(False)
        self.refreshBtn.clicked.connect(self.refresh_mounts)
        self.saveMountBtn.clicked.connect(self.save_mount_selection)
        self.renameDbBtn.clicked.connect(self.rename_current_source_mount)
        self.createDbBtn.clicked.connect(self.create_user_database_from_prompt)
        self.exportDbBtn.clicked.connect(self.export_current_source_database)
        self.importDbBtn.clicked.connect(self.import_database_from_file)
        self.copyExamBtn.clicked.connect(self.copy_current_exam_to_target)
        self.dryRunBtn.clicked.connect(self.run_dry_run)
        self.applyBtn.clicked.connect(self.apply_move)
        self.actionLayout.addWidget(self.refreshBtn)
        self.actionLayout.addWidget(self.saveMountBtn)
        self.actionLayout.addWidget(self.renameDbBtn)
        self.actionLayout.addWidget(self.createDbBtn)
        self.actionLayout.addWidget(self.exportDbBtn)
        self.actionLayout.addWidget(self.importDbBtn)
        self.actionLayout.addWidget(self.copyExamBtn)
        self.actionLayout.addWidget(self.dryRunBtn)
        self.actionLayout.addWidget(self.applyBtn)
        self.actionLayout.addStretch(1)
        self.vBoxLayout.addLayout(self.actionLayout)

        self.logView = QTextEdit(self)
        self.logView.setReadOnly(True)
        self.logView.setPlaceholderText("문제은행 연결 상태와 사전 검사 결과가 여기에 표시됩니다.")
        self.vBoxLayout.addWidget(self.logView)

    def refresh_mounts(self):
        self.mounts = []
        self.active_mounts = []
        self.exam_rows = []
        self.mountList.blockSignals(True)
        self.sourceDbCombo.blockSignals(True)
        self.targetDbCombo.blockSignals(True)
        self.mountList.clear()
        self.sourceDbCombo.clear()
        self.targetDbCombo.clear()
        self.examCombo.clear()
        self.last_plan = None
        self.applyBtn.setEnabled(False)

        if not self.manifest_path.exists():
            self._load_fallback_app_database()
            return

        try:
            self.mounts = load_manifest(self.manifest_path)
            for mount in self.mounts:
                item = QListWidgetItem(self._mount_label(mount))
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if mount.enabled else Qt.Unchecked)
                self.mountList.addItem(item)
            self._rebuild_active_mounts()
            self._rebuild_source_target_combos()
            self.log(
                f"문제은행 {len(self.mounts)}개를 불러왔습니다. "
                f"현재 사용: {len(self.active_mounts)}개"
            )
        except Exception as exc:
            self.log(f"문제은행 연결 설정 로드 실패: {exc}")
            InfoBar.error(
                title="처리 실패",
                content=f"문제은행 연결 설정을 불러오지 못했습니다. {exc}",
                parent=self,
            )
        finally:
            self.mountList.blockSignals(False)
            self.sourceDbCombo.blockSignals(False)
            self.targetDbCombo.blockSignals(False)

        self.on_source_changed()

    def on_mount_selection_changed(self):
        previous_source_id = self._current_source_mount().id if self._current_source_mount() else None
        previous_target_id = self._current_target_mount().id if self._current_target_mount() else None
        self._rebuild_active_mounts()
        self._rebuild_source_target_combos(previous_source_id, previous_target_id)
        self.on_source_changed()

    def save_mount_selection(self):
        if not self.manifest_path.exists():
            InfoBar.error(
                title="처리 실패",
                content="저장할 문제은행 연결 설정 파일이 없습니다.",
                parent=self,
            )
            return

        enabled_by_id = {
            self.mounts[index].id: self.mountList.item(index).checkState() == Qt.Checked
            for index in range(self.mountList.count())
        }
        payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        for row in payload.get("mounts", []):
            mount_id = row.get("id")
            if mount_id in enabled_by_id:
                row["enabled"] = enabled_by_id[mount_id]
        self.manifest_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self.mounts = load_manifest(self.manifest_path)
        self._rebuild_active_mounts()
        self._rebuild_source_target_combos()
        self.on_source_changed()
        self.log(f"연결 설정 저장 완료. 현재 사용: {len(self.active_mounts)}개")
        self.mountsChanged.emit()
        InfoBar.success(title="저장 완료", content="문제은행 연결 설정을 저장했습니다.", parent=self)

    def rename_current_source_mount(self):
        mount = self._current_source_mount()
        if not mount:
            InfoBar.error(title="선택 필요", content="이름을 바꿀 원본 문제은행을 선택하세요.", parent=self)
            return
        label, ok = QInputDialog.getText(
            self,
            "문제은행 이름 변경",
            "새 이름",
            text=mount.label,
        )
        if not ok:
            return
        try:
            self._rename_mount(mount.id, label)
        except Exception as exc:
            self.log(f"이름 변경 실패: {exc}")
            InfoBar.error(title="이름 변경 실패", content=str(exc), parent=self)
            return
        InfoBar.success(title="이름 변경 완료", content="문제은행 이름과 파일명을 함께 변경했습니다.", parent=self)

    def create_user_database_from_prompt(self):
        mount_id, ok = QInputDialog.getText(
            self,
            "새 문제은행 만들기",
            "문제은행 ID",
            text="user_custom",
        )
        if not ok:
            return
        label, ok = QInputDialog.getText(
            self,
            "새 문제은행 만들기",
            "문제은행 이름",
            text=mount_id,
        )
        if not ok:
            return
        try:
            created = self._create_user_database(mount_id, label)
        except Exception as exc:
            self.log(f"새 문제은행 생성 실패: {exc}")
            InfoBar.error(title="생성 실패", content=str(exc), parent=self)
            return
        self.log(f"새 문제은행 생성 완료: {created.label} ({created.id}) -> {created.path}")
        InfoBar.success(title="생성 완료", content="새 문제은행을 만들고 연결 목록에 추가했습니다.", parent=self)

    def export_current_source_database(self):
        source = self._current_source_mount()
        if not source:
            InfoBar.error(title="선택 필요", content="내보낼 원본 문제은행을 선택하세요.", parent=self)
            return

        default_path = self._default_export_path(source)
        file_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "원본 문제은행 내보내기",
            str(default_path),
            "문제은행 패키지 (*.examdb.zip *.zip);;SQLite 문제은행 (*.db);;모든 파일 (*)",
        )
        if not file_path:
            return
        export_path, export_kind = self._normalize_export_path(file_path, selected_filter)

        try:
            if export_kind == "db":
                exported = self._export_current_source_db(export_path)
                copied_images = 0
                missing_images = []
            else:
                result = self._export_current_source_package(export_path)
                exported = result.path
                copied_images = result.copied_images
                missing_images = result.missing_images
        except Exception as exc:
            self.log(f"문제은행 내보내기 실패: {exc}")
            InfoBar.error(title="내보내기 실패", content=str(exc), parent=self)
            return

        size_mb = exported.stat().st_size / (1024 * 1024)
        self.log(
            "문제은행 내보내기 완료\n"
            f"원본 문제은행: {source.label} ({source.id})\n"
            f"output: {exported}\n"
            f"size: {size_mb:.2f} MB\n"
            f"packaged_images: {copied_images}\n"
            f"missing_images: {len(missing_images)}"
        )
        InfoBar.success(
            title="내보내기 완료",
            content="선택한 원본 문제은행을 저장했습니다.",
            parent=self,
        )

    def import_database_from_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "문제은행 가져오기",
            str(self.base_dir / "data" / "exports"),
            "문제은행 패키지 또는 SQLite (*.examdb.zip *.zip *.db);;모든 파일 (*)",
        )
        if not file_path:
            return

        default_id = self._suggest_mount_id(file_path)
        mount_id, ok = QInputDialog.getText(
            self,
            "문제은행 가져오기",
            "연결 ID",
            text=default_id,
        )
        if not ok:
            return
        label, ok = QInputDialog.getText(
            self,
            "문제은행 가져오기",
            "문제은행 이름",
            text=Path(file_path).name,
        )
        if not ok:
            return

        try:
            result = self._import_database(file_path, mount_id, label)
        except Exception as exc:
            self.log(f"문제은행 가져오기 실패: {exc}")
            InfoBar.error(title="가져오기 실패", content=str(exc), parent=self)
            return

        self.log(
            "문제은행 가져오기 완료\n"
            f"연결 항목: {result.mount.label} ({result.mount.id})\n"
            f"db: {result.imported_db_path}\n"
            f"package: {result.package}\n"
            f"copied_images: {result.copied_images}\n"
            f"updated_image_refs: {result.updated_image_refs}"
        )
        InfoBar.success(title="가져오기 완료", content="문제은행을 연결 목록에 추가했습니다.", parent=self)

    def copy_current_exam_to_target(self):
        answer = QMessageBox.question(
            self,
            "시험 사본 만들기",
            "현재 원본 문제은행의 시험을 대상 문제은행에 복사합니다. 원본 문제은행의 시험은 유지됩니다. 계속할까요?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            result = self._copy_current_exam_to_target(backup=True)
        except Exception as exc:
            self.log(f"사본 생성 실패: {exc}")
            InfoBar.error(title="사본 생성 실패", content=str(exc), parent=self)
            return
        self.log(
            "사본 생성 완료\n"
            f"시험 코드: {result.plan.exam_code}\n"
            f"대상 시험 ID: {result.target_exam_id}\n"
            f"대상 백업: {result.target_backup}"
        )
        InfoBar.success(title="사본 생성 완료", content="시험 사본을 대상 문제은행에 만들었습니다.", parent=self)
        self.refresh_mounts()
        self.mountsChanged.emit()

    def on_source_changed(self):
        self.examCombo.clear()
        self.exam_rows = []
        self._reset_plan()
        mount = self._current_source_mount()
        if not mount:
            return
        try:
            self.exam_rows = self._exam_rows(mount.path)
            for exam in self.exam_rows:
                self.examCombo.addItem(
                    f"{exam['name']} ({exam['code']}) - {exam['question_count']}문항",
                )
        except Exception as exc:
            self.log(f"시험 목록 로드 실패: {exc}")

    def run_dry_run(self):
        source = self._current_source_mount()
        target = self._current_target_mount()
        exam_code = self._current_exam_code()
        if not source or not target or not exam_code:
            InfoBar.error(title="선택 필요", content="원본 문제은행, 대상 문제은행, 시험 종류를 선택하세요.", parent=self)
            return
        if source.path == target.path:
            InfoBar.error(title="선택 오류", content="원본 문제은행과 대상 문제은행이 같습니다.", parent=self)
            return

        plan = dry_run_exam_move(source.path, target.path, exam_code)
        self.last_plan = plan
        self.applyBtn.setEnabled(plan.can_apply)
        self.log(self._format_plan(plan))
        if plan.can_apply:
            InfoBar.success(title="사전 검사 통과", content="시험을 안전하게 이동할 수 있습니다.", parent=self)
        else:
            InfoBar.warning(title="사전 검사 확인 필요", content="표시된 충돌이나 오류를 확인해 주세요.", parent=self)

    def apply_move(self):
        if not self.last_plan or not self.last_plan.can_apply:
            self.run_dry_run()
            if not self.last_plan or not self.last_plan.can_apply:
                return

        answer = QMessageBox.question(
            self,
            "시험 이동 저장",
            (
                f"{self.last_plan.exam_code}\n\n"
                "원본 문제은행에서 대상 문제은행으로 시험 전체를 이동합니다.\n"
                "저장 전에 양쪽 문제은행의 백업을 만듭니다. 계속할까요?"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        try:
            result = apply_exam_move(
                self.last_plan.source_db,
                self.last_plan.target_db,
                self.last_plan.exam_code,
                backup=True,
            )
        except ExamMoveConflict as exc:
            self.log(f"이동 차단: {exc}")
            InfoBar.error(title="이동 차단", content=str(exc), parent=self)
            return
        except Exception as exc:
            self.log(f"이동 실패: {exc}")
            InfoBar.error(title="이동 실패", content=str(exc), parent=self)
            return

        self.log(
            "이동 완료\n"
            f"대상 시험 ID: {result.target_exam_id}\n"
            f"원본 백업: {result.source_backup}\n"
            f"대상 백업: {result.target_backup}"
        )
        InfoBar.success(title="이동 완료", content="시험 이동을 저장했습니다.", parent=self)
        self.refresh_mounts()
        self.mountsChanged.emit()

    def _reset_plan(self):
        self.last_plan = None
        if hasattr(self, "applyBtn"):
            self.applyBtn.setEnabled(False)

    def _rename_mount(self, mount_id: str, label: str):
        rename_mount_database(self.manifest_path, mount_id, label)
        self.refresh_mounts()
        self.mountsChanged.emit()

    def _create_user_database(self, mount_id: str, label: str):
        created = create_empty_mount_database(
            self.manifest_path,
            mount_id=mount_id,
            label=label,
        )
        self.refresh_mounts()
        self.mountsChanged.emit()
        return created

    def _copy_current_exam_to_target(self, backup: bool = True):
        source = self._current_source_mount()
        target = self._current_target_mount()
        exam_code = self._current_exam_code()
        if not source or not target or not exam_code:
            raise ValueError("원본 문제은행, 대상 문제은행, 시험 종류를 선택하세요.")
        if source.id == target.id:
            raise ValueError("원본 문제은행과 대상 문제은행이 같습니다.")
        return copy_exam_to_mount(
            self.manifest_path,
            source_mount_id=source.id,
            target_mount_id=target.id,
            exam_code=exam_code,
            backup=backup,
        )

    def _export_current_source_db(self, output_path):
        source = self._current_source_mount()
        if not source:
            raise ValueError("내보낼 원본 문제은행을 선택하세요.")
        if self.manifest_path.exists():
            return export_mount_database(
                self.manifest_path,
                mount_id=source.id,
                output_path=output_path,
            )
        return export_sqlite_database(source.path, output_path)

    def _export_current_source_package(self, output_path):
        source = self._current_source_mount()
        if not source:
            raise ValueError("내보낼 원본 문제은행을 선택하세요.")
        if self.manifest_path.exists():
            return export_mount_database_package(
                self.manifest_path,
                mount_id=source.id,
                package_path=output_path,
                repo_root=self.base_dir,
            )
        return export_database_package(
            source.path,
            output_path,
            repo_root=self.base_dir,
        )

    def _import_database(self, import_path, mount_id: str, label: str):
        result = import_database_to_mount(
            self.manifest_path,
            import_path,
            mount_id=mount_id,
            label=label,
            base_dir=self.base_dir,
        )
        self.refresh_mounts()
        self.mountsChanged.emit()
        return result

    def _default_export_path(self, mount):
        export_dir = self.base_dir / "data" / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        safe_label = re.sub(r"\s+", "_", str(mount.label or mount.id).strip())
        safe_label = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", safe_label)
        safe_label = re.sub(r"_+", "_", safe_label).strip(" ._") or "database"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return export_dir / f"exam_bank.{safe_label}.{timestamp}.examdb.zip"

    def _normalize_export_path(self, file_path: str, selected_filter: str):
        path = Path(file_path)
        if not path.suffix:
            if "SQLite" in selected_filter:
                return Path(f"{file_path}.db"), "db"
            return Path(f"{file_path}.examdb.zip"), "package"
        if path.suffix.lower() == ".db":
            return path, "db"
        return path, "package"

    def _suggest_mount_id(self, file_path: str):
        name = Path(file_path).name
        lowered = name.lower()
        if lowered.endswith(".examdb.zip"):
            name = name[:-11]
        else:
            name = Path(name).stem
        value = re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", name).strip("_").lower()
        return value or "imported_db"

    def _load_fallback_app_database(self):
        if not self.db_path.exists():
            self.mountList.blockSignals(False)
            self.sourceDbCombo.blockSignals(False)
            self.targetDbCombo.blockSignals(False)
            self.log(
                f"문제은행 연결 설정 파일이 없습니다: {self.manifest_path}\n"
                "먼저 문제은행 연결 설정을 생성해 주세요."
            )
            return

        fallback = MountedDatabase(
            id="app",
            label="현재 앱 문제은행",
            domain="app",
            path=self.db_path,
            enabled=True,
            read_only=False,
        )
        self.mounts = [fallback]
        item = QListWidgetItem(self._mount_label(fallback))
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked)
        self.mountList.addItem(item)
        self._rebuild_active_mounts()
        self._rebuild_source_target_combos()
        self.mountList.blockSignals(False)
        self.sourceDbCombo.blockSignals(False)
        self.targetDbCombo.blockSignals(False)
        self.log(
            f"문제은행 연결 설정 파일이 없습니다: {self.manifest_path}\n"
            "현재 앱 문제은행을 원본으로 불러왔습니다. 문제은행 내보내기는 사용할 수 있습니다."
        )
        self.on_source_changed()

    def _rebuild_active_mounts(self):
        self.active_mounts = [
            mount
            for index, mount in enumerate(self.mounts)
            if self.mountList.item(index) and self.mountList.item(index).checkState() == Qt.Checked
        ]
        self._update_connection_status()

    def _update_connection_status(self):
        active = len(self.active_mounts)
        writable = sum(not mount.read_only for mount in self.active_mounts)
        self.connectionStatusLabel.setText(
            f"연결된 문제은행 {active}개 · 쓰기 가능 {writable}개"
        )

    def _rebuild_source_target_combos(self, source_id=None, target_id=None):
        self.sourceDbCombo.blockSignals(True)
        self.targetDbCombo.blockSignals(True)
        self.sourceDbCombo.clear()
        self.targetDbCombo.clear()
        for mount in self.active_mounts:
            self.sourceDbCombo.addItem(self._mount_label(mount))
            self.targetDbCombo.addItem(self._mount_label(mount))

        self._set_combo_to_mount_id(self.sourceDbCombo, source_id)
        self._set_combo_to_mount_id(self.targetDbCombo, target_id)
        if self.targetDbCombo.count() > 1 and self.targetDbCombo.currentIndex() == self.sourceDbCombo.currentIndex():
            self.targetDbCombo.setCurrentIndex(1 if self.sourceDbCombo.currentIndex() == 0 else 0)
        self.sourceDbCombo.blockSignals(False)
        self.targetDbCombo.blockSignals(False)

    def _set_combo_to_mount_id(self, combo, mount_id):
        if not mount_id:
            if combo.count() > 0:
                combo.setCurrentIndex(0)
            return
        for index, mount in enumerate(self.active_mounts):
            if mount.id == mount_id:
                combo.setCurrentIndex(index)
                return
        if combo.count() > 0:
            combo.setCurrentIndex(0)

    def _current_source_mount(self):
        return self._mount_at_combo_index(self.sourceDbCombo.currentIndex())

    def _current_target_mount(self):
        return self._mount_at_combo_index(self.targetDbCombo.currentIndex())

    def _mount_at_combo_index(self, index):
        if index < 0 or index >= len(self.active_mounts):
            return None
        return self.active_mounts[index]

    def _current_exam_code(self):
        index = self.examCombo.currentIndex()
        if index < 0 or index >= len(self.exam_rows):
            return None
        return self.exam_rows[index]["code"]

    def _mount_label(self, mount):
        suffix = "읽기 전용" if mount.read_only else "쓰기 가능"
        return f"{mount.label} ({mount.id}, {suffix})"

    def _mount_by_id(self, mount_id):
        for mount in self.mounts:
            if mount.id == mount_id:
                return mount
        return None

    def _exam_rows(self, db_path: Path):
        import sqlite3

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            return [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT e.code, e.name, COUNT(q.id) AS question_count
                    FROM exams e
                    JOIN exam_subjects es ON es.exam_id = e.id
                    JOIN questions q ON q.exam_subject_id = es.id
                    GROUP BY e.id, e.code, e.name
                    HAVING COUNT(q.id) > 0
                    ORDER BY e.name, e.code
                    """
                ).fetchall()
            ]

    def _format_plan(self, plan: ExamMovePlan) -> str:
        payload = {
            "시험 코드": plan.exam_code,
            "적용 가능": plan.can_apply,
            "원본 문제은행": plan.source_db,
            "대상 문제은행": plan.target_db,
            "항목 수": plan.counts,
            "확인 항목": [
                {"코드": issue.code, "메시지": issue.message, "수준": issue.severity}
                for issue in plan.issues
            ],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def log(self, message):
        self.logView.append(str(message))
