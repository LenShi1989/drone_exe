"""深色科技風主題 (Cyan / Deep Navy),對應原 Vue 版 styles/tokens.css。"""
from __future__ import annotations

from PyQt5.QtGui import QColor, QFont, QPalette
from PyQt5.QtWidgets import QApplication

BG_ROOT = "#060b16"
BG_PANEL = "#0d1628"
BG_ELEVATED = "#12203a"
BG_INPUT = "#08111f"
LINE = "rgba(0,229,255,0.16)"
LINE_STRONG = "rgba(0,229,255,0.38)"
LINE_MUTED = "rgba(148,178,214,0.14)"

FONT_FAMILY = "Microsoft JhengHei UI"
MONO_FAMILY = "Consolas"

QSS = f"""
* {{
    font-family: "{FONT_FAMILY}", "Microsoft JhengHei", "Segoe UI", sans-serif;
    font-size: 10pt;
    color: #dceaf7;
}}
QMainWindow, QDialog, #Root {{ background: {BG_ROOT}; }}
QWidget#Page, QWidget#PageBody, QScrollArea#PageScroll, QScrollArea#PageScroll > QWidget > QWidget {{
    background: transparent;
}}
QToolTip {{
    background: {BG_ELEVATED}; color: #dceaf7; border: 1px solid {LINE_STRONG}; padding: 5px 7px;
}}

/* ---------------- Sidebar ---------------- */
#Sidebar {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0a1222, stop:1 #060c18);
    border-right: 1px solid {LINE};
}}
#Brand {{ border-bottom: 1px solid {LINE_MUTED}; }}
#BrandName {{ font-size: 10.5pt; font-weight: 600; letter-spacing: 1px; }}
#BrandSub {{ font-family: "{MONO_FAMILY}"; font-size: 7pt; letter-spacing: 3px; color: #0891a3; }}
#SidebarFoot {{ border-top: 1px solid {LINE_MUTED}; }}

QPushButton#NavItem {{
    text-align: left; padding: 8px 10px; border: none; border-left: 2px solid transparent;
    border-radius: 2px; color: #8ba3c0; background: transparent; font-size: 10pt;
}}
QPushButton#NavItem:hover {{ color: #dceaf7; background: rgba(0,229,255,0.08); }}
QPushButton#NavItem[active="true"] {{
    color: #00e5ff; background: rgba(0,229,255,0.10); border-left: 2px solid #00e5ff;
}}
QPushButton#NavItem[child="true"] {{ padding-left: 26px; font-size: 9.5pt; }}

/* ---------------- Topbar ---------------- */
#Topbar {{ background: rgba(8,15,28,0.92); border-bottom: 1px solid {LINE}; }}
#Crumbs {{ font-size: 10pt; letter-spacing: 1px; }}
QLabel#StatChip {{
    font-family: "{MONO_FAMILY}"; font-size: 9pt; color: #8ba3c0; padding: 4px 9px;
    background: rgba(0,229,255,0.05); border: 1px solid {LINE_MUTED}; border-radius: 4px;
}}
QToolButton#Hamburger, QToolButton#Bell {{
    border: 1px solid transparent; border-radius: 4px; padding: 4px; background: transparent;
}}
QToolButton#Bell {{ border: 1px solid {LINE_MUTED}; }}
QToolButton#Hamburger:hover, QToolButton#Bell:hover {{ border-color: {LINE_STRONG}; }}
QLabel#Badge {{
    background: #ff4d6d; color: #150408; border-radius: 8px; font-family: "{MONO_FAMILY}";
    font-size: 7.5pt; padding: 0 4px;
}}

/* ---------------- Page ---------------- */
QLabel#PageTitle {{ font-size: 15pt; font-weight: 600; letter-spacing: 1px; }}
QLabel#PageSub {{ color: #8ba3c0; font-size: 9pt; }}
QFrame#Panel {{
    background: rgba(13,22,40,0.86); border: 1px solid {LINE}; border-radius: 6px;
}}
QLabel#PanelTitle {{
    font-size: 9.5pt; font-weight: 600; letter-spacing: 1px; color: #dceaf7;
}}
QFrame#PanelHead {{ border-bottom: 1px solid {LINE_MUTED}; background: transparent; }}
QFrame#Kpi {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba(13,22,40,0.95), stop:1 rgba(10,28,48,0.95));
    border: 1px solid {LINE}; border-radius: 6px;
}}
QLabel#KpiLabel {{ color: #8ba3c0; font-size: 8.5pt; letter-spacing: 1px; }}
QLabel#KpiValue {{ font-family: "{MONO_FAMILY}"; font-size: 21pt; font-weight: 600; color: #00e5ff; }}
QLabel#KpiFoot {{ color: #5d738f; font-size: 8.5pt; }}
QLabel[faint="true"] {{ color: #5d738f; }}
QLabel[dim="true"] {{ color: #8ba3c0; }}
QLabel[mono="true"] {{ font-family: "{MONO_FAMILY}"; }}
QLabel[small="true"] {{ font-size: 8.5pt; }}
QLabel#Empty {{ color: #5d738f; padding: 24px; }}
QLabel#FieldLabel {{ color: #8ba3c0; font-size: 8.5pt; letter-spacing: 1px; }}
QFrame#Hud {{
    background: rgba(8,15,28,0.92); border: 1px solid {LINE_STRONG}; border-radius: 6px;
}}

/* ---------------- Buttons ---------------- */
QPushButton {{
    background: rgba(0,229,255,0.06); border: 1px solid {LINE_STRONG}; border-radius: 4px;
    padding: 6px 14px; color: #dceaf7;
}}
QPushButton:hover {{ background: rgba(0,229,255,0.14); border-color: #00e5ff; }}
QPushButton:pressed {{ background: rgba(0,229,255,0.22); }}
QPushButton:disabled {{ color: #5d738f; border-color: {LINE_MUTED}; background: transparent; }}
QPushButton[kind="primary"] {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00c8e0, stop:1 #00e5ff);
    color: #031018; border: 1px solid #00e5ff; font-weight: 600;
}}
QPushButton[kind="primary"]:hover {{ background: #4df0ff; }}
QPushButton[kind="primary"]:disabled {{ background: rgba(0,229,255,0.25); color: #0b2430; }}
QPushButton[kind="ghost"] {{ background: transparent; border: 1px solid {LINE_MUTED}; color: #8ba3c0; }}
QPushButton[kind="ghost"]:hover {{ color: #00e5ff; border-color: {LINE_STRONG}; }}
QPushButton[kind="danger"] {{
    background: rgba(255,77,109,0.08); border: 1px solid rgba(255,77,109,0.5); color: #ff4d6d;
}}
QPushButton[kind="danger"]:hover {{ background: rgba(255,77,109,0.18); }}
QPushButton[kind="link"] {{
    background: transparent; border: none; color: #00e5ff; padding: 0; font-family: "{MONO_FAMILY}";
    text-decoration: underline;
}}
QPushButton[size="sm"] {{ padding: 3px 8px; font-size: 9pt; }}
QPushButton[mode="true"] {{ border-radius: 0; }}
QPushButton[mode="true"]:checked {{ background: rgba(0,229,255,0.2); color: #00e5ff; border-color: #00e5ff; }}
QToolButton {{ background: transparent; border: 1px solid {LINE_MUTED}; border-radius: 3px; padding: 2px 5px; }}
QToolButton:hover {{ border-color: #00e5ff; color: #00e5ff; }}

/* ---------------- Inputs ---------------- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QDateTimeEdit, QTextEdit, QPlainTextEdit {{
    background: {BG_INPUT}; border: 1px solid rgba(148,178,214,0.22); border-radius: 4px;
    padding: 5px 8px; selection-background-color: rgba(0,229,255,0.35);
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus,
QDateTimeEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{ border-color: #00e5ff; }}
QLineEdit:disabled, QComboBox:disabled {{ color: #5d738f; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow, QDateEdit::down-arrow, QDateTimeEdit::down-arrow {{
    image: url("__ARROW__"); width: 10px; height: 6px; margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background: {BG_ELEVATED}; border: 1px solid {LINE_STRONG}; selection-background-color: rgba(0,229,255,0.25);
    outline: none;
}}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
QDateEdit::up-button, QDateEdit::down-button, QDateTimeEdit::up-button, QDateTimeEdit::down-button {{
    width: 0; border: none;
}}
QDateEdit::drop-down, QDateTimeEdit::drop-down {{ border: none; width: 22px; }}
QCalendarWidget QWidget {{ background: {BG_ELEVATED}; }}
QCalendarWidget QAbstractItemView:enabled {{ selection-background-color: rgba(0,229,255,0.35); }}
QCheckBox {{ spacing: 7px; }}
QCheckBox::indicator {{
    width: 14px; height: 14px; border: 1px solid {LINE_STRONG}; border-radius: 3px; background: {BG_INPUT};
}}
QCheckBox::indicator:checked {{ background: #00e5ff; border-color: #00e5ff; }}

/* ---------------- Tables ---------------- */
QTableWidget, QTableView, QListWidget, QTreeWidget {{
    background: transparent; border: none; gridline-color: {LINE_MUTED}; outline: none;
    alternate-background-color: rgba(255,255,255,0.015);
}}
QTableWidget::item, QTableView::item {{ border-bottom: 1px solid {LINE_MUTED}; padding: 4px 8px; }}
QTableWidget::item:selected, QTableView::item:selected, QListWidget::item:selected, QTreeWidget::item:selected {{
    background: rgba(0,229,255,0.12); color: #dceaf7;
}}
QTableWidget::item:hover, QListWidget::item:hover {{ background: rgba(0,229,255,0.06); }}
QHeaderView::section {{
    background: rgba(0,229,255,0.04); color: #8ba3c0; border: none; border-bottom: 1px solid {LINE};
    padding: 7px 8px; font-size: 8.5pt; letter-spacing: 1px;
}}
QTableCornerButton::section {{ background: transparent; border: none; }}

/* ---------------- Scrollbars ---------------- */
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: rgba(0,229,255,0.22); border-radius: 4px; min-height: 30px; margin: 2px; }}
QScrollBar::handle:vertical:hover {{ background: rgba(0,229,255,0.4); }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: rgba(0,229,255,0.22); border-radius: 4px; min-width: 30px; margin: 2px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------------- Progress ---------------- */
QProgressBar {{
    background: rgba(148,178,214,0.12); border: none; border-radius: 3px; max-height: 6px; text-align: center;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0891a3, stop:1 #00e5ff); border-radius: 3px;
}}

/* ---------------- Dialogs ---------------- */
QDialog {{ border: 1px solid {LINE_STRONG}; }}
QMessageBox {{ background: {BG_PANEL}; }}
QMessageBox QLabel {{ color: #dceaf7; }}
QSplitter::handle {{ background: {LINE_MUTED}; }}
QMenu {{ background: {BG_ELEVATED}; border: 1px solid {LINE_STRONG}; }}
QMenu::item:selected {{ background: rgba(0,229,255,0.18); }}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    font = QFont(FONT_FAMILY, 10)
    app.setFont(font)
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(BG_ROOT))
    pal.setColor(QPalette.WindowText, QColor("#dceaf7"))
    pal.setColor(QPalette.Base, QColor(BG_INPUT))
    pal.setColor(QPalette.AlternateBase, QColor(BG_PANEL))
    pal.setColor(QPalette.Text, QColor("#dceaf7"))
    pal.setColor(QPalette.Button, QColor(BG_PANEL))
    pal.setColor(QPalette.ButtonText, QColor("#dceaf7"))
    pal.setColor(QPalette.Highlight, QColor(0, 229, 255, 45))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ToolTipBase, QColor(BG_ELEVATED))
    pal.setColor(QPalette.ToolTipText, QColor("#dceaf7"))
    pal.setColor(QPalette.PlaceholderText, QColor("#5d738f"))
    app.setPalette(pal)
    app.setStyleSheet(QSS.replace("__ARROW__", _arrow_icon()))


def _arrow_icon() -> str:
    """QSS 無法用邊框畫三角形,執行時產生下拉箭頭圖檔。"""
    from PyQt5.QtCore import QPointF, Qt
    from PyQt5.QtGui import QPainter, QPixmap, QPolygonF

    from .config import data_dir

    path = data_dir() / "arrow_down.png"
    if not path.exists():
        pm = QPixmap(20, 12)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#00e5ff"))
        p.drawPolygon(QPolygonF([QPointF(1, 1), QPointF(19, 1), QPointF(10, 11)]))
        p.end()
        pm.save(str(path), "PNG")
    return path.as_posix()
