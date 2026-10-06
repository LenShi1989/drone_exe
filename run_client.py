"""
前端啟動入口 (開發:python run_client.py;打包後即 DroneClient.exe)。

連線的後端位址設定在執行檔旁的 client.ini ([server] url),
也可用環境變數 DRONE_SERVER_URL 臨時覆蓋。
"""
from __future__ import annotations

import logging
import os
import sys


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    # 150% 等非整數縮放時 Qt5 預設會四捨五入成 2 倍,畫面可用空間大減;改為照實縮放
    os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")

    from PyQt5.QtCore import QObject, Qt, pyqtSignal
    from PyQt5.QtWidgets import QApplication

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setApplicationName("Drone Ops Center")
    app.setOrganizationName("DroneOps")

    # QApplication 建立後才匯入介面模組 (部分模組在匯入時就會建立 QObject)
    from client.api import api
    from client.tasks import run_async
    from client.theme import apply_theme
    from client.views.login import LoginWindow
    from client.views.main_window import MainWindow
    from client.widgets.common import toast

    apply_theme(app)

    if "--selftest" in sys.argv:
        return _selftest()

    class Controller(QObject):
        sessionExpired = pyqtSignal()  # 由背景執行緒觸發,經 signal 回到 GUI 執行緒

        def __init__(self):
            super().__init__()
            self.login: LoginWindow | None = None
            self.main: MainWindow | None = None
            self.sessionExpired.connect(self._on_expired)
            api.on_session_expired = self.sessionExpired.emit

        def show_login(self):
            if self.main is not None:
                self.main.hide()
                self.main.deleteLater()
                self.main = None
            self.login = LoginWindow()
            self.login.loggedIn.connect(self._on_logged_in)
            self.login.show()

        def _on_logged_in(self):
            def ok(menu):
                self.main = MainWindow(menu)
                self.main.loggedOut.connect(self.show_login)
                self.main.showMaximized()
                if self.login is not None:
                    self.login.close()
                    self.login.deleteLater()
                    self.login = None

            def err(e):
                from client.api import error_message
                if self.login is not None:
                    self.login._show_error(error_message(e, "載入選單失敗"))

            run_async(api.menu, ok, err)

        def _on_expired(self):
            if self.main is not None:
                self.main.session_expired()
            else:
                toast("登入已逾時,請重新登入", "warn")

    controller = Controller()
    controller.show_login()
    code = app.exec_()
    # 攝影機串流執行緒可能卡在網路逾時,直接結束行程避免關閉時等待
    os._exit(code)


def _selftest() -> int:
    """部署檢查:載入所有頁面模組、畫一張圖表、確認 OpenCV,結果寫到執行檔旁的 selftest.txt。"""
    import importlib
    import traceback

    from client.config import app_dir

    lines = []
    ok = True
    try:
        for name in ("monitor", "map_editor", "map_history", "drones", "cameras", "workorders", "stats", "logs",
                     "system", "main_window"):
            importlib.import_module(f"client.views.{name}")
        lines.append("views: OK")
        from client.widgets.charts import ChartWidget, Series
        chart = ChartWidget(200)
        chart.category_chart(["a", "b"], [Series("x", [1, 2], "bar")])
        chart.grab()
        lines.append("matplotlib: OK")
        from client.widgets.camera_player import cv2
        lines.append(f"opencv: {cv2.__version__ if cv2 else 'MISSING'}")
        ok = cv2 is not None
    except Exception:  # noqa: BLE001
        ok = False
        lines.append(traceback.format_exc())
    lines.append("RESULT: " + ("PASS" if ok else "FAIL"))
    (app_dir() / "selftest.txt").write_text("\n".join(lines), encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
