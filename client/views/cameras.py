"""攝影機管理:為每台無人機掛載多路 IP 攝影機,以 OpenCV 直接播放 HTTP / RTSP 即時串流。"""
from __future__ import annotations

from datetime import datetime

from PyQt5.QtWidgets import QFileDialog, QFrame, QGridLayout, QWidget

from .. import fmt
from ..api import api, error_message
from ..config import data_dir
from ..tasks import run_async
from ..widgets.camera_player import CameraView, cv2
from ..widgets.common import (
    FormDialog, button, checkbox, clear_layout, combo, confirm, field, full, hbox, int_spin, label, line_edit, tag,
    toast, vbox,
)
from .base import Page


class CameraCard(QFrame):
    def __init__(self, page: CameraPage, cam: dict, can_manage: bool):
        super().__init__()
        self.setObjectName("Panel")
        self.cam = cam
        self.view = CameraView()
        self.view.setMinimumHeight(220)
        title = label(cam["name"], bold=True)
        tags = [tag(cam["protocolText"], "accent" if cam["protocol"] == 0 else "violet")]
        if not cam["isActive"]:
            tags.append(tag("停用", "dim"))
        drone = label(f"{cam['droneName']} ({cam['droneSerialNumber']})", faint=True, small=True)
        url = label(cam["streamUrl"], faint=True, small=True, mono=True)
        url.setToolTip(cam["streamUrl"])
        desc = label(cam.get("description") or "", dim=True, small=True, wrap=True)
        self.play_btn = button("▶ 播放", "primary", "sm", self.toggle)
        self.play_btn.setEnabled(cam["isActive"] and cv2 is not None)
        snap = button("快照", "ghost", "sm", self.save_snapshot)
        ops = [self.play_btn, snap, "stretch"]
        if can_manage:
            ops += [button("編輯", "ghost", "sm", lambda: page.open_edit(cam)),
                    button("刪除", "danger", "sm", lambda: page.remove(cam))]
        self.setLayout(vbox(hbox(title, *tags, "stretch", spacing=6), drone, self.view, url, desc, hbox(*ops),
                            spacing=6, margins=(12, 10, 12, 12)))

    def toggle(self):
        if self.view.playing:
            self.view.stop()
            self.play_btn.setText("▶ 播放")
        else:
            self.view.play(self.cam["streamUrl"])
            self.play_btn.setText("■ 停止")

    def stop(self):
        self.view.stop()
        self.play_btn.setText("▶ 播放")

    def save_snapshot(self):
        img = self.view.snapshot()
        if img is None:
            toast("目前沒有畫面可截圖", "warn")
            return
        default = data_dir() / f"snapshot_{self.cam['id']}_{datetime.now():%Y%m%d_%H%M%S}.jpg"
        path, _ = QFileDialog.getSaveFileName(self, "儲存快照", str(default), "JPEG (*.jpg)")
        if path:
            img.save(path, "JPG")
            toast(f"快照已儲存:{path}", "success")


class CameraPage(Page):
    title = "攝影機管理"
    subtitle = "為每台無人機掛載多路 IP 攝影機,由用戶端以 OpenCV 直接拉流,支援 HTTP / RTSP 即時串流"

    def __init__(self, main):
        super().__init__(main)
        self.cameras: list[dict] = []
        self.drones: list[dict] = []
        self.cards: list[CameraCard] = []
        self.can_manage = api.can("camera.manage")

        self.drone_filter = combo([("全部無人機", None)])
        self.drone_filter.setMinimumWidth(220)
        self.drone_filter.currentIndexChanged.connect(self._render)
        self.add_head_action(self.drone_filter)
        if self.can_manage:
            self.add_head_action(button("＋ 新增攝影機", "primary", on_click=lambda: self.open_edit(None)))
        if cv2 is None:
            self.add(label("此版本未包含 OpenCV,無法播放影像 (仍可管理攝影機設定)", color=fmt.WARN))

        self.grid_box = QWidget()
        self.grid = QGridLayout(self.grid_box)
        self.grid.setSpacing(16)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.add(self.grid_box)

    def on_show(self):
        self.load()
        if api.can("drone.view"):
            def ok(res):
                self.drones = res["items"]
                current = self.drone_filter.currentData()
                self.drone_filter.blockSignals(True)
                self.drone_filter.clear()
                self.drone_filter.addItem("全部無人機", None)
                for d in self.drones:
                    self.drone_filter.addItem(f"{d['name']} ({d['serialNumber']})", d["id"])
                self.drone_filter.setCurrentIndex(max(0, self.drone_filter.findData(current)))
                self.drone_filter.blockSignals(False)
            run_async(lambda: api.drones(pageSize=200), ok, lambda _e: None, owner=self)

    def on_hide(self):
        for c in self.cards:
            c.stop()

    def load(self):
        def ok(cams):
            self.cameras = cams
            self._render()
        run_async(api.cameras, ok, self.fail("載入攝影機失敗"), owner=self)

    def _render(self, *_):
        for c in self.cards:
            c.stop()
        self.cards = []
        clear_layout(self.grid)
        drone_id = self.drone_filter.currentData()
        items = [c for c in self.cameras if drone_id is None or c["droneId"] == drone_id]
        if not items:
            empty = label("尚無攝影機", faint=True)
            empty.setObjectName("Empty")
            self.grid.addWidget(empty, 0, 0)
            return
        for i, cam in enumerate(items):
            card = CameraCard(self, cam, self.can_manage)
            self.cards.append(card)
            self.grid.addWidget(card, i // 3, i % 3)

    def open_edit(self, cam: dict | None):
        if not self.drones:
            toast("請先於「無人機設定」建立無人機", "warn")
            return
        dlg = FormDialog(self, "新增攝影機" if cam is None else f"編輯攝影機 #{cam['id']}", "儲存", width=600)
        drone = combo([(f"{d['name']} ({d['serialNumber']})", d["id"]) for d in self.drones],
                      cam["droneId"] if cam else None)
        name = line_edit(cam["name"] if cam else "", "雲台主鏡")
        protocol = combo([("HTTP (MJPEG / HLS / MP4)", 0), ("RTSP", 1)], cam["protocol"] if cam else 0)
        url = line_edit(cam["streamUrl"] if cam else "", mono=True)
        desc = line_edit(cam.get("description") or "" if cam else "", "前視 4K 雲台 / 紅外熱像…")
        order = int_spin(cam["sortOrder"] if cam else 0, 0, 999)
        active = checkbox("啟用", cam["isActive"] if cam else True)

        def placeholder(*_):
            url.setPlaceholderText("rtsp://192.168.1.60:554/stream1" if protocol.currentData() == 1
                                   else "http://192.168.1.50/video.mjpg")

        protocol.currentIndexChanged.connect(placeholder)
        placeholder()
        dlg.grid([field("所屬無人機 *", drone), field("攝影機名稱 *", name), field("協定 *", protocol),
                  field("排序 (0 = 自動接續)", order), full(field("串流網址 *", url)), full(field("備註", desc)),
                  full(active)])

        def submit():
            if not name.text().strip():
                toast("請輸入攝影機名稱", "warn")
                return
            if not url.text().strip():
                toast("請輸入串流網址", "warn")
                return
            body = {"droneId": drone.currentData(), "name": name.text().strip(), "protocol": protocol.currentData(),
                    "streamUrl": url.text().strip(), "description": desc.text().strip() or None,
                    "sortOrder": order.value(), "isActive": active.isChecked()}
            dlg.set_busy(True)

            def ok(_):
                dlg.accept()
                toast("攝影機已儲存", "success")
                self.load()

            def err(e):
                dlg.set_busy(False)
                toast(error_message(e, "儲存失敗"), "error")

            run_async(lambda: api.camera_update(cam["id"], body) if cam else api.camera_create(body), ok, err,
                      owner=dlg)

        dlg.on_confirm = submit
        dlg.exec_()

    def remove(self, cam: dict):
        if not confirm(self, f"確定刪除攝影機「{cam['name']}」?"):
            return

        def ok(_):
            toast("已刪除", "success")
            self.load()

        run_async(lambda: api.camera_delete(cam["id"]), ok, self.fail("刪除失敗"), owner=self)
