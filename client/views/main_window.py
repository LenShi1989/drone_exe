"""
主視窗:漢堡排側邊欄 + 頂部列 + 功能頁。

側邊欄完全由後端 GET /api/menu 資料驅動 (依角色權限過濾),
新增功能頁只需在資料庫加 MenuItem + Permission,並在 ROUTES 註冊對應頁面類別。
"""
from __future__ import annotations

import importlib
from datetime import datetime

from PyQt5.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPushButton, QScrollArea, QStackedWidget, QToolButton,
    QVBoxLayout, QWidget,
)

from ..api import api, error_message
from ..realtime import telemetry
from ..tasks import run_async
from ..widgets.common import FormDialog, ToastHost, button, field, hbox, label, set_toast_host, toast, vbox
from .base import Page
from .login import LogoMark

# path → (模組:類別, 麵包屑標題)
ROUTES: dict[str, tuple[str, str]] = {
    "/monitor": ("monitor:MonitorPage", "即時監控"),
    "/map/editor": ("map_editor:MapEditorPage", "地圖編輯"),
    "/map/history": ("map_history:MapHistoryPage", "歷史地圖"),
    "/drone/settings": ("drones:DroneSettingsPage", "無人機設定"),
    "/drone/status": ("drones:DroneStatusPage", "無人機狀態"),
    "/cameras": ("cameras:CameraPage", "攝影機管理"),
    "/workorder/current": ("workorders:WorkOrderCurrentPage", "當前工單"),
    "/workorder/history": ("workorders:WorkOrderHistoryPage", "歷史工單"),
    "/workorder/templates": ("workorders:WorkOrderTemplatePage", "工單模板"),
    "/stats/missions": ("stats:MissionCountPage", "任務數量"),
    "/stats/workorders": ("stats:WorkOrderChartPage", "工單圖表"),
    "/stats/duration": ("stats:DurationChartPage", "工單用時"),
    "/stats/charging": ("stats:ChargingChartPage", "充電圖表"),
    "/logs/missions": ("logs:MissionLogPage", "任務紀錄"),
    "/logs/logins": ("logs:LoginLogPage", "登入紀錄"),
    "/logs/notifications": ("logs:NotificationPage", "通知中心"),
    "/system/users": ("system:UserPage", "帳號管理"),
    "/system/roles": ("system:RolePage", "角色管理"),
}

ICONS = {
    "radar": "◉", "map": "▦", "edit-map": "✎", "history": "⟲", "drone": "✈", "settings": "⚙",
    "battery": "▮", "camera": "◙", "clipboard": "☰", "play": "▶", "archive": "▤", "template": "❒",
    "chart": "▥", "chart-bar": "▇", "chart-pie": "◔", "clock": "◷", "bolt": "ϟ", "list": "≣",
    "route": "⤳", "login": "⇥", "bell": "◎", "shield": "⛨", "user": "☺", "key": "⚿",
}

SIDEBAR_W, SIDEBAR_COLLAPSED_W = 236, 58


class Hamburger(QToolButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Hamburger")
        self.setFixedSize(34, 34)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("收合側邊欄")

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor("#00e5ff"), 2, Qt.SolidLine, Qt.RoundCap))
        hover = self.underMouse()
        for i, dx in enumerate((2 if hover else 0, 0, -2 if hover else 0)):
            y = 11 + i * 6
            p.drawLine(QPointF(8 + dx, y), QPointF(26 + dx, y))


class BellButton(QToolButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Bell")
        self.setFixedSize(34, 34)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("通知中心")
        self.count = 0

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor("#8ba3c0"), 1.6))
        # 鈴鐺
        p.drawArc(QRectF(10, 8, 14, 16), 0, 180 * 16)
        p.drawLine(QPointF(10, 16), QPointF(10, 22))
        p.drawLine(QPointF(24, 16), QPointF(24, 22))
        p.drawLine(QPointF(8, 22), QPointF(26, 22))
        p.drawEllipse(QPointF(17, 25), 1.8, 1.8)
        if self.count > 0:
            text = "99+" if self.count > 99 else str(self.count)
            w = 8 + 6 * len(text)
            rect = QRectF(self.width() - w, 0, w, 15)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#ff4d6d"))
            p.drawRoundedRect(rect, 7, 7)
            p.setPen(QColor("#150408"))
            f = p.font()
            f.setPointSizeF(7)
            f.setBold(True)
            p.setFont(f)
            p.drawText(rect, Qt.AlignCenter, text)


class NoAccessPage(Page):
    title = "無存取權限"
    subtitle = "您的角色沒有此功能的權限,請聯絡系統管理員。"


class MainWindow(QMainWindow):
    loggedOut = pyqtSignal()

    def __init__(self, menu: list[dict]):
        super().__init__()
        self.setWindowTitle("無人機操作系統 — Drone Ops Center")
        self.resize(1480, 920)
        self.menu = menu
        self.allowed = {c["path"]: c for n in menu for c in ([n] if n["path"] else n["children"])}
        self.pages: dict[str, Page] = {}
        self.current_path: str | None = None
        self.collapsed = False
        self.nav_buttons: dict[str, QPushButton] = {}
        self.group_boxes: dict[str, QWidget] = {}
        self.group_buttons: dict[str, QPushButton] = {}
        self.open_groups: set[str] = set()

        root = QWidget()
        root.setObjectName("Root")
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.sidebar = self._build_sidebar()
        lay.addWidget(self.sidebar)
        main = QVBoxLayout()
        main.setSpacing(0)
        main.setContentsMargins(0, 0, 0, 0)
        main.addWidget(self._build_topbar())
        self.stack = QStackedWidget()
        main.addWidget(self.stack, 1)
        lay.addLayout(main, 1)
        self.setCentralWidget(root)

        self.toast_host = ToastHost(root)
        set_toast_host(self.toast_host)

        telemetry.connectedChanged.connect(self._on_connected)
        telemetry.snapshotsChanged.connect(self._on_snapshots)
        telemetry.notificationReceived.connect(self._on_notification)
        telemetry.start()

        self._clock = QTimer(self, interval=1000, timeout=self._tick)
        self._clock.start()
        self._tick()
        self._unread_timer = QTimer(self, interval=60000, timeout=self.refresh_unread)
        self._unread_timer.start()
        self.refresh_unread()

        self.navigate(self.first_path())
        self._auto_collapse_checked = False

    def showEvent(self, e):
        super().showEvent(e)
        # 小螢幕 (例如 1920×1080 @150% 縮放,可用寬度僅 1280) 預設收合側邊欄,讓表格有足夠空間
        if not self._auto_collapse_checked:
            self._auto_collapse_checked = True
            QTimer.singleShot(0, self._maybe_collapse)

    def _maybe_collapse(self):
        if self.width() < 1400 and not self.collapsed:
            self.toggle_sidebar()

    # ------------------------------------------------------------------ 版面

    def _build_sidebar(self) -> QFrame:
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(SIDEBAR_W)
        v = QVBoxLayout(side)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        brand = QFrame()
        brand.setObjectName("Brand")
        brand.setFixedHeight(56)
        self.brand_text = QWidget()
        name = QLabel("無人機操作系統")
        name.setObjectName("BrandName")
        sub = QLabel("DRONE OPS CENTER")
        sub.setObjectName("BrandSub")
        self.brand_text.setLayout(vbox(name, sub, spacing=0))
        brand.setLayout(hbox(LogoMark(28), self.brand_text, "stretch", spacing=10, margins=(14, 0, 10, 0)))
        v.addWidget(brand)

        nav = QWidget()
        nav_lay = QVBoxLayout(nav)
        nav_lay.setContentsMargins(6, 8, 6, 8)
        nav_lay.setSpacing(2)
        for node in self.menu:
            if node["path"]:
                nav_lay.addWidget(self._nav_button(node, child=False))
                continue
            gb = self._nav_button(node, child=False, group=True)
            self.group_buttons[node["key"]] = gb
            nav_lay.addWidget(gb)
            box = QWidget()
            box_lay = QVBoxLayout(box)
            box_lay.setContentsMargins(0, 2, 0, 4)
            box_lay.setSpacing(1)
            for child in node["children"]:
                box_lay.addWidget(self._nav_button(child, child=True))
            box.setVisible(False)
            self.group_boxes[node["key"]] = box
            nav_lay.addWidget(box)
        nav_lay.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(nav)
        scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        v.addWidget(scroll, 1)

        foot = QFrame()
        foot.setObjectName("SidebarFoot")
        self.conn_dot = QLabel("●")
        self.conn_text = label("遙測未連線", faint=True, small=True)
        foot.setLayout(hbox(self.conn_dot, self.conn_text, "stretch", spacing=7, margins=(14, 10, 14, 10)))
        v.addWidget(foot)
        self._on_connected(False)
        return side

    def _nav_button(self, node: dict, child: bool, group: bool = False) -> QPushButton:
        icon = ICONS.get(node.get("icon", ""), "•")
        b = QPushButton()
        b.setObjectName("NavItem")
        b.setCursor(Qt.PointingHandCursor)
        b.setProperty("child", child)
        b.setProperty("origChild", child)
        b.setProperty("title", node["title"])
        b.setProperty("glyph", icon)
        b.setProperty("isGroup", group)
        if group:
            b.clicked.connect(lambda _=False, k=node["key"]: self._toggle_group(k))
        else:
            self.nav_buttons[node["path"]] = b
            b.clicked.connect(lambda _=False, p=node["path"]: self.navigate(p))
        self._render_nav_text(b)
        return b

    def _render_nav_text(self, b: QPushButton):
        glyph, title = b.property("glyph"), b.property("title")
        if self.collapsed:
            b.setText(glyph)
            b.setToolTip(title)
        else:
            chevron = ""
            if b.property("isGroup"):
                key = next((k for k, gb in self.group_buttons.items() if gb is b), None)
                chevron = "   ▴" if key in self.open_groups else "   ▾"
            b.setText(f"{glyph}   {title}{chevron}")
            b.setToolTip("")

    def _toggle_group(self, key: str):
        if key in self.open_groups:
            self.open_groups.discard(key)
        else:
            self.open_groups.add(key)
        self._sync_groups()

    def _sync_groups(self):
        for key, box in self.group_boxes.items():
            box.setVisible(self.collapsed or key in self.open_groups)
        for b in list(self.nav_buttons.values()) + list(self.group_buttons.values()):
            self._render_nav_text(b)

    def toggle_sidebar(self):
        self.collapsed = not self.collapsed
        self.sidebar.setFixedWidth(SIDEBAR_COLLAPSED_W if self.collapsed else SIDEBAR_W)
        self.brand_text.setVisible(not self.collapsed)
        self.conn_text.setVisible(not self.collapsed)
        for b in self.nav_buttons.values():
            b.setProperty("child", bool(b.property("origChild")) and not self.collapsed)
            b.style().unpolish(b)
            b.style().polish(b)
        self._sync_groups()

    def _build_topbar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("Topbar")
        bar.setFixedHeight(56)
        burger = Hamburger()
        burger.clicked.connect(self.toggle_sidebar)
        cap = label("DRONE OPS", faint=True, small=True)
        cap.setStyleSheet("letter-spacing:2px")
        self.crumb = QLabel("")
        self.crumb.setObjectName("Crumbs")
        self.flying_chip = QLabel("● 0 飛行中")
        self.flying_chip.setObjectName("StatChip")
        self.clock_chip = QLabel("")
        self.clock_chip.setObjectName("StatChip")
        self.bell = BellButton()
        self.bell.clicked.connect(lambda: self.navigate("/logs/notifications"))
        user = api.user or {}
        name = QLabel(user.get("displayName", ""))
        name.setAlignment(Qt.AlignRight)
        role = label(user.get("roleName", ""), faint=True, small=True)
        role.setAlignment(Qt.AlignRight)
        user_box = QWidget()
        user_box.setLayout(vbox(name, role, spacing=0))
        pwd_btn = button("修改密碼", "ghost", "sm", self._change_password)
        logout_btn = button("登出", "ghost", "sm", self.logout)
        sep = QFrame()
        sep.setFixedWidth(1)
        sep.setStyleSheet("background: rgba(148,178,214,0.14)")
        sep.setFixedHeight(30)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 0, 16, 0)
        lay.setSpacing(12)
        for w in (burger, cap, label("/", faint=True), self.crumb, None, self.flying_chip, self.clock_chip, self.bell,
                  sep, user_box, pwd_btn, logout_btn):
            if w is None:
                lay.addStretch(1)
            else:
                lay.addWidget(w, 0, Qt.AlignVCenter)
        return bar

    # ------------------------------------------------------------------ 導覽

    def first_path(self) -> str:
        for node in self.menu:
            if node["path"]:
                return node["path"]
            for c in node["children"]:
                if c["path"]:
                    return c["path"]
        return "/no-access"

    def navigate(self, path: str):
        if path not in self.allowed or path not in ROUTES:
            path = "/no-access"
        if path == self.current_path:
            page = self.pages.get(path)
            if page:
                page.on_show()
            return
        old = self.pages.get(self.current_path) if self.current_path else None
        if old:
            old.on_hide()
        page = self.pages.get(path)
        if page is None:
            page = self._create_page(path)
            self.pages[path] = page
            self.stack.addWidget(page)
        self.current_path = path
        self.stack.setCurrentWidget(page)
        self.crumb.setText(ROUTES.get(path, ("", "無存取權限"))[1])
        for p, b in self.nav_buttons.items():
            b.setProperty("active", p == path)
            b.style().unpolish(b)
            b.style().polish(b)
        for node in self.menu:
            if any(c["path"] == path for c in node["children"]):
                self.open_groups.add(node["key"])
        self._sync_groups()
        page.on_show()

    def _create_page(self, path: str) -> Page:
        if path == "/no-access":
            return NoAccessPage(self)
        target, _ = ROUTES[path]
        module_name, cls_name = target.split(":")
        module = importlib.import_module(f"client.views.{module_name}")
        return getattr(module, cls_name)(self)

    # ------------------------------------------------------------------ 即時狀態

    def _tick(self):
        self.clock_chip.setText(datetime.now().strftime("%H:%M:%S"))

    def _on_connected(self, connected: bool):
        color = "#22e39b" if connected else "#ff4d6d"
        self.conn_dot.setStyleSheet(f"color:{color};font-size:9pt")
        self.conn_text.setText("遙測連線中" if connected else "遙測未連線")

    def _on_snapshots(self):
        n = len(telemetry.flying)
        self.flying_chip.setText(f"<span style='color:#22e39b'>●</span> {n} 飛行中")
        self.flying_chip.setToolTip(f"飛行中 {n} 台")

    def _on_notification(self, n: dict):
        level = {3: "error", 2: "warn", 1: "success"}.get(n.get("level"), "info")
        content = n.get("content")
        toast(f"{n.get('title', '')}{f' — {content}' if content else ''}", level)
        self.refresh_unread()

    def refresh_unread(self):
        def ok(count):
            self.bell.count = int(count or 0)
            self.bell.update()
            page = self.pages.get("/logs/notifications")
            if page is not None and hasattr(page, "set_unread"):
                page.set_unread(self.bell.count)

        run_async(api.unread_count, ok, lambda _e: None, owner=self)

    # ------------------------------------------------------------------ 帳號

    def _change_password(self):
        dlg = FormDialog(self, "修改密碼", "變更", width=420)
        old, new, again = QLineEdit(), QLineEdit(), QLineEdit()
        for e in (old, new, again):
            e.setEchoMode(QLineEdit.Password)
        dlg.add(field("目前密碼", old))
        dlg.add(field("新密碼 (至少 8 字元)", new))
        dlg.add(field("確認新密碼", again))

        def submit():
            if len(new.text()) < 8:
                toast("新密碼至少 8 個字元", "warn")
                return
            if new.text() != again.text():
                toast("兩次輸入的新密碼不一致", "warn")
                return
            dlg.set_busy(True)

            def ok(_):
                dlg.accept()
                toast("密碼已變更,其他裝置的登入狀態已失效", "success")

            def err(e):
                dlg.set_busy(False)
                toast(error_message(e, "變更密碼失敗"), "error")

            run_async(lambda: api.change_password(old.text(), new.text()), ok, err, owner=dlg)

        dlg.on_confirm = submit
        dlg.exec_()

    def logout(self):
        telemetry.stop()
        for page in self.pages.values():
            page.on_hide()
        run_async(api.logout, lambda _r: None, lambda _e: None)
        set_toast_host(None)
        self.loggedOut.emit()

    def session_expired(self):
        toast("登入已逾時,請重新登入", "warn")
        QTimer.singleShot(800, self.logout)

    def closeEvent(self, e):
        telemetry.stop()
        for page in self.pages.values():
            page.on_hide()
        super().closeEvent(e)
