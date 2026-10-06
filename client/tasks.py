"""
在背景執行緒呼叫 API,完成後回到 GUI 執行緒執行 callback。

    run_async(lambda: api.drones(page=1), on_ok=self._render, on_err=self._fail, owner=self)

owner 被銷毀 (例如頁面已關閉) 時 callback 會自動略過,避免存取已刪除的 Qt 物件。
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from PyQt5 import sip
from PyQt5.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

log = logging.getLogger("drone.tasks")

_pool = QThreadPool.globalInstance()
_pool.setMaxThreadCount(8)
_alive: set[_Signals] = set()


class _Signals(QObject):
    done = pyqtSignal(object)
    failed = pyqtSignal(object)


class _Job(QRunnable):
    def __init__(self, fn: Callable[[], Any], signals: _Signals):
        super().__init__()
        self.fn = fn
        self.signals = signals

    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as exc:  # noqa: BLE001 - 交給 on_err 決定如何呈現
            self.signals.failed.emit(exc)
        else:
            self.signals.done.emit(result)


def _owner_alive(owner: QObject | None) -> bool:
    return owner is None or not sip.isdeleted(owner)


def run_async(fn: Callable[[], Any], on_ok: Callable[[Any], None] | None = None,
              on_err: Callable[[Exception], None] | None = None, owner: QObject | None = None) -> None:
    signals = _Signals()
    _alive.add(signals)

    def ok(result):
        _alive.discard(signals)
        if on_ok and _owner_alive(owner):
            on_ok(result)

    def err(exc):
        _alive.discard(signals)
        if not _owner_alive(owner):
            return
        if on_err:
            on_err(exc)
        else:
            log.warning("背景工作失敗:%s", exc)

    signals.done.connect(ok)
    signals.failed.connect(err)
    _pool.start(_Job(fn, signals))
