"""
對話框截圖測試:開啟各頁的新增 / 編輯 / 排程 / 明細對話框並截圖。

    python tests/gui_dialogs.py --server http://localhost:5080 --out screenshots
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://localhost:5080")
    ap.add_argument("--out", default="screenshots")
    args = ap.parse_args()
    os.environ["DRONE_SERVER_URL"] = args.server
    os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")

    from PyQt5.QtCore import QEventLoop, Qt, QTimer
    from PyQt5.QtWidgets import QApplication

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv)
    from client.api import api
    from client.theme import apply_theme
    from client.views.main_window import MainWindow
    from client.widgets import common

    apply_theme(app)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    opened: list = []

    def fake_exec(self):  # 改為非模態,才能在程式中截圖後關閉
        self.move(-6000, 0)
        self.show()
        opened.append(self)
        return 0

    common.FormDialog.exec_ = fake_exec

    def pump(seconds: float):
        loop = QEventLoop()
        QTimer.singleShot(int(seconds * 1000), loop.quit)
        loop.exec_()

    api.login("admin", "Admin@123")
    win = MainWindow(api.menu())
    win.resize(1600, 1000)
    win.move(-6000, 0)
    win.show()

    def shot(name: str, open_fn):
        opened.clear()
        open_fn()
        pump(1.8)
        for i, dlg in enumerate(opened):
            dlg.adjustSize()
            pump(0.2)
            dlg.grab().save(str(out / f"dlg_{name}{'' if i == 0 else i}.png"))
            dlg.close()
        print(f"{name}: {len(opened)} 個對話框")

    def page(path):
        win.navigate(path)
        win.grab()
        pump(2.5)
        return win.pages[path]

    p = page("/drone/settings")
    shot("drone_edit", lambda: p.open_edit(p.rows[0]))
    shot("drone_sim", p.open_sim_create)
    p = page("/map/editor")
    shot("map_point", lambda: p.edit_point(p.points[0]))
    p = page("/workorder/current")
    shot("wo_create", lambda: p.open_edit(None))
    pending = [o for o in p.rows if o["status"] == 0]
    if pending:
        shot("wo_schedule", lambda: p.open_schedule(pending[0]))
    from client.views.workorders import open_detail
    hist = page("/workorder/history")
    shot("wo_detail", lambda: open_detail(hist, hist.rows[0]["id"]))
    p = page("/workorder/templates")
    shot("template", lambda: p.open_edit(p.templates[0]))
    p = page("/cameras")
    shot("camera", lambda: p.open_edit(p.cameras[0]))
    p = page("/system/users")
    shot("user", lambda: p.open_edit(p.rows[1]))
    p = page("/system/roles")
    shot("role", lambda: p.open_edit(p.roles[1]))
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
