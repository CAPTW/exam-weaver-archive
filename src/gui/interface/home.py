from PyQt5.QtWidgets import QWidget, QVBoxLayout
from PyQt5.QtGui import QColor
from qfluentwidgets import (
    SimpleCardWidget, TitleLabel, SubtitleLabel, 
    BodyLabel, ScrollArea
)

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

        # Welcome
        self.titleLabel = TitleLabel("기출문제 문제은행 관리자", self)
        self.vBoxLayout.addWidget(self.titleLabel)

        self.subtitleLabel = BodyLabel("시험 문제를 관리하고 모의고사 시험지를 생성할 수 있습니다.", self)
        self.vBoxLayout.addWidget(self.subtitleLabel)
        
        self.vBoxLayout.addStretch(1)
