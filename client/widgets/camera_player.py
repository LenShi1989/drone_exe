"""
攝影機即時影像 (取代原版 Python OpenCV 串流閘道 + 瀏覽器 <img>)。

桌面版直接在用戶端以 OpenCV 拉流 (RTSP / HTTP MJPEG),不需另外架設閘道服務。
每一路影像在獨立 QThread 讀取,轉成 QImage 後送回 GUI 執行緒顯示。
"""
from __future__ import annotations

import time

from PyQt5.QtCore import QRectF, Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor, QImage, QPainter, QPen
from PyQt5.QtWidgets import QWidget

try:
    import cv2  # type: ignore
except ImportError:  # pragma: no cover - 未安裝 OpenCV 時改顯示提示
    cv2 = None


# VideoCapture 連線逾時可能長達數十秒;停止時若執行緒還卡著,先放這裡等它自行結束再釋放
_orphans: set["StreamWorker"] = set()


class StreamWorker(QThread):
    frameReady = pyqtSignal(QImage)
    statusChanged = pyqtSignal(str)

    def __init__(self, url: str):
        super().__init__()
        self.url = url
        self._running = True

    def stop(self) -> None:
        self._running = False
        if self.wait(1500):
            self.deleteLater()
            return
        _orphans.add(self)
        self.finished.connect(lambda: (_orphans.discard(self), self.deleteLater()))

    def run(self):
        if cv2 is None:
            self.statusChanged.emit("未安裝 OpenCV,無法播放")
            return
        while self._running:
            self.statusChanged.emit("連線中…")
            cap = cv2.VideoCapture(self.url)
            if not cap.isOpened():
                cap.release()
                self.statusChanged.emit("無法連線,5 秒後重試")
                for _ in range(50):
                    if not self._running:
                        return
                    time.sleep(0.1)
                continue
            self.statusChanged.emit("")
            fails = 0
            last = 0.0
            while self._running:
                ok, frame = cap.read()
                if not ok:
                    fails += 1
                    if fails > 30:
                        break
                    time.sleep(0.05)
                    continue
                fails = 0
                now = time.monotonic()
                if now - last < 1 / 20:  # 最多 20 fps 送畫面,降低 GUI 負擔
                    continue
                last = now
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, _ = rgb.shape
                img = QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888).copy()
                self.frameReady.emit(img)
            cap.release()
            if self._running:
                self.statusChanged.emit("串流中斷,重新連線…")


class CameraView(QWidget):
    """顯示單路影像;stop() 會結束背景執行緒。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 180)
        self._image: QImage | None = None
        self._status = "未播放"
        self._worker: StreamWorker | None = None

    @property
    def playing(self) -> bool:
        return self._worker is not None

    def play(self, url: str):
        self.stop()
        self._image = None
        self._status = "連線中…"
        self._worker = StreamWorker(url)
        self._worker.frameReady.connect(self._on_frame)
        self._worker.statusChanged.connect(self._on_status)
        self._worker.start()
        self.update()

    def stop(self):
        if self._worker:
            w = self._worker
            self._worker = None
            w.frameReady.disconnect()
            w.statusChanged.disconnect()
            w.stop()
        self._status = "已停止"
        self.update()

    def snapshot(self) -> QImage | None:
        return self._image

    def _on_frame(self, img: QImage):
        self._image = img
        self.update()

    def _on_status(self, text: str):
        self._status = text
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#03070f"))
        if self._image is not None:
            scaled = self._image.size().scaled(self.size(), Qt.KeepAspectRatio)
            x = (self.width() - scaled.width()) / 2
            y = (self.height() - scaled.height()) / 2
            p.drawImage(QRectF(x, y, scaled.width(), scaled.height()), self._image)
        else:
            # 無畫面時的掃描線背景
            p.setPen(QPen(QColor(0, 229, 255, 14)))
            for y in range(0, self.height(), 4):
                p.drawLine(0, y, self.width(), y)
        if self._status:
            p.setPen(QColor("#8ba3c0"))
            p.drawText(self.rect(), Qt.AlignCenter, self._status)
        p.setPen(QPen(QColor(0, 229, 255, 70)))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        p.end()

    def closeEvent(self, e):
        self.stop()
        super().closeEvent(e)
