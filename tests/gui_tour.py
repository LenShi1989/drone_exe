"""
GUI 巡覽測試:登入後依序開啟每個功能頁並截圖,檢查畫面是否正常載入。

    python tests/gui_tour.py --server http://localhost:5080 --out screenshots [--offscreen]
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://localhost:5080")
    ap.add_argument("--out", default="screenshots")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="Admin@123")
    ap.add_argument("--offscreen", action="store_true", help="Qt offscreen 平台 (Windows 上無字型,僅供 CI)")
    ap.add_argument("--park", action="store_true", help="視窗移到可見桌面之外,避免干擾操作")
    ap.add_argument("--wait", type=float, default=3.0, help="每頁等待秒數")
    ap.add_argument("--only", nargs="*", help="只截這些路徑")
    args = ap.parse_args()

    os.environ["DRONE_SERVER_URL"] = args.server
    os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")
    if args.offscreen:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"

    from PyQt5.QtCore import QEventLoop, Qt, QTimer
    from PyQt5.QtWidgets import QApplication

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv)
    from client.api import api
    from client.theme import apply_theme
    from client.views.login import LoginWindow
    from client.views.main_window import ROUTES, MainWindow

    apply_theme(app)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []

    def pump(seconds: float):
        loop = QEventLoop()
        QTimer.singleShot(int(seconds * 1000), loop.quit)
        loop.exec_()

    login = LoginWindow()
    login.resize(1100, 720)
    if args.park:
        login.move(-6000, 0)
    login.show()
    pump(0.5)
    login.grab().save(str(out / "00_login.png"))
    login.close()

    api.login(args.user, args.password)
    win = MainWindow(api.menu())
    win.resize(1600, 1000)
    if args.park:
        win.move(-6000, 0)
    win.show()
    pump(1.5)

    for i, path in enumerate(ROUTES, start=1):
        if args.only and path not in args.only:
            continue
        if path not in win.allowed:
            continue
        t0 = time.time()
        try:
            win.navigate(path)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{path}: {exc}")
            continue
        win.grab()  # 視窗在可見桌面外時不會收到 paint 事件,先渲染一次觸發地圖圖磚載入
        pump(args.wait)
        name = f"{i:02d}_{path.strip('/').replace('/', '_')}.png"
        win.grab().save(str(out / name))
        print(f"{path:<24} {time.time() - t0:5.1f}s → {name}")

    win.toggle_sidebar()
    pump(0.5)
    win.grab().save(str(out / "99_sidebar_collapsed.png"))
    win.close()
    print("錯誤:" + "; ".join(errors) if errors else "完成,無例外")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
