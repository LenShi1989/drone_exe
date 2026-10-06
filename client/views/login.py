"""登入視窗。"""
from __future__ import annotations

import json

from PyQt5.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QLinearGradient, QPainter, QPen, QRadialGradient
from PyQt5.QtWidgets import QFrame, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from ..api import api, error_message
from ..config import data_dir, settings
from ..tasks import run_async
from ..widgets.common import button, field, hbox, label, vbox

DEMO_ACCOUNTS = [
    ("admin", "Admin@123", "系統管理員 — 全部權限"),
    ("operator", "Operator@123", "操作員 — 可派工/編輯地圖"),
    ("viewer", "Viewer@123", "檢視者 — 唯讀"),
]


class LogoMark(QWidget):
    def __init__(self, size: int = 46, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        s = self.width() / 32
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#00e5ff"))
        p.drawEllipse(c, 4.5 * s, 4.5 * s)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(0, 229, 255, 140), 1.4 * s))
        p.drawEllipse(c, 10 * s, 10 * s)
        p.setPen(QPen(QColor(0, 229, 255, 64), 1.0 * s))
        p.drawEllipse(c, 14.5 * s, 14.5 * s)


class LoginWindow(QWidget):
    loggedIn = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("無人機操作系統 — 登入")
        self.resize(980, 680)
        self._pref = data_dir() / "login.json"

        card = QFrame()
        card.setObjectName("Panel")
        card.setFixedWidth(460)

        title = QLabel("無人機操作系統")
        title.setStyleSheet("font-size:17pt;font-weight:600;letter-spacing:2px")
        sub = label("DRONE OPERATIONS CENTER", mono=True)
        sub.setStyleSheet("color:#0891a3;letter-spacing:3px;font-size:8pt")
        head = hbox(LogoMark(46), vbox(title, sub, spacing=2), "stretch", spacing=14)

        self.username = QLineEdit(self._remembered_user() or "admin")
        self.password = QLineEdit("Admin@123" if (self._remembered_user() or "admin") == "admin" else "")
        self.password.setEchoMode(QLineEdit.Password)
        self.password.returnPressed.connect(self.submit)
        self.username.returnPressed.connect(self.password.setFocus)
        self.error = label("", wrap=True, color="#ff4d6d", small=True)
        self.error.hide()
        self.submit_btn = button("登入系統", "primary", on_click=self.submit)
        self.submit_btn.setMinimumHeight(38)

        demo_box = QVBoxLayout()
        demo_box.setSpacing(6)
        demo_box.addWidget(label("示範帳號", faint=True, small=True))
        for user, pwd, desc in DEMO_ACCOUNTS:
            b = QPushButton(f"{user}    {desc}")
            b.setProperty("kind", "ghost")
            b.setStyleSheet("text-align:left;padding:6px 10px;font-size:9pt")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, u=user, p=pwd: self._fill(u, p))
            demo_box.addWidget(b)

        server = label(f"伺服器:{settings.server_url}", faint=True, small=True, mono=True)

        lay = vbox(head, field("帳號", self.username), field("密碼", self.password), self.error, self.submit_btn,
                   demo_box, server, spacing=14, margins=(30, 28, 30, 24))
        card.setLayout(lay)

        root = QVBoxLayout(self)
        root.addStretch(1)
        root.addLayout(hbox("stretch", card, "stretch"))
        root.addStretch(1)

    def _remembered_user(self) -> str | None:
        try:
            return json.loads(self._pref.read_text(encoding="utf-8")).get("username")
        except (OSError, ValueError):
            return None

    def _fill(self, username: str, password: str):
        self.username.setText(username)
        self.password.setText(password)
        self.error.hide()

    def submit(self):
        username, password = self.username.text().strip(), self.password.text()
        if not username or not password:
            self._show_error("請輸入帳號與密碼")
            return
        self.error.hide()
        self.submit_btn.setEnabled(False)
        self.submit_btn.setText("驗證中…")

        def ok(_user):
            try:
                self._pref.write_text(json.dumps({"username": username}), encoding="utf-8")
            except OSError:
                pass
            self.submit_btn.setEnabled(True)
            self.submit_btn.setText("登入系統")
            self.loggedIn.emit()

        def err(exc):
            self.submit_btn.setEnabled(True)
            self.submit_btn.setText("登入系統")
            self._show_error(error_message(exc, "登入失敗"))

        run_async(lambda: api.login(username, password), ok, err, owner=self)

    def _show_error(self, text: str):
        self.error.setText(text)
        self.error.show()

    def paintEvent(self, _):
        """深色背景 + 網格 + 中央光暈,對應原版登入頁的科技風背景。"""
        p = QPainter(self)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0, QColor("#071226"))
        g.setColorAt(1, QColor("#03070f"))
        p.fillRect(self.rect(), g)
        p.setPen(QPen(QColor(0, 229, 255, 16)))
        for x in range(0, self.width(), 40):
            p.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), 40):
            p.drawLine(0, y, self.width(), y)
        rg = QRadialGradient(QPointF(self.width() / 2, self.height() / 2), max(self.width(), self.height()) / 2)
        rg.setColorAt(0, QColor(0, 229, 255, 38))
        rg.setColorAt(1, QColor(0, 229, 255, 0))
        p.fillRect(QRectF(self.rect()), rg)
