"""
原生 Qt 地圖元件 (取代原版 GeoMap.vue + Google Maps)。

- 底圖:OpenStreetMap 圖磚 (可於 client.ini 改來源),套深色濾鏡維持科技風,
  圖磚存在本機磁碟快取;無網路或 [map] online=false 時退回網格底圖,點位/航線/航跡照常顯示。
- 圖層:點位 / 無人機 (依航向旋轉) / 航線 (實線或虛線) / 航跡。
- 互動:拖曳平移、滾輪縮放、點擊地圖 (mapClicked)、點擊標記 (markerClicked)、拖曳可拖動的標記 (markerDragged)。

OSM 圖磚使用條款要求標示「© OpenStreetMap contributors」,請勿移除左下角標示。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from PyQt5.QtCore import QObject, QPointF, QRectF, QSize, Qt, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import (
    QBrush, QColor, QFont, QImage, QPainter, QPen, QPixmap, QPolygonF,
)
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkDiskCache, QNetworkReply, QNetworkRequest
from PyQt5.QtWidgets import QToolButton, QWidget

from ..config import data_dir, settings
from ..theme import MONO_FAMILY

TILE = 256
MIN_ZOOM, MAX_ZOOM = 3, 19
MAX_LAT = 85.05112878


# ============================================================ 座標換算 (Web Mercator)

def to_world(lat: float, lng: float, zoom: int) -> tuple[float, float]:
    scale = TILE * (1 << zoom)
    lat = max(-MAX_LAT, min(MAX_LAT, lat))
    x = (lng + 180.0) / 360.0 * scale
    s = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * scale
    return x, y


def from_world(x: float, y: float, zoom: int) -> tuple[float, float]:
    scale = TILE * (1 << zoom)
    lng = x / scale * 360.0 - 180.0
    n = math.pi - 2 * math.pi * y / scale
    lat = math.degrees(math.atan(math.sinh(n)))
    return lat, lng


# ============================================================ 資料模型

@dataclass
class GeoMarker:
    id: str
    lat: float
    lng: float
    color: str = "#00e5ff"
    label: str = ""
    kind: str = "point"  # point | drone
    heading: float = 0.0
    draggable: bool = False


@dataclass
class GeoLine:
    id: str
    points: list[tuple[float, float]] = field(default_factory=list)
    color: str = "#00e5ff"
    width: float = 2.5
    dashed: bool = False


# ============================================================ 圖磚快取 (全 App 共用)

class TileProvider(QObject):
    tileLoaded = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.online = settings.map_online
        self._mem: dict[tuple[int, int, int], QPixmap] = {}
        self._order: list[tuple[int, int, int]] = []
        self._pending: set[tuple[int, int, int]] = set()
        self._failed: dict[tuple[int, int, int], int] = {}
        self._fail_streak = 0
        self.net = QNetworkAccessManager(self)
        cache = QNetworkDiskCache(self)
        cache.setCacheDirectory(str(data_dir() / "tiles"))
        cache.setMaximumCacheSize(300 * 1024 * 1024)
        self.net.setCache(cache)
        self.net.finished.connect(self._on_finished)
        self._emit_timer = QTimer(self, singleShot=True, interval=60, timeout=self.tileLoaded.emit)

    @property
    def degraded(self) -> bool:
        """連續失敗太多次 (多半是離線),改顯示網格底圖。"""
        return not self.online or self._fail_streak >= 12

    def get(self, z: int, x: int, y: int) -> QPixmap | None:
        key = (z, x, y)
        pm = self._mem.get(key)
        if pm is not None:
            return pm
        if self.online and key not in self._pending and self._failed.get(key, 0) < 2 and len(self._pending) < 24:
            self._request(key)
        return None

    def _request(self, key):
        z, x, y = key
        url = settings.tile_url.format(z=z, x=x, y=y, s="abc"[(x + y) % 3])
        req = QNetworkRequest(QUrl(url))
        req.setRawHeader(b"User-Agent", b"DroneOpsCenter/1.0 (PyQt5 desktop client)")
        req.setAttribute(QNetworkRequest.CacheLoadControlAttribute, QNetworkRequest.PreferCache)
        req.setAttribute(QNetworkRequest.User, key)
        self._pending.add(key)
        self.net.get(req)

    def _on_finished(self, reply: QNetworkReply):
        key = reply.request().attribute(QNetworkRequest.User)
        self._pending.discard(key)
        if reply.error() == QNetworkReply.NoError:
            img = QImage()
            if img.loadFromData(bytes(reply.readAll())):
                self._store(key, self._darken(img))
                self._fail_streak = 0
                self._emit_timer.start()
            else:
                self._failed[key] = self._failed.get(key, 0) + 1
        else:
            self._failed[key] = self._failed.get(key, 0) + 1
            self._fail_streak += 1
            if self._fail_streak == 12:
                self._emit_timer.start()
        reply.deleteLater()

    def _store(self, key, pm: QPixmap):
        self._mem[key] = pm
        self._order.append(key)
        if len(self._order) > 600:
            old = self._order.pop(0)
            self._mem.pop(old, None)

    @staticmethod
    def _darken(img: QImage) -> QPixmap:
        """亮色圖磚 → 深色科技風:灰階反相後染成藍青色調。"""
        gray = img.convertToFormat(QImage.Format_Grayscale8)
        gray.invertPixels()
        out = QPixmap(TILE, TILE)
        out.fill(QColor("#060b16"))
        p = QPainter(out)
        p.drawImage(QRectF(0, 0, TILE, TILE), gray)
        p.setCompositionMode(QPainter.CompositionMode_Multiply)
        p.fillRect(QRectF(0, 0, TILE, TILE), QColor(110, 175, 235))
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        p.fillRect(QRectF(0, 0, TILE, TILE), QColor(4, 10, 22, 70))
        p.end()
        return out


_provider: TileProvider | None = None


def tile_provider() -> TileProvider:
    global _provider
    if _provider is None:
        _provider = TileProvider()
    return _provider


# ============================================================ 地圖元件

class MapWidget(QWidget):
    mapClicked = pyqtSignal(float, float)
    markerClicked = pyqtSignal(str)
    markerDragged = pyqtSignal(str, float, float)

    def __init__(self, parent=None, *, clickable: bool = False, auto_fit: bool = True, min_height: int = 360):
        super().__init__(parent)
        self.setMinimumHeight(min_height)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.clickable = clickable
        self.auto_fit = auto_fit
        self.markers: list[GeoMarker] = []
        self.lines: list[GeoLine] = []
        self.zoom = 16
        self.center = (settings.center_lat, settings.center_lng)
        self._fitted = False
        self._press_pos: QPointF | None = None
        self._press_center: tuple[float, float] | None = None
        self._dragging_marker: GeoMarker | None = None
        self._moved = False
        self._hover_marker: str | None = None
        self._overlays: list[tuple[QWidget, str]] = []
        self.tiles = tile_provider()
        self.tiles.tileLoaded.connect(self.update)
        self._build_controls()
        self.setCursor(Qt.OpenHandCursor)

    # ------------------------------------------------------------------ 公開 API

    def set_data(self, markers: list[GeoMarker] | None = None, lines: list[GeoLine] | None = None,
                 fit: bool = False) -> None:
        if markers is not None:
            if self._dragging_marker is not None:
                # 拖曳中不要被外部重繪覆蓋位置
                keep = {self._dragging_marker.id: self._dragging_marker}
                markers = [keep.get(m.id, m) for m in markers]
            self.markers = markers
        if lines is not None:
            self.lines = lines
        if fit or (self.auto_fit and not self._fitted and self._has_content()):
            self.fit()
        self.update()

    def fit(self) -> None:
        pts = [(m.lat, m.lng) for m in self.markers] + [p for ln in self.lines for p in ln.points]
        if not pts:
            return
        self._fitted = True
        lats = [p[0] for p in pts]
        lngs = [p[1] for p in pts]
        self.center = ((min(lats) + max(lats)) / 2, (min(lngs) + max(lngs)) / 2)
        if len(pts) == 1 or (max(lats) - min(lats) < 1e-6 and max(lngs) - min(lngs) < 1e-6):
            self.zoom = 17
            self.update()
            return
        pad = 70
        w, h = max(100, self.width() - pad * 2), max(100, self.height() - pad * 2)
        zoom = MAX_ZOOM - 1
        while zoom > MIN_ZOOM:
            x1, y1 = to_world(max(lats), min(lngs), zoom)
            x2, y2 = to_world(min(lats), max(lngs), zoom)
            if abs(x2 - x1) <= w and abs(y2 - y1) <= h:
                break
            zoom -= 1
        self.zoom = zoom
        self.update()

    def add_overlay(self, widget: QWidget, corner: str = "tl") -> None:
        widget.setParent(self)
        self._overlays.append((widget, corner))
        widget.show()
        self._place_overlays()

    def _has_content(self) -> bool:
        return bool(self.markers) or any(ln.points for ln in self.lines)

    # ------------------------------------------------------------------ 控制鈕

    def _build_controls(self):
        self._btns = []
        for text, tip, fn in (("+", "放大", lambda: self._zoom_at(1, None)),
                              ("−", "縮小", lambda: self._zoom_at(-1, None)),
                              ("⌖", "顯示全部", self.fit)):
            b = QToolButton(self)
            b.setText(text)
            b.setToolTip(tip)
            b.setFixedSize(30, 30)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet("QToolButton{background:rgba(8,15,28,0.9);border:1px solid rgba(0,229,255,0.38);"
                            "border-radius:4px;color:#00e5ff;font-size:13pt;font-weight:600}"
                            "QToolButton:hover{background:rgba(0,229,255,0.18)}")
            b.clicked.connect(fn)
            self._btns.append(b)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        for i, b in enumerate(self._btns):
            b.move(self.width() - 42, 12 + i * 36)
        self._place_overlays()
        if self.auto_fit and not self._fitted and self._has_content():
            self.fit()

    def _place_overlays(self):
        for w, corner in self._overlays:
            w.adjustSize()
            if corner == "tr":
                w.move(self.width() - w.width() - 54, 12)
            elif corner == "bl":
                w.move(12, self.height() - w.height() - 26)
            else:
                w.move(12, 12)
            w.raise_()

    def sizeHint(self) -> QSize:
        return QSize(800, 520)

    # ------------------------------------------------------------------ 座標

    def _center_world(self) -> tuple[float, float]:
        return to_world(self.center[0], self.center[1], self.zoom)

    def latlng_to_screen(self, lat: float, lng: float) -> QPointF:
        cx, cy = self._center_world()
        x, y = to_world(lat, lng, self.zoom)
        return QPointF(x - cx + self.width() / 2, y - cy + self.height() / 2)

    def screen_to_latlng(self, pos: QPointF) -> tuple[float, float]:
        cx, cy = self._center_world()
        return from_world(cx + pos.x() - self.width() / 2, cy + pos.y() - self.height() / 2, self.zoom)

    # ------------------------------------------------------------------ 繪圖

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#071224"))
        self._draw_tiles(p)
        self._draw_grid(p)
        for ln in self.lines:
            self._draw_line(p, ln)
        for m in self.markers:
            if m.kind != "drone":
                self._draw_point(p, m)
        for m in self.markers:
            if m.kind == "drone":
                self._draw_drone(p, m)
        self._draw_frame(p)
        p.end()

    def _draw_tiles(self, p: QPainter):
        if self.tiles.degraded:
            return
        cx, cy = self._center_world()
        left, top = cx - self.width() / 2, cy - self.height() / 2
        n = 1 << self.zoom
        tx0, ty0 = int(math.floor(left / TILE)), int(math.floor(top / TILE))
        tx1, ty1 = int(math.floor((left + self.width()) / TILE)), int(math.floor((top + self.height()) / TILE))
        for ty in range(ty0, ty1 + 1):
            if ty < 0 or ty >= n:
                continue
            for tx in range(tx0, tx1 + 1):
                pm = self.tiles.get(self.zoom, tx % n, ty)
                if pm is not None:
                    p.drawPixmap(QPointF(tx * TILE - left, ty * TILE - top), pm)

    def _draw_grid(self, p: QPainter):
        """科技風網格;離線時兼作底圖。"""
        degraded = self.tiles.degraded
        step = 48
        pen = QPen(QColor(0, 229, 255, 26 if degraded else 10))
        pen.setWidth(1)
        p.setPen(pen)
        cx, cy = self._center_world()
        ox = -((cx - self.width() / 2) % step)
        oy = -((cy - self.height() / 2) % step)
        x = ox
        while x < self.width():
            p.drawLine(QPointF(x, 0), QPointF(x, self.height()))
            x += step
        y = oy
        while y < self.height():
            p.drawLine(QPointF(0, y), QPointF(self.width(), y))
            y += step

    def _draw_line(self, p: QPainter, ln: GeoLine):
        if len(ln.points) < 2:
            return
        poly = QPolygonF([self.latlng_to_screen(lat, lng) for lat, lng in ln.points])
        color = QColor(ln.color)
        glow = QColor(color)
        glow.setAlpha(55)
        p.setPen(QPen(glow, ln.width + 5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPolyline(poly)
        pen = QPen(color, ln.width, Qt.DashLine if ln.dashed else Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        if ln.dashed:
            pen.setDashPattern([4, 3])
        p.setPen(pen)
        p.drawPolyline(poly)

    def _draw_label(self, p: QPainter, pos: QPointF, text: str, color: QColor):
        if not text:
            return
        f = QFont(self.font())
        f.setPointSizeF(8.5)
        p.setFont(f)
        rect = p.fontMetrics().boundingRect(text)
        box = QRectF(pos.x() + 10, pos.y() - rect.height() / 2 - 3, rect.width() + 10, rect.height() + 6)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(6, 12, 24, 205))
        p.drawRoundedRect(box, 3, 3)
        p.setPen(color.lighter(115))
        p.drawText(box, Qt.AlignCenter, text)

    def _draw_point(self, p: QPainter, m: GeoMarker):
        pos = self.latlng_to_screen(m.lat, m.lng)
        if not self.rect().adjusted(-40, -40, 40, 40).contains(pos.toPoint()):
            return
        color = QColor(m.color)
        hover = self._hover_marker == m.id
        if m.label.startswith("#"):
            # 航點:圓圈內顯示序號
            r = 10 if not hover else 12
            glow = QColor(color)
            glow.setAlpha(60)
            p.setPen(Qt.NoPen)
            p.setBrush(glow)
            p.drawEllipse(pos, r + 5, r + 5)
            p.setBrush(QColor("#071224"))
            p.setPen(QPen(color, 2))
            p.drawEllipse(pos, r, r)
            f = QFont(MONO_FAMILY)
            f.setPointSizeF(8)
            f.setBold(True)
            p.setFont(f)
            p.setPen(color)
            p.drawText(QRectF(pos.x() - r, pos.y() - r, r * 2, r * 2), Qt.AlignCenter, m.label[1:])
            return
        r = 6 if not hover else 8
        glow = QColor(color)
        glow.setAlpha(70)
        p.setPen(Qt.NoPen)
        p.setBrush(glow)
        p.drawEllipse(pos, r + 5, r + 5)
        p.setBrush(color)
        p.setPen(QPen(QColor("#04101c"), 2))
        p.drawEllipse(pos, r, r)
        self._draw_label(p, pos, m.label, color)

    def _draw_drone(self, p: QPainter, m: GeoMarker):
        pos = self.latlng_to_screen(m.lat, m.lng)
        color = QColor(m.color)
        glow = QColor(color)
        glow.setAlpha(45)
        p.setPen(Qt.NoPen)
        p.setBrush(glow)
        p.drawEllipse(pos, 17, 17)
        p.save()
        p.translate(pos)
        p.rotate(m.heading)
        arrow = QPolygonF([QPointF(0, -13), QPointF(9, 10), QPointF(0, 5), QPointF(-9, 10)])
        p.setBrush(color)
        p.setPen(QPen(QColor("#04101c"), 1.5))
        p.drawPolygon(arrow)
        p.restore()
        if self._hover_marker == m.id:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(color, 1.5, Qt.DashLine))
            p.drawEllipse(pos, 21, 21)
        self._draw_label(p, pos + QPointF(8, 0), m.label, color)

    def _draw_frame(self, p: QPainter):
        # 左下角授權標示 / 離線提示
        f = QFont(self.font())
        f.setPointSizeF(7.5)
        p.setFont(f)
        text = "離線網格底圖 (無法取得圖磚)" if self.tiles.degraded else "© OpenStreetMap contributors"
        rect = QRectF(6, self.height() - 20, p.fontMetrics().width(text) + 12, 16)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(6, 12, 24, 190))
        p.drawRoundedRect(rect, 3, 3)
        p.setPen(QColor("#8ba3c0"))
        p.drawText(rect, Qt.AlignCenter, text)
        # 右下角比例/縮放
        zt = f"Z{self.zoom}  {self.center[0]:.5f}, {self.center[1]:.5f}"
        zr = QRectF(self.width() - p.fontMetrics().width(zt) - 18, self.height() - 20,
                    p.fontMetrics().width(zt) + 12, 16)
        p.setBrush(QColor(6, 12, 24, 190))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(zr, 3, 3)
        p.setPen(QColor("#5d738f"))
        p.drawText(zr, Qt.AlignCenter, zt)
        # 外框
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(0, 229, 255, 60), 1))
        p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 6, 6)

    # ------------------------------------------------------------------ 互動

    def _marker_at(self, pos: QPointF, draggable_only: bool = False) -> GeoMarker | None:
        best, best_d = None, 14.0
        for m in reversed(self.markers):
            if draggable_only and not m.draggable:
                continue
            sp = self.latlng_to_screen(m.lat, m.lng)
            d = math.hypot(sp.x() - pos.x(), sp.y() - pos.y())
            if d < best_d:
                best, best_d = m, d
        return best

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        self._press_pos = QPointF(e.pos())
        self._press_center = self._center_world()
        self._moved = False
        self._dragging_marker = self._marker_at(QPointF(e.pos()), draggable_only=True)
        self.setCursor(Qt.ClosedHandCursor if self._dragging_marker is None else Qt.SizeAllCursor)

    def mouseMoveEvent(self, e):
        pos = QPointF(e.pos())
        if self._press_pos is None:
            hit = self._marker_at(pos)
            new_hover = hit.id if hit else None
            if new_hover != self._hover_marker:
                self._hover_marker = new_hover
                self.setCursor(Qt.PointingHandCursor if hit else (Qt.CrossCursor if self.clickable
                                                                  else Qt.OpenHandCursor))
                self.update()
            return
        delta = pos - self._press_pos
        if not self._moved and math.hypot(delta.x(), delta.y()) < 4:
            return
        self._moved = True
        if self._dragging_marker is not None:
            lat, lng = self.screen_to_latlng(pos)
            self._dragging_marker.lat, self._dragging_marker.lng = lat, lng
        else:
            cx, cy = self._press_center
            self.center = from_world(cx - delta.x(), cy - delta.y(), self.zoom)
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or self._press_pos is None:
            return
        pos = QPointF(e.pos())
        dragged = self._dragging_marker
        self._press_pos = None
        self._dragging_marker = None
        self.setCursor(Qt.CrossCursor if self.clickable else Qt.OpenHandCursor)
        if self._moved:
            if dragged is not None:
                self.markerDragged.emit(dragged.id, dragged.lat, dragged.lng)
            return
        hit = self._marker_at(pos)
        if hit is not None:
            self.markerClicked.emit(hit.id)
            if not self.clickable or hit.kind == "drone":
                return
        if self.clickable:
            lat, lng = self.screen_to_latlng(pos)
            self.mapClicked.emit(lat, lng)

    def mouseDoubleClickEvent(self, e):
        if not self.clickable:
            self._zoom_at(1, QPointF(e.pos()))

    def wheelEvent(self, e):
        steps = 1 if e.angleDelta().y() > 0 else -1
        self._zoom_at(steps, QPointF(e.pos()))

    def _zoom_at(self, steps: int, pos: QPointF | None):
        new_zoom = max(MIN_ZOOM, min(MAX_ZOOM, self.zoom + steps))
        if new_zoom == self.zoom:
            return
        if pos is None:
            pos = QPointF(self.width() / 2, self.height() / 2)
        anchor = self.screen_to_latlng(pos)
        self.zoom = new_zoom
        ax, ay = to_world(anchor[0], anchor[1], self.zoom)
        self.center = from_world(ax - (pos.x() - self.width() / 2), ay - (pos.y() - self.height() / 2), self.zoom)
        self.update()

    def setClickable(self, value: bool) -> None:
        self.clickable = value
        self.setCursor(Qt.CrossCursor if value else Qt.OpenHandCursor)


def brush(color: str) -> QBrush:
    return QBrush(QColor(color))
