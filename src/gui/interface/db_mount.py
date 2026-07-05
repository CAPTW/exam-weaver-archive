from __future__ import annotations

import json
from pathlib import Path

from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QMessageBox,
    QListWidget,
    QListWidgetItem,
    QInputDialog,
)
from PyQt5.QtCore import Qt
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
    rename_mount_database,
)
from experiments.db_mount_prototype.mount_repo import load_manifest


class DbMountInterface(QWidget):
    def __init__(self, base_dir, parent=None):
        super().__init__(parent)
        self.base_dir = Path(base_dir)
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

        self.titleLabel = SubtitleLabel("DB Mount 관리", self)
        self.vBoxLayout.addWidget(self.titleLabel)
        self.descriptionLabel = BodyLabel(
            "사용할 DB를 선택하고, exam 단위로 mounted DB 사이를 이동합니다. 이동은 dry-run 확인 후 저장됩니다.",
            self,
        )
        self.vBoxLayout.addWidget(self.descriptionLabel)

        self.mountList = QListWidget(self)
        self.mountList.setMinimumHeight(118)
        self.mountList.setMaximumHeight(172)
        self.mountList.setSelectionMode(QListWidget.NoSelection)
        self.mountList.itemChanged.connect(self.on_mount_selection_changed)
        self.vBoxLayout.addWidget(BodyLabel("사용할 DB", self))
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

        self.selectionLayout.addWidget(BodyLabel("Source", self))
        self.selectionLayout.addWidget(self.sourceDbCombo)
        self.selectionLayout.addWidget(BodyLabel("Target", self))
        self.selectionLayout.addWidget(self.targetDbCombo)
        self.selectionLayout.addWidget(BodyLabel("Exam", self))
        self.selectionLayout.addWidget(self.examCombo)
        self.vBoxLayout.addLayout(self.selectionLayout)

        self.actionLayout = QHBoxLayout()
        self.refreshBtn = PushButton("새로고침", self)
        self.saveMountBtn = PushButton("Mount 설정 저장", self)
        self.renameDbBtn = PushButton("Source DB 이름/파일명 변경", self)
        self.createDbBtn = PushButton("새 DB 만들기", self)
        self.copyExamBtn = PrimaryPushButton("Exam 사본 만들기", self)
        self.dryRunBtn = PrimaryPushButton("Dry-run", self)
        self.applyBtn = PrimaryPushButton("이동 저장", self)
        self.applyBtn.setEnabled(False)
        self.refreshBtn.clicked.connect(self.refresh_mounts)
        self.saveMountBtn.clicked.connect(self.save_mount_selection)
        self.renameDbBtn.clicked.connect(self.rename_current_source_mount)
        self.createDbBtn.clicked.connect(self.create_user_database_from_prompt)
        self.copyExamBtn.clicked.connect(self.copy_current_exam_to_target)
        self.dryRunBtn.clicked.connect(self.run_dry_run)
        self.applyBtn.clicked.connect(self.apply_move)
        self.actionLayout.addWidget(self.refreshBtn)
        self.actionLayout.addWidget(self.saveMountBtn)
        self.actionLayout.addWidget(self.renameDbBtn)
        self.actionLayout.addWidget(self.createDbBtn)
        self.actionLayout.addWidget(self.copyExamBtn)
        self.actionLayout.addWidget(self.dryRunBtn)
        self.actionLayout.addWidget(self.applyBtn)
        self.actionLayout.addStretch(1)
        self.vBoxLayout.addLayout(self.actionLayout)

        self.logView = QTextEdit(self)
        self.logView.setReadOnly(True)
        self.logView.setPlaceholderText("DB mount 상태와 dry-run 결과가 여기에 표시됩니다.")
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
            self.mountList.blockSignals(False)
            self.sourceDbCombo.blockSignals(False)
            self.targetDbCombo.blockSignals(False)
            self.log(
                f"Mount manifest가 없습니다: {self.manifest_path}\n"
                "먼저 data/domain_dbs/mount_manifest.json을 생성하세요."
            )
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
            self.log(f"{len(self.mounts)}개 mounted DB를 불러왔습니다. 활성: {len(self.active_mounts)}개")
        except Exception as exc:
            self.log(f"Mount manifest 로드 실패: {exc}")
            InfoBar.error(title="로드 실패", content=str(exc), parent=self)
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
            InfoBar.error(title="저장 실패", content="Mount manifest가 없습니다.", parent=self)
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
        self.log(f"Mount 설정 저장 완료. 활성: {len(self.active_mounts)}개")
        InfoBar.success(title="저장 완료", content="Mount 설정을 저장했습니다.", parent=self)

    def rename_current_source_mount(self):
        mount = self._current_source_mount()
        if not mount:
            InfoBar.error(title="선택 필요", content="이름을 바꿀 Source DB를 선택하세요.", parent=self)
            return
        label, ok = QInputDialog.getText(
            self,
            "DB 이름 변경",
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
        InfoBar.success(title="이름 변경 완료", content="DB 이름과 파일명을 함께 변경했습니다.", parent=self)

    def create_user_database_from_prompt(self):
        mount_id, ok = QInputDialog.getText(
            self,
            "새 DB 만들기",
            "DB ID",
            text="user_custom",
        )
        if not ok:
            return
        label, ok = QInputDialog.getText(
            self,
            "새 DB 만들기",
            "DB 이름",
            text=mount_id,
        )
        if not ok:
            return
        try:
            created = self._create_user_database(mount_id, label)
        except Exception as exc:
            self.log(f"새 DB 생성 실패: {exc}")
            InfoBar.error(title="생성 실패", content=str(exc), parent=self)
            return
        self.log(f"새 DB 생성 완료: {created.label} ({created.id}) -> {created.path}")
        InfoBar.success(title="생성 완료", content="새 DB를 생성하고 mount에 추가했습니다.", parent=self)

    def copy_current_exam_to_target(self):
        answer = QMessageBox.question(
            self,
            "Exam 사본 만들기",
            "현재 Source의 Exam을 Target DB에 복사합니다. Source DB는 삭제되지 않습니다. 계속할까요?",
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
            f"exam_code: {result.plan.exam_code}\n"
            f"target_exam_id: {result.target_exam_id}\n"
            f"target_backup: {result.target_backup}"
        )
        InfoBar.success(title="사본 생성 완료", content="Exam 사본을 target DB에 만들었습니다.", parent=self)
        self.refresh_mounts()

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
            self.log(f"Exam 목록 로드 실패: {exc}")

    def run_dry_run(self):
        source = self._current_source_mount()
        target = self._current_target_mount()
        exam_code = self._current_exam_code()
        if not source or not target or not exam_code:
            InfoBar.error(title="선택 필요", content="Source, target, exam을 선택하세요.", parent=self)
            return
        if source.path == target.path:
            InfoBar.error(title="선택 오류", content="Source와 target DB가 같습니다.", parent=self)
            return

        plan = dry_run_exam_move(source.path, target.path, exam_code)
        self.last_plan = plan
        self.applyBtn.setEnabled(plan.can_apply)
        self.log(self._format_plan(plan))
        if plan.can_apply:
            InfoBar.success(title="Dry-run 통과", content="저장할 수 있습니다.", parent=self)
        else:
            InfoBar.warning(title="Dry-run 차단", content="충돌/오류를 확인하세요.", parent=self)

    def apply_move(self):
        if not self.last_plan or not self.last_plan.can_apply:
            self.run_dry_run()
            if not self.last_plan or not self.last_plan.can_apply:
                return

        answer = QMessageBox.question(
            self,
            "Exam 이동 저장",
            (
                f"{self.last_plan.exam_code}\n\n"
                "Source DB에서 target DB로 exam 전체를 이동합니다.\n"
                "저장 전 source/target 백업이 생성됩니다. 계속할까요?"
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
            f"target_exam_id: {result.target_exam_id}\n"
            f"source_backup: {result.source_backup}\n"
            f"target_backup: {result.target_backup}"
        )
        InfoBar.success(title="이동 완료", content="exam 이동이 저장되었습니다.", parent=self)
        self.refresh_mounts()

    def _reset_plan(self):
        self.last_plan = None
        if hasattr(self, "applyBtn"):
            self.applyBtn.setEnabled(False)

    def _rename_mount(self, mount_id: str, label: str):
        rename_mount_database(self.manifest_path, mount_id, label)
        self.refresh_mounts()

    def _create_user_database(self, mount_id: str, label: str):
        created = create_empty_mount_database(
            self.manifest_path,
            mount_id=mount_id,
            label=label,
        )
        self.refresh_mounts()
        return created

    def _copy_current_exam_to_target(self, backup: bool = True):
        source = self._current_source_mount()
        target = self._current_target_mount()
        exam_code = self._current_exam_code()
        if not source or not target or not exam_code:
            raise ValueError("Source, target, exam을 선택하세요.")
        if source.id == target.id:
            raise ValueError("Source와 target DB가 같습니다.")
        return copy_exam_to_mount(
            self.manifest_path,
            source_mount_id=source.id,
            target_mount_id=target.id,
            exam_code=exam_code,
            backup=backup,
        )

    def _rebuild_active_mounts(self):
        self.active_mounts = [
            mount
            for index, mount in enumerate(self.mounts)
            if self.mountList.item(index) and self.mountList.item(index).checkState() == Qt.Checked
        ]

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
        suffix = "read-only" if mount.read_only else "writable"
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
            "exam_code": plan.exam_code,
            "can_apply": plan.can_apply,
            "source_db": plan.source_db,
            "target_db": plan.target_db,
            "counts": plan.counts,
            "issues": [
                {"code": issue.code, "message": issue.message, "severity": issue.severity}
                for issue in plan.issues
            ],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def log(self, message):
        self.logView.append(str(message))
