"""無人機管理:無人機設定 (機隊 CRUD、模擬機、巡航、指令) 與無人機狀態 (電量 / 用電記錄)。"""
from __future__ import annotations

from PyQt5.QtCore import QTimer

from .. import fmt
from ..api import api, error_message
from ..fmt import DroneStatus
from ..realtime import telemetry
from ..tasks import run_async
from ..widgets.charts import ChartWidget, Series
from ..widgets.common import (
    BatteryBar, DataTable, FormDialog, KpiCard, Pager, Panel, button, checkbox, combo, confirm, field, float_spin,
    full, hbox, int_spin, kpi_row, label, line_edit, menu_button, tag, tags_cell, toast, toolbar, vbox, wrap_layout,
)
from .base import Page

DEFAULT_HOME = (25.0559, 121.6156)


# ============================================================ 無人機設定

class DroneSettingsPage(Page):
    title = "無人機設定"
    subtitle = "機身序號、電池容量與返航點等機隊參數維護"

    def __init__(self, main):
        super().__init__(main)
        self.rows: list[dict] = []
        self.routes: list[dict] = []
        self.add_head_action(button("✈ 新增模擬機", on_click=self.open_sim_create))
        self.add_head_action(button("＋ 新增無人機", "primary", on_click=lambda: self.open_edit(None)))

        panel = Panel(padded=False)
        self.keyword = line_edit(placeholder="名稱 / 序號 / 機型")
        self.keyword.returnPressed.connect(self.search)
        self.status_filter = combo([("全部", None)] + [(t, k) for k, t in fmt.DRONE_STATUS_TEXT.items()])
        self.status_filter.currentIndexChanged.connect(self.search)
        panel.add(toolbar(field("關鍵字", self.keyword), field("狀態", self.status_filter),
                          button("查詢", on_click=self.search), "stretch"))
        self.table = DataTable([("名稱 / 序號", "l", 170), ("機型", "l", 120), ("狀態", "l", 180), ("電池容量", "r", 90),
                                ("續航", "r", 70), ("最大速度", "r", 85), ("返航點", "l", 150), ("韌體", "l", 70),
                                ("最後心跳", "l", 130), ("", "r", None)])
        self.table.setMinimumHeight(520)
        panel.add(self.table)
        self.pager = Pager()
        self.pager.changed.connect(lambda *_: self.load())
        panel.add(self.pager)
        self.add(panel)

    def on_show(self):
        self.load()
        if api.can("map.view"):
            run_async(lambda: api.routes(status=1), lambda r: setattr(self, "routes", r), lambda _e: None, owner=self)

    def search(self, *_):
        self.pager.reset()
        self.load()

    def load(self):
        self.table.show_message("載入中…")
        q = {"page": self.pager.page, "pageSize": self.pager.page_size,
             "keyword": self.keyword.text().strip() or None, "status": self.status_filter.currentData()}

        def ok(res):
            self.rows = res["items"]
            self.pager.set_total(res["total"])
            self._render()

        run_async(lambda: api.drones(**q), ok, self.fail("載入無人機清單失敗"), owner=self)

    def _render(self):
        t = self.table
        t.reset_rows(len(self.rows))
        for i, d in enumerate(self.rows):
            t.set_two_line(i, 0, d["name"], d["serialNumber"])
            tags = [tag(fmt.DRONE_STATUS_TEXT[d["status"]], fmt.DRONE_STATUS_TAG[d["status"]])]
            if not d["isActive"]:
                tags.append(tag("已停用", "dim"))
            if d["isPatrolling"]:
                pt = tag("巡航中", "info")
                pt.setToolTip(d.get("patrolRouteName") or "")
                tags.append(pt)
            t.setCellWidget(i, 2, tags_cell(*tags))
            t.set_text(i, 1, d["model"], faint=not d["isActive"])
            t.set_text(i, 3, f"{d['batteryCapacityWh']:g} Wh", mono=True)
            t.set_text(i, 4, f"{d['maxFlightMinutes']} 分", mono=True)
            t.set_text(i, 5, f"{d['maxSpeedMps']:g} m/s", mono=True)
            t.set_text(i, 6, f"{d['homeLatitude']:.4f}, {d['homeLongitude']:.4f}", mono=True)
            t.set_text(i, 7, d["firmwareVersion"], mono=True)
            t.set_text(i, 8, fmt.fmt_datetime(d["lastHeartbeatAt"]), faint=True)
            actions = []
            if d["isActive"]:
                actions.append(("停止巡航" if d["isPatrolling"] else "巡航", lambda dd=d: self.toggle_patrol(dd)))
            actions += [("返航", lambda dd=d: self.command(dd, "Return")),
                        ("充電", lambda dd=d: self.command(dd, "Charge"))]
            if d["isActive"]:
                actions += [None, ("停用", lambda dd=d: self.disable(dd))]
            t.set_actions(i, 9, [button("編輯", "ghost", "sm", lambda dd=d: self.open_edit(dd)),
                                 menu_button("指令", actions)])

    # ------------------------------------------------------------------ 動作

    def open_edit(self, d: dict | None):
        dlg = FormDialog(self, "新增無人機" if d is None else f"編輯無人機 #{d['id']}", "儲存", width=640)
        sn = line_edit(d["serialNumber"] if d else "", "DRN-007", mono=True)
        name = line_edit(d["name"] if d else "", "巡檢七號")
        model = line_edit(d["model"] if d else "", "MatrixPro-4T")
        fw = line_edit(d["firmwareVersion"] if d else "2.4.1", mono=True)
        cap = float_spin(d["batteryCapacityWh"] if d else 320, 1, 100000, 0)
        minutes = int_spin(d["maxFlightMinutes"] if d else 35, 1, 600)
        speed = float_spin(d["maxSpeedMps"] if d else 18, 1, 100, 1)
        status = combo([(t, k) for k, t in fmt.DRONE_STATUS_TEXT.items()], d["status"] if d else DroneStatus.Offline)
        lat = float_spin(d["homeLatitude"] if d else DEFAULT_HOME[0], -90, 90, 7, 0.0001)
        lng = float_spin(d["homeLongitude"] if d else DEFAULT_HOME[1], -180, 180, 7, 0.0001)
        active = checkbox("啟用 (可被派工)", d["isActive"] if d else True)
        dlg.grid([field("機身序號 *", sn), field("名稱 *", name), field("機型 *", model), field("韌體版本", fw),
                  field("電池容量 (Wh)", cap), field("標稱續航 (分)", minutes), field("最大速度 (m/s)", speed),
                  field("狀態", status), field("返航點緯度", lat), field("返航點經度", lng), full(active)])

        def submit():
            if not (sn.text().strip() and name.text().strip() and model.text().strip()):
                toast("請填寫序號、名稱與機型", "warn")
                return
            body = {"serialNumber": sn.text().strip(), "name": name.text().strip(), "model": model.text().strip(),
                    "firmwareVersion": fw.text().strip() or "1.0.0", "batteryCapacityWh": cap.value(),
                    "maxSpeedMps": speed.value(), "maxFlightMinutes": minutes.value(), "homeLatitude": lat.value(),
                    "homeLongitude": lng.value(), "status": status.currentData(), "isActive": active.isChecked()}
            dlg.set_busy(True)

            def ok(_):
                dlg.accept()
                toast("無人機設定已儲存", "success")
                self.load()

            def err(e):
                dlg.set_busy(False)
                toast(error_message(e, "儲存失敗"), "error")

            run_async(lambda: api.drone_update(d["id"], body) if d else api.drone_create(body), ok, err, owner=dlg)

        dlg.on_confirm = submit
        dlg.exec_()

    def open_sim_create(self):
        dlg = FormDialog(self, "新增模擬機", "建立並起飛", width=640)
        dlg.add(label("序號 (SIM-xxx) 與名稱由系統自動編號,建立後立即納入模擬器,"
                      "可直接在「即時監控」看到飛行、耗電與返航充電。", faint=True, small=True, wrap=True))
        count = int_spin(1, 1, 20)
        prefix = line_edit("模擬機", "模擬機")
        model = line_edit("SimDrone-X", "SimDrone-X")
        cap = float_spin(320, 1, 100000, 0)
        pct = float_spin(100, 0, 100, 0)
        route = combo([("自動挑選已發布航線", None)] + [(r["name"], r["id"]) for r in self.routes])
        custom = checkbox("指定起降點 (預設沿用既有起降場)")
        lat = float_spin(DEFAULT_HOME[0], -90, 90, 7, 0.0001)
        lng = float_spin(DEFAULT_HOME[1], -180, 180, 7, 0.0001)
        lat_f, lng_f = field("起降點緯度", lat), field("起降點經度", lng)
        start = checkbox("建立後立即起飛巡航", True)
        loop = checkbox("循環巡航 (低電量自動返航充電,充飽再起飛)", True)
        start.toggled.connect(loop.setEnabled)
        dlg.grid([field("數量", count), field("名稱前綴", prefix), field("機型", model), field("電池容量 (Wh)", cap),
                  field("初始電量 (%)", pct), field("巡航航線", route), full(custom), lat_f, lng_f, full(start),
                  full(loop)])
        lat_f.setVisible(False)
        lng_f.setVisible(False)
        custom.toggled.connect(lambda on: (lat_f.setVisible(on), lng_f.setVisible(on), dlg.adjustSize()))

        def submit():
            body = {"count": count.value(), "namePrefix": prefix.text().strip() or None,
                    "model": model.text().strip() or None, "batteryCapacityWh": cap.value(),
                    "batteryPercent": pct.value(), "routeId": route.currentData(),
                    "homeLatitude": lat.value() if custom.isChecked() else None,
                    "homeLongitude": lng.value() if custom.isChecked() else None,
                    "startPatrol": start.isChecked(), "loop": loop.isChecked()}
            dlg.set_busy(True)

            def ok(res):
                dlg.accept()
                toast(res["message"], "success")
                self.load()

            def err(e):
                dlg.set_busy(False)
                toast(error_message(e, "新增模擬機失敗"), "error")

            run_async(lambda: api.drone_simulated(body), ok, err, owner=dlg)

        dlg.on_confirm = submit
        dlg.exec_()

    def toggle_patrol(self, d: dict):
        def ok(res):
            if d["isPatrolling"]:
                toast(f"{d['name']} 已停止巡航,返航中", "success")
            else:
                toast(f"{d['name']} 開始巡航「{res['routeName']}」", "success")
            self.load()

        fn = (lambda: api.drone_stop_patrol(d["id"])) if d["isPatrolling"] else (lambda: api.drone_start_patrol(d["id"]))
        run_async(fn, ok, self.fail("巡航設定失敗"), owner=self)

    def command(self, d: dict, cmd: str):
        def ok(_):
            toast(f"已對 {d['name']} 下達指令:{cmd}", "success")
            self.load()

        run_async(lambda: api.drone_command(d["id"], cmd), ok, self.fail("指令失敗"), owner=self)

    def disable(self, d: dict):
        if not confirm(self, f"確定停用「{d['name']}」?停用後不會被派工。"):
            return

        def ok(_):
            toast("已停用", "success")
            self.load()

        run_async(lambda: api.drone_disable(d["id"]), ok, self.fail("停用失敗"), owner=self)


# ============================================================ 無人機狀態

class DroneStatusPage(Page):
    title = "無人機狀態"
    subtitle = "電量、功率與用電記錄。遙測每秒更新,明細每 10 秒落盤"

    def __init__(self, main):
        super().__init__(main)
        self.drones: list[dict] = []
        self.selected_id: int | None = None
        self.batteries: dict[int, BatteryBar] = {}
        self.add_head_action(button("重新整理", "ghost", on_click=self.load))

        self.k_energy, self.k_low = KpiCard("機隊累計耗電"), KpiCard("低電量警示")
        self.k_hours, self.k_conn = KpiCard("累計飛行時數"), KpiCard("即時連線")
        self.add(kpi_row(self.k_energy, self.k_low, self.k_hours, self.k_conn))

        panel = Panel("機隊電量總覽", padded=False)
        self.table = DataTable([("名稱 / 序號", "l", 160), ("狀態", "l", 90), ("電量", "l", 180), ("電壓", "r", 80),
                                ("電流", "r", 80), ("功率", "r", 80), ("高度", "r", 70), ("速度", "r", 70),
                                ("累計耗電", "r", 100), ("累計飛行", "r", 90), ("最後心跳", "l", None)])
        self.table.setMinimumHeight(300)
        self.table.rowActivated.connect(self._row_clicked)
        panel.add(self.table)
        self.add(panel)

        self.chart_panel = Panel("電量歷史")
        self.chart = ChartWidget(300)
        self.chart_panel.add(self.chart)
        self.session_panel = Panel("充電記錄", padded=False)
        self.sessions = DataTable([("開始", "l", 140), ("電量變化", "r", 110), ("充入", "r", 90), ("耗時", "r", 90),
                                   ("充電站", "l", None)])
        self.sessions.setMinimumHeight(330)
        self.session_panel.add(self.sessions)
        self.add(hbox(self.chart_panel, self.session_panel, spacing=16))

        self._throttle = QTimer(self, singleShot=True, interval=900, timeout=self._apply_live)

    def on_show(self):
        telemetry.snapshotsChanged.connect(self._throttle.start)
        self.load()

    def on_hide(self):
        try:
            telemetry.snapshotsChanged.disconnect(self._throttle.start)
        except TypeError:
            pass

    def load(self):
        self.table.show_message("載入中…")

        def ok(res):
            self.drones = res["items"]
            if self.selected_id is None and self.drones:
                self.selected_id = self.drones[0]["id"]
            self._render()
            if self.selected_id is not None:
                self.load_detail(self.selected_id)

        run_async(lambda: api.drones(pageSize=100), ok, self.fail("載入無人機狀態失敗"), owner=self)

    def _merged(self) -> list[dict]:
        """列表電量以即時遙測覆蓋 DB 快照,避免顯示落後。"""
        out = []
        for d in self.drones:
            live = telemetry.by_id.get(d["id"])
            m = dict(d, powerW=0, voltageV=0, currentA=0)
            if live:
                m.update(status=live["status"], batteryPercent=live["batteryPercent"], altitudeM=live["altitudeM"],
                         speedMps=live["speedMps"], lastHeartbeatAt=live["recordedAt"], powerW=live["powerW"],
                         voltageV=live["voltageV"], currentA=live["currentA"])
            out.append(m)
        return out

    def _render(self):
        merged = self._merged()
        t = self.table
        t.reset_rows(len(merged), "尚無無人機")
        self.batteries = {}
        for i, d in enumerate(merged):
            t.set_two_line(i, 0, d["name"], d["serialNumber"])
            bar = BatteryBar(d["batteryPercent"])
            self.batteries[d["id"]] = bar
            holder = vbox(bar, margins=(8, 0, 8, 0))
            t.setCellWidget(i, 2, wrap_layout(holder))
            self._fill_live_cells(i, d)
            t.set_text(i, 8, f"{fmt.fmt_num(d['totalEnergyWh'], 0)} Wh", mono=True)
            t.set_text(i, 9, f"{fmt.fmt_num(d['totalFlightSeconds'] / 3600, 1)} h", mono=True)
            if d["id"] == self.selected_id:
                t.selectRow(i)
        self._update_kpis(merged)

    def _fill_live_cells(self, i: int, d: dict):
        t = self.table
        t.setCellWidget(i, 1, tags_cell(tag(fmt.DRONE_STATUS_TEXT[d["status"]], fmt.DRONE_STATUS_TAG[d["status"]])))
        t.set_text(i, 3, f"{fmt.fmt_num(d['voltageV'], 2)} V", mono=True)
        t.set_text(i, 4, f"{fmt.fmt_num(d['currentA'], 2)} A", mono=True)
        t.set_text(i, 5, f"{fmt.fmt_num(d['powerW'], 0)} W", mono=True)
        t.set_text(i, 6, f"{fmt.fmt_num(d['altitudeM'], 0)} m", mono=True)
        t.set_text(i, 7, fmt.fmt_num(d["speedMps"], 1), mono=True)
        t.set_text(i, 10, fmt.fmt_datetime(d["lastHeartbeatAt"], True), faint=True)

    def _apply_live(self):
        merged = self._merged()
        for i, d in enumerate(merged):
            if i >= self.table.rowCount():
                break
            bar = self.batteries.get(d["id"])
            if bar:
                bar.set_percent(d["batteryPercent"])
            self._fill_live_cells(i, d)
        self._update_kpis(merged)

    def _update_kpis(self, merged: list[dict]):
        total = sum(d["totalEnergyWh"] for d in self.drones)
        self.k_energy.set(fmt.fmt_num(total / 1000, 2), "kWh", f"{len(self.drones)} 台合計")
        low = [d for d in merged if d["batteryPercent"] < 30 and d["isActive"]]
        self.k_low.set(len(low), "台", "、".join(d["name"] for d in low) or "全機隊電量正常",
                       color=fmt.DANGER if low else fmt.OK)
        hours = sum(d["totalFlightSeconds"] for d in self.drones) / 3600
        self.k_hours.set(fmt.fmt_num(hours, 1), "小時", "機隊總和")
        last = telemetry.last_updated.strftime("%H:%M:%S") if telemetry.last_updated else "—"
        self.k_conn.set("ONLINE" if telemetry.connected else "OFFLINE", "", f"最後更新 {last}",
                        color=fmt.OK if telemetry.connected else fmt.DANGER)

    def _row_clicked(self, row: int):
        if 0 <= row < len(self.drones):
            self.selected_id = self.drones[row]["id"]
            self.load_detail(self.selected_id)

    def load_detail(self, drone_id: int):
        drone = next((d for d in self.drones if d["id"] == drone_id), None)
        name = drone["name"] if drone else ""
        self.chart_panel.set_title(f"{name} — 電量 / 功率歷史 (載入中…)")
        self.session_panel.set_title(f"{name} — 充電記錄")

        def load():
            return api.drone_telemetry(drone_id, limit=400), api.drone_charge_sessions(drone_id, limit=20)

        def ok(res):
            history, sessions = res
            self.chart_panel.set_title(f"{name} — 電量 / 功率歷史")
            if history:
                labels = [fmt.fmt_time(p["recordedAt"]) for p in history]
                self.chart.category_chart(labels, [
                    Series("電量 %", [p["batteryPercent"] for p in history], "area", fmt.OK),
                    Series("功率 W", [p["powerW"] for p in history], "line", fmt.ACCENT, axis=1),
                    Series("高度 m", [p["altitudeM"] for p in history], "line", fmt.ACCENT_2, axis=1, dashed=True),
                ], ylabels=("%", "W / m"))
            else:
                self.chart.empty("此無人機尚無遙測明細 (需飛行或充電後才會記錄)")
            t = self.sessions
            t.reset_rows(len(sessions), "尚無充電記錄")
            for i, s in enumerate(sessions):
                t.set_text(i, 0, fmt.fmt_datetime(s["startedAt"]))
                t.set_text(i, 1, f"{fmt.fmt_num(s['startPercent'], 0)}% → {fmt.fmt_num(s['endPercent'], 0)}%",
                           mono=True)
                t.set_text(i, 2, f"{fmt.fmt_num(s['energyWh'], 1)} Wh", mono=True)
                t.set_text(i, 3, fmt.fmt_duration(s["durationSeconds"]), mono=True)
                t.set_text(i, 4, s["stationName"], faint=True)

        run_async(load, ok, self.fail("載入歷史資料失敗"), owner=self)
