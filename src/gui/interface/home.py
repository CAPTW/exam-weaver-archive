from PyQt5.QtWidgets import QWidget, QVBoxLayout
from qfluentwidgets import BodyLabel, ScrollArea, TitleLabel


class HomeInterface(ScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = QWidget(self)
        self.vBoxLayout = QVBoxLayout(self.view)

        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.setObjectName("HomeInterface")

        self.init_ui()

    def init_ui(self):
        self.vBoxLayout.setContentsMargins(30, 30, 30, 30)
        self.vBoxLayout.setSpacing(20)

        self.titleLabel = TitleLabel("Exam Generator", self)
        self.vBoxLayout.addWidget(self.titleLabel)

        self.subtitleLabel = BodyLabel(
            "기출문서를 문제은행으로, 문제은행을 편집 가능한 시험지로 만듭니다.",
            self,
        )
        self.vBoxLayout.addWidget(self.subtitleLabel)

        self.vBoxLayout.addStretch(1)
