"""功能頁基底:標題列 + 可捲動內容區。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from ..api import error_message
from ..widgets.common import toast

if TYPE_CHECKING:
    from .main_window import MainWindow


class Page(QWidget):
    title = ""
    subtitle = ""
    scrollable = True

    def __init__(self, main: MainWindow):
        super().__init__()
        self.main = main
        self.setObjectName("Page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        container = QWidget()
        container.setObjectName("PageBody")
        self.layout_ = QVBoxLayout(container)
        self.layout_.setContentsMargins(20, 16, 20, 28)
        self.layout_.setSpacing(16)

        head = QHBoxLayout()
        head.setSpacing(10)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.title_label = QLabel(self.title)
        self.title_label.setObjectName("PageTitle")
        self.sub_label = QLabel(self.subtitle)
        self.sub_label.setObjectName("PageSub")
        self.sub_label.setWordWrap(True)
        titles.addWidget(self.title_label)
        titles.addWidget(self.sub_label)
        head.addLayout(titles, 1)
        self.head_actions = QHBoxLayout()
        self.head_actions.setSpacing(8)
        head.addLayout(self.head_actions)
        self.layout_.addLayout(head)

        if self.scrollable:
            scroll = QScrollArea()
            scroll.setObjectName("PageScroll")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setWidget(container)
            outer.addWidget(scroll)
        else:
            outer.addWidget(container)

    # ------------------------------------------------------------------ 子類別使用

    def add(self, item, stretch: int = 0) -> None:
        if isinstance(item, QWidget):
            self.layout_.addWidget(item, stretch)
        else:
            self.layout_.addLayout(item, stretch)

    def add_head_action(self, widget: QWidget) -> QWidget:
        self.head_actions.addWidget(widget)
        return widget

    def fail(self, fallback: str):
        """產生 on_err callback:以 toast 顯示錯誤。"""
        return lambda exc: toast(error_message(exc, fallback), "error")

    # ------------------------------------------------------------------ 生命週期

    def on_show(self) -> None:
        """每次切換到此頁時呼叫 (等同原版每次重新掛載頁面)。"""

    def on_hide(self) -> None:
        """離開此頁時呼叫 (停止計時器、串流等)。"""
