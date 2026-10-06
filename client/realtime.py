"""
即時遙測 (WebSocket)。單一連線由整個 App 共用,各頁面訂閱 telemetry 的 signal 即可。
斷線會自動以 1 / 2 / 5 / 10 / 20 秒間隔重連;連不上時改以 REST 拉一次快照讓畫面有資料。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from PyQt5.QtCore import QObject, QTimer, QUrl, pyqtSignal
from PyQt5.QtNetwork import QAbstractSocket
from PyQt5.QtWebSockets import QWebSocket

from .api import api
from .config import settings
from .fmt import DroneStatus
from .tasks import run_async

log = logging.getLogger("drone.realtime")

_RECONNECT_DELAYS = [1000, 2000, 5000, 10000, 20000]
_TRAIL_MAX = 240


class TelemetryClient(QObject):
    snapshotsChanged = pyqtSignal()
    connectedChanged = pyqtSignal(bool)
    notificationReceived = pyqtSignal(dict)
    workOrderChanged = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.snapshots: list[dict] = []
        self.by_id: dict[int, dict] = {}
        self.trails: dict[int, list[tuple[float, float]]] = {}
        self.connected = False
        self.last_updated: datetime | None = None
        self._ws: QWebSocket | None = None
        self._active = False
        self._attempt = 0
        self._reconnect = QTimer(self, singleShot=True, timeout=self._open)
        self._ping = QTimer(self, interval=25000, timeout=self._send_ping)

    # ------------------------------------------------------------------ 狀態

    @property
    def flying(self) -> list[dict]:
        return [s for s in self.snapshots if s["status"] in (DroneStatus.Flying, DroneStatus.Returning)]

    def _set_connected(self, value: bool) -> None:
        if self.connected != value:
            self.connected = value
            self.connectedChanged.emit(value)

    def _apply(self, items: list[dict]) -> None:
        self.snapshots = items
        self.by_id = {s["droneId"]: s for s in items}
        self.last_updated = datetime.now()
        for s in items:
            did = s["droneId"]
            if s["status"] not in (DroneStatus.Flying, DroneStatus.Returning):
                self.trails.pop(did, None)
                continue
            trail = self.trails.setdefault(did, [])
            point = (s["latitude"], s["longitude"])
            if not trail or trail[-1] != point:
                trail.append(point)
                if len(trail) > _TRAIL_MAX:
                    del trail[0]
        self.snapshotsChanged.emit()

    def load_once(self) -> None:
        """WebSocket 不可用時以 REST 拉一次,讓畫面有資料。"""
        if not api.can("monitor.view"):
            return
        run_async(api.drones_live, self._apply, lambda e: None, owner=self)

    # ------------------------------------------------------------------ 連線

    def start(self) -> None:
        if self._active:
            return
        self._active = True
        self._attempt = 0
        self._open()

    def stop(self) -> None:
        self._active = False
        self._reconnect.stop()
        self._ping.stop()
        if self._ws:
            self._ws.abort()
            self._ws.deleteLater()
            self._ws = None
        self._set_connected(False)
        self.snapshots, self.by_id, self.trails = [], {}, {}
        self.snapshotsChanged.emit()

    def _open(self) -> None:
        if not self._active or not api.access_token:
            return
        if self._ws:
            self._ws.abort()
            self._ws.deleteLater()
        ws = QWebSocket()
        ws.connected.connect(self._on_connected)
        ws.disconnected.connect(self._on_disconnected)
        ws.textMessageReceived.connect(self._on_message)
        ws.error.connect(self._on_error)
        self._ws = ws
        url = QUrl(settings.ws_url)
        url.setQuery(f"access_token={api.access_token}")
        ws.open(url)

    def _on_connected(self) -> None:
        self._attempt = 0
        self._set_connected(True)
        self._ping.start()

    def _on_error(self, _err: QAbstractSocket.SocketError) -> None:
        log.debug("WebSocket 錯誤:%s", self._ws.errorString() if self._ws else "")

    def _on_disconnected(self) -> None:
        self._ping.stop()
        was_connected = self.connected
        self._set_connected(False)
        if not self._active:
            return
        if not was_connected and self._attempt == 0:
            self.load_once()
        delay = _RECONNECT_DELAYS[min(self._attempt, len(_RECONNECT_DELAYS) - 1)]
        self._attempt += 1
        self._reconnect.start(delay)

    def _send_ping(self) -> None:
        if self._ws and self.connected:
            self._ws.sendTextMessage("ping")

    def _on_message(self, text: str) -> None:
        try:
            msg = json.loads(text)
        except ValueError:
            return
        kind, data = msg.get("type"), msg.get("data")
        if kind == "TelemetryUpdate":
            self._apply(data or [])
        elif kind == "NotificationReceived":
            self.notificationReceived.emit(data or {})
        elif kind == "WorkOrderChanged":
            self.workOrderChanged.emit(data or {})


telemetry = TelemetryClient()
