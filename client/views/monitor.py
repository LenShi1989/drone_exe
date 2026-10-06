"""即時監控:KPI、地圖航跡、機隊即時狀態與選取機體 HUD。"""
from __future__ import annotations

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QFrame, QGridLayout, QLabel, QScrollArea, QWidget

from .. import fmt
from ..api import api
from ..fmt import DroneStatus
from ..realtime import telemetry
from ..tasks import run_async
from ..widgets.common import (
    BatteryBar, KpiCard, Panel, button, checkbox, hbox, kpi_row, label, progress_cell, set_progress_cell, tag, vbox,
)
from ..widgets.map_view import GeoLine, GeoMarker, MapWidget
from .base import Page


class DroneHud(QFrame):
    """地圖左上角的選取機體資訊。"""

    FIELDS = [("SN", "serial"), ("座標", "coord"), ("高度", "alt"), ("速度", "speed"), ("航向", "heading"),
              ("電量", "battery"), ("功率", "power"), ("電壓", "voltage"), ("電流", "current"), ("GPS", "gps"),
              ("任務", "task"), ("進度", "progress")]

    def __init__(self, on_close):
        super().__init__()
        self.setObjectName("Hud")
        self.setFixedWidth(270)
        self.name = QLabel()
        self.name.setStyleSheet("font-weight:600")
        self.status_holder = QWidget()
        self.status_holder.setLayout(hbox())
        close = button("✕", "ghost", "sm", on_close)
        close.setFixedWidth(28)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(3)
        self.values: dict[str, QLabel] = {}
        self.keys: dict[str, QLabel] = {}
        for i, (title, key) in enumerate(self.FIELDS):
            k = label(title, faint=True, small=True)
            v = label("", mono=True, small=True)
            grid.addWidget(k, i, 0)
            grid.addWidget(v, i, 1)
            self.values[key], self.keys[key] = v, k
        self.setLayout(vbox(hbox(self.name, self.status_holder, "stretch", close), grid, spacing=8,
                            margins=(12, 10, 12, 12)))

    def show_snapshot(self, s: dict):
        self.name.setText(s["name"])
        lay = self.status_holder.layout()
        while lay.count():
            lay.takeAt(0).widget().deleteLater()
        lay.addWidget(tag(fmt.DRONE_STATUS_TEXT.get(s["status"], ""), fmt.DRONE_STATUS_TAG.get(s["status"], "dim")))
        v = self.values
        v["serial"].setText(s["serialNumber"])
        v["coord"].setText(f"{s['latitude']:.5f}, {s['longitude']:.5f}")
        v["alt"].setText(f"{fmt.fmt_num(s['altitudeM'])} m")
        v["speed"].setText(f"{fmt.fmt_num(s['speedMps'], 2)} m/s")
        v["heading"].setText(f"{fmt.fmt_num(s['headingDeg'])}°")
        v["battery"].setText(f"{fmt.fmt_num(s['batteryPercent'])} %")
        v["power"].setText(f"{fmt.fmt_num(s['powerW'])} W")
        v["voltage"].setText(f"{fmt.fmt_num(s['voltageV'], 2)} V")
        v["current"].setText(f"{fmt.fmt_num(s['currentA'], 2)} A")
        v["gps"].setText(f"{s['satellites']} 顆 / {s['signalPercent']}%")
        task = s.get("workOrderNo") or (f"巡航 · {s['patrolRouteName']}" if s.get("patrolRouteName") else None)
        for key in ("task", "progress"):
            self.keys[key].setVisible(bool(task))
            v[key].setVisible(bool(task))
        if task:
            self.keys["task"].setText("工單" if s.get("workOrderNo") else "巡航")
            v["task"].setText(s.get("workOrderNo") or s["patrolRouteName"])
            v["progress"].setText(f"{s['progressPercent']} %")
        self.adjustSize()


class FleetItem(QFrame):
    def __init__(self, on_click):
        super().__init__()
        self.setCursor(Qt.PointingHandCursor)
        self._on_click = on_click
        self.drone_id = 0
        self.name = QLabel()
        self.name.setStyleSheet("font-weight:600")
        self.tag_box = QWidget()
        self.tag_box.setLayout(hbox())
        self.battery = BatteryBar()
        self.power = label("", mono=True, small=True, faint=True)
        self.serial = label("", mono=True, small=True, faint=True)
        self.extra = label("", mono=True, small=True, faint=True)
        self.task = label("", mono=True, small=True, faint=True)
        self.task_pct = label("", mono=True, small=True)
        self.progress = progress_cell(0)
        self.progress.layout().setContentsMargins(0, 0, 0, 0)
        self.progress.text.hide()
        self.task_box = QWidget()
        self.task_box.setLayout(vbox(hbox(self.task, "stretch", self.task_pct), self.progress, spacing=3))
        self.setLayout(vbox(hbox(self.name, "stretch", self.tag_box), hbox(self.battery, self.power),
                            hbox(self.serial, "stretch", self.extra), self.task_box, spacing=5,
                            margins=(12, 9, 12, 10)))
        self._tag_key = None

    def mousePressEvent(self, e):
        self._on_click(self.drone_id)

    def update_from(self, s: dict, active: bool):
        self.drone_id = s["droneId"]
        self.name.setText(s["name"])
        key = (s["status"],)
        if key != self._tag_key:
            lay = self.tag_box.layout()
            while lay.count():
                lay.takeAt(0).widget().deleteLater()
            lay.addWidget(tag(fmt.DRONE_STATUS_TEXT.get(s["status"], ""), fmt.DRONE_STATUS_TAG.get(s["status"], "dim")))
            self._tag_key = key
        self.battery.set_percent(s["batteryPercent"])
        self.power.setText(f"{fmt.fmt_num(s['powerW'], 0)} W")
        self.serial.setText(s["serialNumber"])
        flying = s["status"] in (DroneStatus.Flying, DroneStatus.Returning)
        self.extra.setText(f"{fmt.fmt_num(s['altitudeM'], 0)}m · {fmt.fmt_num(s['speedMps'], 1)}m/s" if flying
                           else fmt.fmt_ago(s.get("recordedAt")))
        task = s.get("workOrderNo") or (f"巡航 · {s['patrolRouteName']}" if s.get("patrolRouteName") else None)
        self.task_box.setVisible(bool(task))
        if task:
            self.task.setText(task)
            self.task_pct.setText(f"{s['progressPercent']}%")
            set_progress_cell(self.progress, s["progressPercent"])
        border = "rgba(0,229,255,0.55)" if active else "rgba(148,178,214,0.10)"
        bg = "rgba(0,229,255,0.08)" if active else "transparent"
        self.setStyleSheet(f"FleetItem{{border:none;border-bottom:1px solid rgba(148,178,214,0.10);"
                           f"border-left:2px solid {border if active else 'transparent'};background:{bg}}}")


class MonitorPage(Page):
    title = "即時監控"
    subtitle = ""

    def __init__(self, main):
        super().__init__(main)
        self.points: list[dict] = []
        self.routes: list[dict] = []
        self.selected_id: int | None = None
        self.fleet_items: dict[int, FleetItem] = {}

        self.show_points = checkbox("點位", True)
        self.show_routes = checkbox("航線", True)
        self.show_trails = checkbox("航跡", True)
        for cb in (self.show_points, self.show_routes, self.show_trails):
            cb.toggled.connect(self.redraw)
            self.add_head_action(cb)

        self.k_total, self.k_flying = KpiCard("機隊總數"), KpiCard("飛行中")
        self.k_battery, self.k_orders = KpiCard("平均電量"), KpiCard("進行中工單")
        self.add(kpi_row(self.k_total, self.k_flying, self.k_battery, self.k_orders))

        self.map = MapWidget(min_height=560)
        self.map.markerClicked.connect(self._on_marker)
        self.hud = DroneHud(lambda: self._select(None))
        self.map.add_overlay(self.hud, "tl")
        self.hud.hide()  # 點選無人機後才顯示

        fleet_panel = Panel("機隊即時狀態", padded=False)
        fleet_panel.setFixedWidth(330)
        self.fleet_list = QWidget()
        self.fleet_lay = vbox(spacing=0)
        self.fleet_list.setLayout(self.fleet_lay)
        self.fleet_empty = label("尚無遙測資料", faint=True)
        self.fleet_empty.setObjectName("Empty")
        self.fleet_lay.addWidget(self.fleet_empty)
        self.fleet_lay.addStretch(1)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(self.fleet_list)
        sc.setMinimumHeight(540)
        fleet_panel.add(sc)
        self.add(hbox(self.map, fleet_panel, spacing=16), 1)

        self._overview_timer = QTimer(self, interval=15000, timeout=self._load_overview)

    # ------------------------------------------------------------------ 生命週期

    def on_show(self):
        telemetry.snapshotsChanged.connect(self._on_telemetry)
        telemetry.connectedChanged.connect(self._update_sub)
        if not telemetry.snapshots:
            telemetry.load_once()
        self._update_sub()
        self._load_overview()
        self._overview_timer.start()
        run_async(api.map_points, self._set_points, lambda _e: None, owner=self)

        def load_routes():
            routes = api.routes(status=1)
            return [api.route(r["id"]) for r in routes]  # 清單不含航點,逐條補齊才畫得出航線

        run_async(load_routes, self._set_routes, lambda _e: None, owner=self)
        self._on_telemetry()

    def on_hide(self):
        self._overview_timer.stop()
        for sig, slot in ((telemetry.snapshotsChanged, self._on_telemetry),
                          (telemetry.connectedChanged, self._update_sub)):
            try:
                sig.disconnect(slot)
            except TypeError:
                pass

    # ------------------------------------------------------------------ 資料

    def _load_overview(self):
        run_async(api.stats_overview, self._set_overview, lambda _e: None, owner=self)

    def _set_overview(self, o: dict):
        self.overview = o
        self.k_total.set(o["totalDrones"], "台", f"在線 {o['onlineDrones']} 台")
        self.k_battery.set(fmt.fmt_num(o["avgBatteryPercent"], 1), "%", f"今日耗電 {fmt.fmt_num(o['todayEnergyWh'], 0)} Wh")
        self.k_orders.set(o["activeWorkOrders"], "張", f"今日完成 {o['completedToday']} 張")
        self._update_flying_kpi()

    def _set_points(self, pts):
        self.points = pts
        self.redraw()

    def _set_routes(self, routes):
        self.routes = routes
        self.redraw()

    def _update_sub(self, *_):
        dot = "<span style='color:#22e39b'>●</span>" if telemetry.connected else "<span style='color:#ff4d6d'>●</span>"
        state = "WebSocket 已連線" if telemetry.connected else "未連線 (顯示最後快照)"
        last = telemetry.last_updated.strftime("%H:%M:%S") if telemetry.last_updated else "—"
        self.sub_label.setText(f"{dot} {state} · 最後更新 {last}")

    def _update_flying_kpi(self):
        o = getattr(self, "overview", None)
        self.k_flying.set(len(telemetry.flying), "台", f"充電中 {o['chargingDrones'] if o else 0} 台", color="#22e39b")

    def _on_telemetry(self):
        self._update_sub()
        self._update_flying_kpi()
        self._render_fleet()
        self.redraw()
        if self.selected_id is not None:
            s = telemetry.by_id.get(self.selected_id)
            if s:
                self.hud.show_snapshot(s)

    # ------------------------------------------------------------------ 呈現

    def _sorted(self) -> list[dict]:
        def rank(s):
            st = s["status"]
            return 0 if st in (DroneStatus.Flying, DroneStatus.Returning) else 2 if st == DroneStatus.Offline else 1
        return sorted(telemetry.snapshots, key=lambda s: (rank(s), s["droneId"]))

    def _render_fleet(self):
        items = self._sorted()
        self.fleet_empty.setVisible(not items)
        wanted = [s["droneId"] for s in items]
        for did in list(self.fleet_items):
            if did not in wanted:
                self.fleet_items.pop(did).deleteLater()
        for i, s in enumerate(items):
            item = self.fleet_items.get(s["droneId"])
            if item is None:
                item = FleetItem(self._select)
                self.fleet_items[s["droneId"]] = item
            self.fleet_lay.insertWidget(i + 1, item)
            item.update_from(s, s["droneId"] == self.selected_id)

    def redraw(self, *_):
        markers: list[GeoMarker] = []
        if self.show_points.isChecked():
            markers += [GeoMarker(f"point-{p['id']}", p["latitude"], p["longitude"],
                                  fmt.POINT_TYPE_COLOR.get(p["pointType"], fmt.ACCENT), p["name"]) for p in self.points]
        for s in telemetry.snapshots:
            if s["status"] == DroneStatus.Offline:
                continue
            markers.append(GeoMarker(f"drone-{s['droneId']}", s["latitude"], s["longitude"],
                                     fmt.DRONE_STATUS_COLOR.get(s["status"], fmt.ACCENT),
                                     f"{s['name']} {s['batteryPercent']:.0f}%", "drone", s["headingDeg"]))
        lines: list[GeoLine] = []
        if self.show_routes.isChecked():
            for r in self.routes:
                if len(r.get("waypoints", [])) >= 2:
                    lines.append(GeoLine(f"route-{r['id']}", [(w["latitude"], w["longitude"]) for w in r["waypoints"]],
                                         "#9b85ff", 2, dashed=True))
        if self.show_trails.isChecked():
            for did, trail in telemetry.trails.items():
                if len(trail) >= 2:
                    lines.append(GeoLine(f"trail-{did}", list(trail), fmt.ACCENT, 3))
        self.map.set_data(markers, lines)

    def _on_marker(self, marker_id: str):
        if marker_id.startswith("drone-"):
            self._select(int(marker_id.split("-", 1)[1]))

    def _select(self, drone_id: int | None):
        self.selected_id = drone_id
        s = telemetry.by_id.get(drone_id) if drone_id is not None else None
        if s:
            self.hud.show_snapshot(s)
            self.hud.show()
        else:
            self.hud.hide()
        self._render_fleet()
