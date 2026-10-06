"""共用 UI 元件:Panel、KPI、Tag、電量條、表格、分頁、對話框、Toast。"""
from __future__ import annotations

from datetime import datetime
from typing import Callable, Iterable

from PyQt5.QtCore import QDateTime, QEvent, QPropertyAnimation, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath
from PyQt5.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDateTimeEdit, QDialog, QDoubleSpinBox, QFrame, QGraphicsOpacityEffect,
    QGridLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLayout, QLineEdit, QMessageBox, QProgressBar,
    QMenu, QPushButton, QSizePolicy, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import fmt
from ..theme import MONO_FAMILY

# ============================================================ 小工具


def button(text: str, kind: str | None = None, size: str | None = None,
           on_click: Callable[[], None] | None = None, tooltip: str | None = None) -> QPushButton:
    b = QPushButton(text)
    b.setCursor(Qt.PointingHandCursor)
    if kind:
        b.setProperty("kind", kind)
    if size:
        b.setProperty("size", size)
    if tooltip:
        b.setToolTip(tooltip)
    if kind == "link":
        # 連結鈕在表格內常被量窄,依等寬字型預先算好最小寬度
        b.setMinimumWidth(QFontMetrics(mono_font(10)).horizontalAdvance(text) + 8)
    if on_click:
        b.clicked.connect(lambda _=False: on_click())
    return b


def label(text: str = "", *, faint=False, dim=False, mono=False, small=False, bold=False, wrap=False,
          color: str | None = None, object_name: str | None = None) -> QLabel:
    lb = QLabel(text)
    for name, on in (("faint", faint), ("dim", dim), ("mono", mono), ("small", small)):
        if on:
            lb.setProperty(name, True)
    style = []
    if bold:
        style.append("font-weight:600")
    if color:
        style.append(f"color:{color}")
    if style:
        lb.setStyleSheet(";".join(style))
    if wrap:
        lb.setWordWrap(True)
    if object_name:
        lb.setObjectName(object_name)
    return lb


def mono_font(size: float = 9.5) -> QFont:
    f = QFont(MONO_FAMILY)
    f.setPointSizeF(size)
    return f


def hbox(*items, spacing: int = 8, margins=(0, 0, 0, 0)) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for it in items:
        _add(lay, it)
    return lay


def vbox(*items, spacing: int = 8, margins=(0, 0, 0, 0)) -> QVBoxLayout:
    lay = QVBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for it in items:
        _add(lay, it)
    return lay


def _add(lay, it) -> None:
    if it is None:
        return
    if it == "stretch":
        lay.addStretch(1)
    elif isinstance(it, QLayout):
        lay.addLayout(it)
    else:
        lay.addWidget(it)


def toolbar(*items, margins=(14, 12, 14, 4)) -> QWidget:
    """篩選列:欄位與按鈕底部對齊,高度固定不被拉伸。"""
    w = QWidget()
    w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    lay = QHBoxLayout(w)
    lay.setContentsMargins(*margins)
    lay.setSpacing(10)
    for it in items:
        if it is None:
            continue
        if it == "stretch":
            lay.addStretch(1)
        elif isinstance(it, QLayout):
            lay.addLayout(it)
        else:
            lay.addWidget(it, 0, Qt.AlignBottom)
    return w


def icon_button(text: str, tooltip: str, on_click: Callable[[], None], danger: bool = False) -> QPushButton:
    """列表內的小方形操作鈕 (▲ ▼ ✕ ✎ ＋)。"""
    b = QPushButton(text)
    b.setCursor(Qt.PointingHandCursor)
    b.setToolTip(tooltip)
    b.setFixedSize(26, 26)
    color = fmt.DANGER if danger else fmt.TEXT_DIM
    border = "rgba(255,77,109,0.5)" if danger else "rgba(148,178,214,0.25)"
    b.setStyleSheet(f"QPushButton{{padding:0;font-size:9pt;color:{color};background:transparent;"
                    f"border:1px solid {border};border-radius:3px}}"
                    f"QPushButton:hover{{color:#00e5ff;border-color:#00e5ff;background:rgba(0,229,255,0.1)}}")
    b.clicked.connect(lambda _=False: on_click())
    return b


def menu_button(text: str, actions: list, kind: str = "ghost") -> QPushButton:
    """下拉選單按鈕。actions: [(文字, callback) 或 None (分隔線)]。"""
    b = button(text + " ▾", kind, "sm")
    m = QMenu(b)
    for item in actions:
        if item is None:
            m.addSeparator()
            continue
        title, fn = item
        act = m.addAction(title)
        act.triggered.connect(lambda _=False, f=fn: f())
    b.setMenu(m)
    b.setStyleSheet("QPushButton::menu-indicator{width:0;image:none}")
    return b


def wrap_layout(layout: QLayout) -> QWidget:
    w = QWidget()
    w.setLayout(layout)
    return w


def clear_layout(layout: QLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            clear_layout(item.layout())


# ============================================================ Tag / 電量 / 進度


def tag(text: str, kind: str = "dim") -> QLabel:
    color, bg, border = fmt.TAG_STYLES.get(kind, fmt.TAG_STYLES["dim"])
    lb = QLabel(text)
    lb.setStyleSheet(f"color:{color};background:{bg};border:1px solid {border};border-radius:3px;"
                     f"padding:1px 7px;font-size:8.5pt;")
    font = QFont(lb.font())
    font.setPointSizeF(8.5)
    lb.setMinimumWidth(QFontMetrics(font).horizontalAdvance(text) + 18)
    lb.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    return lb


def tags_cell(*tags: QLabel) -> QWidget:
    w = QWidget()
    lay = hbox(*tags, "stretch", spacing=4, margins=(6, 0, 6, 0))
    w.setLayout(lay)
    return w


class BatteryBar(QWidget):
    """電量條:依電量變色 (≥60 綠 / ≥30 橘 / 其餘紅) 並顯示百分比。"""

    def __init__(self, percent: float = 0, parent=None):
        super().__init__(parent)
        self._pct = 0.0
        self.setMinimumSize(110, 18)
        self.set_percent(percent)

    def set_percent(self, percent) -> None:
        self._pct = max(0.0, min(100.0, float(percent or 0)))
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(150, 18)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        color = QColor(fmt.OK if self._pct >= 60 else fmt.WARN if self._pct >= 30 else fmt.DANGER)
        text_w = 46
        bar = QRectF(1, self.height() / 2 - 4, self.width() - text_w - 6, 8)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(148, 178, 214, 30))
        p.drawRoundedRect(bar, 3, 3)
        fill = QRectF(bar.x(), bar.y(), bar.width() * self._pct / 100, bar.height())
        glow = QColor(color)
        glow.setAlpha(70)
        p.setBrush(glow)
        p.drawRoundedRect(fill.adjusted(-1, -1, 1, 1), 4, 4)
        p.setBrush(color)
        p.drawRoundedRect(fill, 3, 3)
        p.setPen(color)
        p.setFont(mono_font(8.5))
        p.drawText(QRectF(self.width() - text_w, 0, text_w, self.height()), Qt.AlignRight | Qt.AlignVCenter,
                   f"{self._pct:.0f}%")


def progress_cell(percent: int) -> QWidget:
    w = QWidget()
    bar = QProgressBar()
    bar.setRange(0, 100)
    bar.setValue(int(percent or 0))
    bar.setTextVisible(False)
    bar.setFixedHeight(6)
    lb = label(f"{int(percent or 0)}%", mono=True, small=True, faint=True)
    lb.setAlignment(Qt.AlignRight)
    w.setLayout(vbox(bar, lb, spacing=2, margins=(8, 4, 8, 2)))
    w.bar, w.text = bar, lb  # type: ignore[attr-defined]
    return w


def set_progress_cell(w: QWidget, percent: int) -> None:
    w.bar.setValue(int(percent or 0))  # type: ignore[attr-defined]
    w.text.setText(f"{int(percent or 0)}%")  # type: ignore[attr-defined]


# ============================================================ Panel / KPI


class Panel(QFrame):
    """有標題列與動作區的卡片容器,對應原版 PanelCard。"""

    def __init__(self, title: str | None = None, padded: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.head = QFrame()
        self.head.setObjectName("PanelHead")
        self.title_label = QLabel(title or "")
        self.title_label.setObjectName("PanelTitle")
        self.actions = QHBoxLayout()
        self.actions.setSpacing(6)
        head_lay = hbox(self.title_label, "stretch", self.actions, margins=(14, 9, 12, 9))
        self.head.setLayout(head_lay)
        self.head.setVisible(bool(title))
        outer.addWidget(self.head)
        self.body = QVBoxLayout()
        pad = 14 if padded else 0
        self.body.setContentsMargins(pad, pad, pad, pad)
        self.body.setSpacing(10)
        outer.addLayout(self.body, 1)

    def set_title(self, title: str) -> None:
        self.title_label.setText(title)
        self.head.setVisible(bool(title) or self.actions.count() > 0)

    def add_action(self, widget: QWidget) -> QWidget:
        self.actions.addWidget(widget)
        self.head.setVisible(True)
        return widget

    def add(self, item) -> None:
        _add(self.body, item)


class KpiCard(QFrame):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Kpi")
        self.setMinimumHeight(96)
        self.title = QLabel(title)
        self.title.setObjectName("KpiLabel")
        self.value = QLabel("—")
        self.value.setObjectName("KpiValue")
        self.value.setTextFormat(Qt.RichText)
        self.foot = QLabel("")
        self.foot.setObjectName("KpiFoot")
        self.foot.setWordWrap(True)
        self.setLayout(vbox(self.title, self.value, self.foot, "stretch", spacing=4, margins=(16, 12, 16, 12)))

    def set(self, value, unit: str = "", foot: str | None = None, color: str | None = None,
            size_pt: float | None = None) -> None:
        unit_html = f"<span style='font-size:10pt;color:#8ba3c0;font-weight:400'> {unit}</span>" if unit else ""
        self.value.setText(f"{value}{unit_html}")
        style = []
        if color:
            style.append(f"color:{color}")
        if size_pt:
            style.append(f"font-size:{size_pt}pt")
        self.value.setStyleSheet(";".join(style))
        if foot is not None:
            self.foot.setText(foot)


def kpi_row(*cards: KpiCard) -> QHBoxLayout:
    return hbox(*cards, spacing=14)


# ============================================================ 表單欄位


def field(title: str, widget: QWidget | QLayout, hint: str | None = None) -> QWidget:
    w = QWidget()
    lb = QLabel(title)
    lb.setObjectName("FieldLabel")
    items = [lb, widget]
    if hint:
        items.append(label(hint, faint=True, small=True, wrap=True))
    w.setLayout(vbox(*items, spacing=4))
    return w


def line_edit(text: str = "", placeholder: str = "", mono: bool = False) -> QLineEdit:
    e = QLineEdit(text)
    e.setPlaceholderText(placeholder)
    if mono:
        e.setFont(mono_font(10))
    return e


def int_spin(value: int = 0, lo: int = 0, hi: int = 1_000_000, suffix: str = "") -> QSpinBox:
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setValue(int(value))
    s.setFont(mono_font(10))
    if suffix:
        s.setSuffix(suffix)
    return s


def float_spin(value: float = 0, lo: float = -1e9, hi: float = 1e9, decimals: int = 2, step: float = 1.0,
               suffix: str = "") -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setDecimals(decimals)
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setValue(float(value))
    s.setFont(mono_font(10))
    if suffix:
        s.setSuffix(suffix)
    return s


def combo(options: Iterable[tuple[str, object]], current=None) -> QComboBox:
    """options: [(顯示文字, 值)]。以 combo.currentData() 取值。"""
    c = QComboBox()
    for text, value in options:
        c.addItem(text, value)
    if current is not None:
        set_combo(c, current)
    return c


def set_combo(c: QComboBox, value) -> None:
    for i in range(c.count()):
        if c.itemData(i) == value:
            c.setCurrentIndex(i)
            return


def checkbox(text: str, checked: bool = False) -> QCheckBox:
    cb = QCheckBox(text)
    cb.setChecked(checked)
    return cb


class OptionalDateTime(QWidget):
    """可留空的日期時間 (勾選才啟用)。"""

    def __init__(self, enable_text: str = "指定", value: datetime | None = None, parent=None):
        super().__init__(parent)
        self.check = QCheckBox(enable_text)
        self.edit = QDateTimeEdit()
        self.edit.setCalendarPopup(True)
        self.edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.edit.setDateTime(QDateTime.currentDateTime())
        self.check.toggled.connect(self.edit.setEnabled)
        self.setLayout(hbox(self.check, self.edit, spacing=8))
        self.set_value(value)

    def set_value(self, value: datetime | None) -> None:
        self.check.setChecked(value is not None)
        self.edit.setEnabled(value is not None)
        if value is not None:
            self.edit.setDateTime(QDateTime(value.year, value.month, value.day, value.hour, value.minute))

    def value(self) -> datetime | None:
        if not self.check.isChecked():
            return None
        return self.edit.dateTime().toPyDateTime().astimezone()


# ============================================================ 表格


class DataTable(QTableWidget):
    """唯讀表格。columns: [(標題, 對齊 'l'|'r'|'c', 寬度或 None)]。"""

    rowActivated = pyqtSignal(int)

    def __init__(self, columns: list[tuple[str, str, int | None]], parent=None, stretch_col: int | None = None):
        super().__init__(0, len(columns), parent)
        self.columns = columns
        self.setHorizontalHeaderLabels([c[0] for c in columns])
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setFocusPolicy(Qt.NoFocus)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.verticalHeader().setDefaultSectionSize(40)
        header = self.horizontalHeader()
        header.setHighlightSections(False)
        header.setMinimumSectionSize(40)
        header.setSectionResizeMode(QHeaderView.Interactive)
        for i, (_, align, _w) in enumerate(columns):
            self.horizontalHeaderItem(i).setTextAlignment(self._align(align) | Qt.AlignVCenter)
        # 最後一欄若是操作鈕 (標題空白),一律依內容寬度,不參與延展,避免按鈕被擠扁;
        # 改由 stretch_col (預設第 2 欄) 吸收多餘寬度
        last = len(columns) - 1
        self._actions_col = last if columns[last][0] == "" else None
        if stretch_col is None:
            stretch_col = (1 if last >= 1 else 0) if self._actions_col is not None else last
        self._stretch_col = stretch_col
        header.setStretchLastSection(False)
        self._autosize_timer = QTimer(self, singleShot=True, interval=0, timeout=self._autosize)
        self._placeholder = QLabel(self.viewport())
        self._placeholder.setObjectName("Empty")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.hide()
        self.cellDoubleClicked.connect(lambda r, _c: self.rowActivated.emit(r))
        self.cellClicked.connect(lambda r, _c: self.rowActivated.emit(r))

    @staticmethod
    def _align(code: str):
        return {"r": Qt.AlignRight, "c": Qt.AlignHCenter}.get(code, Qt.AlignLeft)

    def show_message(self, text: str | None) -> None:
        if text:
            self.setRowCount(0)
            self._placeholder.setText(text)
            self._placeholder.setGeometry(0, 0, self.viewport().width(), 90)
            self._placeholder.show()
        else:
            self._placeholder.hide()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._placeholder.setGeometry(0, 0, self.viewport().width(), 90)
        self._fill_stretch()

    def reset_rows(self, count: int, empty_text: str = "沒有符合條件的資料") -> None:
        self.clearContents()
        self.setRowCount(count)
        self.show_message(None if count else empty_text)
        self._autosize_timer.start()  # 等呼叫端填完資料再依內容調整欄寬

    def _autosize(self) -> None:
        """依內容 (含儲存格內的元件) 調整欄寬,單欄最寬 360px;多出的寬度給 stretch 欄,
        總寬超過可視區時出現水平捲軸,操作鈕不會被擠扁。沒資料時沿用 columns 設定的寬度。"""
        if self.rowCount() == 0:
            for i, (_, _a, width) in enumerate(self.columns):
                self.setColumnWidth(i, width or 120)
            self._fill_stretch()
            return
        for i in range(len(self.columns)):
            self.resizeColumnToContents(i)
            width = self.columnWidth(i)
            for r in range(self.rowCount()):
                cw = self.cellWidget(r, i)
                if cw is not None:
                    # 尚未顯示過的元件還沒套用樣式表 (padding/字型),先 polish 再量,否則會量得偏窄
                    for child in [cw, *cw.findChildren(QWidget)]:
                        child.ensurePolished()
                    if cw.layout() is not None:
                        cw.layout().invalidate()
                    width = max(width, cw.sizeHint().width())
            cap = 10_000 if i == self._actions_col else 360
            self.setColumnWidth(i, min(cap, width + 8))
        self._natural = self.columnWidth(self._stretch_col)
        self._fill_stretch()

    def _fill_stretch(self) -> None:
        if not hasattr(self, "_stretch_col"):  # 建構中觸發的 resize
            return
        natural = getattr(self, "_natural", self.columnWidth(self._stretch_col))
        others = sum(self.columnWidth(i) for i in range(len(self.columns)) if i != self._stretch_col)
        self.setColumnWidth(self._stretch_col, max(natural, self.viewport().width() - others))

    def set_text(self, row: int, col: int, text, *, mono=False, faint=False, dim=False, color: str | None = None,
                 tooltip: str | None = None, data=None) -> QTableWidgetItem:
        item = QTableWidgetItem("" if text is None else str(text))
        item.setTextAlignment(self._align(self.columns[col][1]) | Qt.AlignVCenter)
        if mono:
            item.setFont(mono_font(9.5))
        if color:
            item.setForeground(QColor(color))
        elif faint:
            item.setForeground(QColor(fmt.TEXT_FAINT))
        elif dim:
            item.setForeground(QColor(fmt.TEXT_DIM))
        if tooltip:
            item.setToolTip(tooltip)
        if data is not None:
            item.setData(Qt.UserRole, data)
        self.setItem(row, col, item)
        return item

    def set_two_line(self, row: int, col: int, main: str, sub: str, sub_mono: bool = True) -> None:
        w = QWidget()
        a = QLabel(main)
        b = label(sub, faint=True, small=True, mono=sub_mono)
        w.setLayout(vbox(a, b, spacing=0, margins=(8, 2, 8, 2)))
        self.setCellWidget(row, col, w)
        self.setRowHeight(row, 46)

    def set_actions(self, row: int, col: int, buttons: list[QPushButton]) -> None:
        w = QWidget()
        lay = hbox("stretch", *buttons, spacing=5, margins=(6, 3, 8, 3))
        lay.setSizeConstraint(QLayout.SetMinimumSize)
        w.setLayout(lay)
        self.setCellWidget(row, col, w)


class Pager(QWidget):
    """分頁列,對應原版 DataPager。"""

    changed = pyqtSignal(int, int)  # page, page_size

    def __init__(self, page_size: int = 20, parent=None):
        super().__init__(parent)
        self.page = 1
        self.page_size = page_size
        self.total = 0
        self.info = label("", faint=True, small=True)
        self.size_combo = combo([(f"{n} 筆/頁", n) for n in (10, 20, 50, 100)], page_size)
        self.size_combo.currentIndexChanged.connect(self._size_changed)
        self.prev_btn = button("‹ 上一頁", "ghost", "sm", self._prev)
        self.next_btn = button("下一頁 ›", "ghost", "sm", self._next)
        self.page_label = label("", mono=True, small=True)
        self.setLayout(hbox(self.info, "stretch", self.size_combo, self.prev_btn, self.page_label, self.next_btn,
                            margins=(14, 8, 14, 10)))
        self.set_total(0)

    @property
    def pages(self) -> int:
        return max(1, -(-self.total // self.page_size))

    def set_total(self, total: int) -> None:
        self.total = total
        start = 0 if total == 0 else (self.page - 1) * self.page_size + 1
        end = min(total, self.page * self.page_size)
        self.info.setText(f"共 {total} 筆 · 顯示 {start}–{end}")
        self.page_label.setText(f"{self.page} / {self.pages}")
        self.prev_btn.setEnabled(self.page > 1)
        self.next_btn.setEnabled(self.page < self.pages)

    def reset(self) -> None:
        self.page = 1

    def _prev(self):
        if self.page > 1:
            self.page -= 1
            self.changed.emit(self.page, self.page_size)

    def _next(self):
        if self.page < self.pages:
            self.page += 1
            self.changed.emit(self.page, self.page_size)

    def _size_changed(self):
        self.page_size = self.size_combo.currentData()
        self.page = 1
        self.changed.emit(self.page, self.page_size)


# ============================================================ 對話框


class FormDialog(QDialog):
    """標題 + 內容 + 取消/確認的通用對話框 (對應 ModalDialog)。on_confirm 回傳 False 時不關閉。"""

    def __init__(self, parent: QWidget | None, title: str, confirm_text: str = "儲存", width: int = 560,
                 hide_footer: bool = False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(width)
        self.on_confirm: Callable[[], None] | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 16)
        outer.setSpacing(14)
        t = QLabel(title)
        t.setStyleSheet("font-size:12.5pt;font-weight:600;color:#00e5ff;letter-spacing:1px")
        outer.addWidget(t)
        self.body = QVBoxLayout()
        self.body.setSpacing(12)
        outer.addLayout(self.body, 1)
        self.cancel_btn = button("取消" if not hide_footer else "關閉", "ghost", on_click=self.reject)
        self.confirm_btn = button(confirm_text, "primary", on_click=self._confirm)
        self._confirm_text = confirm_text
        foot = hbox("stretch", self.cancel_btn, self.confirm_btn)
        if hide_footer:
            self.confirm_btn.hide()
        outer.addLayout(foot)

    def add(self, item) -> None:
        _add(self.body, item)

    def grid(self, fields: list[QWidget], columns: int = 2) -> QGridLayout:
        """把欄位排成 N 欄格線;欄位若設了 property full=True 則整列。"""
        g = QGridLayout()
        g.setHorizontalSpacing(14)
        g.setVerticalSpacing(10)
        r = c = 0
        for f in fields:
            if f.property("full"):
                if c:
                    r, c = r + 1, 0
                g.addWidget(f, r, 0, 1, columns)
                r += 1
                continue
            g.addWidget(f, r, c)
            c += 1
            if c >= columns:
                r, c = r + 1, 0
        self.body.addLayout(g)
        return g

    def set_busy(self, busy: bool) -> None:
        self.confirm_btn.setEnabled(not busy)
        self.confirm_btn.setText("處理中…" if busy else self._confirm_text)

    def _confirm(self):
        if self.on_confirm:
            self.on_confirm()
        else:
            self.accept()


def full(widget: QWidget) -> QWidget:
    widget.setProperty("full", True)
    return widget


def confirm(parent: QWidget, text: str, title: str = "確認") -> bool:
    box = QMessageBox(QMessageBox.Question, title, text, QMessageBox.Yes | QMessageBox.No, parent)
    box.button(QMessageBox.Yes).setText("確定")
    box.button(QMessageBox.No).setText("取消")
    box.setDefaultButton(QMessageBox.No)
    return box.exec_() == QMessageBox.Yes


def prompt_text(parent: QWidget, title: str, text: str, default: str = "") -> str | None:
    dlg = QInputDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setLabelText(text)
    dlg.setTextValue(default)
    dlg.setOkButtonText("確定")
    dlg.setCancelButtonText("取消")
    return dlg.textValue() if dlg.exec_() == QDialog.Accepted else None


# ============================================================ Toast


class ToastHost(QWidget):
    """右下角浮動提示。透明覆蓋在主視窗上,不攔截滑鼠。"""

    COLORS = {"info": fmt.INFO, "success": fmt.OK, "warn": fmt.WARN, "error": fmt.DANGER}

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 18, 18)
        self._lay.setSpacing(8)
        self._lay.addStretch(1)
        parent.installEventFilter(self)
        self._fit()

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Resize:
            self._fit()
        return False

    def _fit(self):
        p = self.parentWidget()
        w = 380
        self.setGeometry(p.width() - w, 60, w, p.height() - 60)
        self.raise_()

    def show_toast(self, text: str, level: str = "info", ms: int = 3800) -> None:
        color = self.COLORS.get(level, fmt.INFO)
        card = QLabel(text)
        card.setWordWrap(True)
        card.setStyleSheet(
            f"background: rgba(10,20,36,0.96); border:1px solid {color}; border-left:4px solid {color};"
            f"border-radius:5px; padding:10px 14px; color:#dceaf7;")
        self._lay.addWidget(card, 0, Qt.AlignRight)
        card.setMaximumWidth(360)
        self.raise_()
        effect = QGraphicsOpacityEffect(card)
        card.setGraphicsEffect(effect)
        effect.setOpacity(1.0)

        def fade():
            anim = QPropertyAnimation(effect, b"opacity", card)
            anim.setDuration(350)
            anim.setStartValue(1.0)
            anim.setEndValue(0.0)
            anim.finished.connect(card.deleteLater)
            anim.start()

        QTimer.singleShot(ms, fade)


_toast_host: ToastHost | None = None


def set_toast_host(host: ToastHost | None) -> None:
    global _toast_host
    _toast_host = host


def toast(text: str, level: str = "info", ms: int = 3800) -> None:
    if _toast_host is not None:
        _toast_host.show_toast(text, level, ms)


def rounded_rect_path(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path

