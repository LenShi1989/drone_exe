"""
即時推播 (取代原版 SignalR)。

客戶端連 ws://<host>:<port>/ws/telemetry?access_token=<JWT>,
伺服器推送 JSON 訊息:{"type": "<事件>", "data": <payload>}

  TelemetryUpdate       TelemetrySnapshot[]   每秒一次全機隊快照
  WorkOrderChanged      {workOrderId, orderNo, status, progressPercent}
  NotificationReceived  NotificationDto
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any

from fastapi import WebSocket
from fastapi.encoders import jsonable_encoder

log = logging.getLogger("drone.realtime")


class LiveTelemetryStore:
    """模擬器產生的最新一筆遙測快取,供 /drones/live 立即回應。"""

    def __init__(self) -> None:
        self._latest: dict[int, Any] = {}
        self._lock = threading.Lock()

    def update_all(self, snapshots: list) -> None:
        with self._lock:
            for s in snapshots:
                self._latest[s.drone_id] = s

    def get_all(self) -> list:
        with self._lock:
            return [self._latest[k] for k in sorted(self._latest)]

    def remove(self, drone_id: int) -> None:
        with self._lock:
            self._latest.pop(drone_id, None)


class TelemetryHub:
    """WebSocket 連線管理。可從任意執行緒呼叫 publish(),會轉送到主事件迴圈。"""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    async def _broadcast(self, text: str) -> None:
        dead = []
        for ws in list(self._clients):
            try:
                await ws.send_text(text)
            except Exception:  # noqa: BLE001 - 斷線的連線直接移除
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    def publish(self, event: str, data: Any) -> None:
        if self._loop is None or not self._clients:
            return
        payload = jsonable_encoder(data, by_alias=True)
        text = json.dumps({"type": event, "data": payload}, ensure_ascii=False)
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            self._loop.create_task(self._broadcast(text))
        else:
            asyncio.run_coroutine_threadsafe(self._broadcast(text), self._loop)


live_store = LiveTelemetryStore()
hub = TelemetryHub()
