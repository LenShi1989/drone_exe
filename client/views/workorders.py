"""工單管理:當前工單、歷史工單、工單模板與工單明細。"""
from __future__ import annotations

import csv
from datetime import date

from PyQt5.QtCore import QDate
from PyQt5.QtWidgets import QDateEdit, QFileDialog, QGridLayout, QPlainTextEdit, QWidget

from .. import fmt
from ..api import api, error_message
from ..fmt import DroneStatus, RouteStatus, WorkOrderStatus
from ..realtime import telemetry
from ..tasks import run_async
from ..widgets.common import (
    DataTable, FormDialog, KpiCard, OptionalDateTime, Pager, Panel, button, checkbox, clear_layout, combo, confirm,
    field, full, hbox, int_spin, kpi_row, label, line_edit, progress_cell, prompt_text, set_progress_cell, tag,
    tags_cell, toast, toolbar, vbox,
)
from ..widgets.map_view import GeoLine, GeoMarker, MapWidget
from .base import Page


def date_edit(d: date) -> QDateEdit:
    e = QDateEdit(QDate(d.year, d.month, d.day))
    e.setCalendarPopup(True)
    e.setDisplayFormat("yyyy-MM-dd")
    return e


def qdate_to_date(e: QDateEdit) -> date:
    return e.date().toPyDate()


# ============================================================ 工單明細

class WorkOrderDetailDialog(FormDialog):
    def __init__(self, parent: QWidget, order_id: int):
        super().__init__(parent, "工單明細", width=920, hide_footer=True)
        self.order_id = order_id
        self.loading = label("載入中…", faint=True)
        self.add(self.loading)
        run_async(lambda: api.work_order(order_id), self._render, self._fail, owner=self)

    def _fail(self, e):
        toast(error_message(e, "載入工單明細失敗"), "error")
        self.reject()

    def _render(self, d: dict):
        self.loading.hide()
        self.setWindowTitle(f"{d['orderNo']} — {d['title']}")
        head = label(f"{d['orderNo']} — {d['title']}", bold=True)
        head.setStyleSheet("font-size:11.5pt;font-weight:600")
        self.add(head)

        meta = QGridLayout()
        meta.setHorizontalSpacing(18)
        meta.setVerticalSpacing(6)
        items = [
            ("狀態", tag(fmt.WORK_ORDER_STATUS_TEXT[d["status"]], fmt.WORK_ORDER_STATUS_TAG[d["status"]])),
            ("優先度", tag(fmt.PRIORITY_TEXT[d["priority"]], fmt.PRIORITY_TAG[d["priority"]])),
            ("無人機", d.get("droneName") or "未指派"), ("航線", d.get("routeName") or "未指派"),
            ("模板", d.get("templateName") or "—"), ("負責人", d.get("assigneeName") or "—"),
            ("建立", fmt.fmt_datetime(d["createdAt"])), ("排程", fmt.fmt_datetime(d["scheduledAt"])),
            ("起飛", fmt.fmt_datetime(d["startedAt"], True)), ("完成", fmt.fmt_datetime(d["completedAt"], True)),
            ("用時", fmt.fmt_duration(d["durationSeconds"])),
            ("耗電", "—" if d["energyUsedWh"] is None else f"{fmt.fmt_num(d['energyUsedWh'], 1)} Wh"),
        ]
        for i, (k, v) in enumerate(items):
            r, c = divmod(i, 4)
            value = v if isinstance(v, QWidget) else label(str(v), mono=k in ("建立", "排程", "起飛", "完成", "用時", "耗電"))
            meta.addLayout(hbox(label(k, faint=True, small=True), value, "stretch", spacing=8), r, c)
        self.add(meta)

        if d.get("description") or d.get("remark"):
            note = []
            if d.get("description"):
                note.append(f"<span style='color:#5d738f'>說明:</span>{d['description']}")
            if d.get("remark"):
                note.append(f"<span style='color:#5d738f'>備註:</span>{d['remark']}")
            nl = label("<br>".join(note), small=True, wrap=True)
            nl.setStyleSheet("background:rgba(0,229,255,0.04);border:1px solid rgba(148,178,214,0.14);"
                             "border-radius:4px;padding:8px 10px")
            self.add(nl)

        prog = progress_cell(d["progressPercent"])
        prog.layout().setContentsMargins(0, 0, 0, 0)
        self.add(hbox(label("執行進度", faint=True, small=True), "stretch"))
        self.add(prog)

        wps = d["waypoints"]
        table = DataTable([("#", "r", 40), ("座標", "l", 190), ("高度", "r", 70), ("動作", "l", None)])
        table.setFixedSize(400, 260)
        table.reset_rows(len(wps), "未指派航線")
        for i, w in enumerate(wps):
            table.set_text(i, 0, w["sequence"], mono=True)
            table.set_text(i, 1, f"{w['latitude']:.5f}, {w['longitude']:.5f}", mono=True)
            table.set_text(i, 2, f"{w['altitudeM']:g} m", mono=True)
            table.set_text(i, 3, fmt.WAYPOINT_ACTION_TEXT.get(w["action"], ""))
        left = vbox(label(f"航點 ({len(wps)})", faint=True, small=True), table, spacing=6)
        if wps:
            m = MapWidget(min_height=280)
            m.setFixedHeight(280)
            m.set_data([GeoMarker(f"wp-{w['sequence']}", w["latitude"], w["longitude"], fmt.ACCENT, f"#{w['sequence']}")
                        for w in wps],
                       [GeoLine("route", [(w["latitude"], w["longitude"]) for w in wps], fmt.ACCENT, 2.5)]
                       if len(wps) >= 2 else [], fit=True)
            right = m
        else:
            right = label("未指派航線,無法顯示地圖", faint=True)
        self.add(hbox(left, right, spacing=14))

        logs = d["missionLogs"]
        self.add(label(f"任務紀錄 ({len(logs)})", faint=True, small=True))
        timeline = DataTable([("事件", "l", 80), ("內容", "l", 520), ("時間", "r", None)])
        timeline.setFixedHeight(180)
        timeline.reset_rows(len(logs), "尚無任務紀錄")
        for i, log in enumerate(logs):
            timeline.setCellWidget(i, 0, tags_cell(tag(fmt.MISSION_EVENT_TEXT[log["eventType"]],
                                                       fmt.MISSION_EVENT_TAG[log["eventType"]])))
            timeline.set_text(i, 1, log["message"])
            timeline.set_text(i, 2, fmt.fmt_datetime(log["occurredAt"], True), mono=True, faint=True)
        self.add(timeline)
        self.adjustSize()


def open_detail(parent: QWidget, order_id: int) -> None:
    WorkOrderDetailDialog(parent, order_id).exec_()


# ============================================================ 當前工單

class WorkOrderCurrentPage(Page):
    title = "當前工單"
    subtitle = "待處理 / 已排程 / 執行中的工單。排程後由模擬器自動起飛執行"

    def __init__(self, main):
        super().__init__(main)
        self.rows: list[dict] = []
        self.drones: list[dict] = []
        self.routes: list[dict] = []
        self.templates: list[dict] = []
        self.progress_cells: dict[int, QWidget] = {}
        self.can_manage = api.can("workorder.manage")
        if self.can_manage:
            self.add_head_action(button("＋ 建立工單", "primary", on_click=lambda: self.open_edit(None)))

        panel = Panel(padded=False)
        self.keyword = line_edit(placeholder="工單號 / 標題")
        self.keyword.returnPressed.connect(self.search)
        self.status = combo([("全部進行中", None), ("待處理", 0), ("已排程", 1), ("執行中", 2)])
        self.status.currentIndexChanged.connect(self.search)
        panel.add(toolbar(field("關鍵字", self.keyword), field("狀態", self.status),
                          button("查詢", on_click=self.search), "stretch", button("重新整理", "ghost", on_click=self.load)))
        self.table = DataTable([("工單號", "l", 160), ("標題", "l", 170), ("狀態", "l", 90), ("優先度", "l", 80),
                                ("無人機", "l", 100), ("航線", "l", 140), ("進度", "l", 130), ("排程時間", "l", 130),
                                ("", "r", None)])
        self.table.setMinimumHeight(520)
        panel.add(self.table)
        self.pager = Pager()
        self.pager.changed.connect(lambda *_: self.load())
        panel.add(self.pager)
        self.add(panel)

    @property
    def published_routes(self):
        return [r for r in self.routes if r["status"] == RouteStatus.Published]

    @property
    def idle_drones(self):
        return [d for d in self.drones if d["isActive"] and d["status"] == DroneStatus.Idle]

    def on_show(self):
        telemetry.snapshotsChanged.connect(self._live_progress)
        telemetry.workOrderChanged.connect(self._on_wo_changed)
        self.load()
        self.load_refs()

    def on_hide(self):
        for sig, slot in ((telemetry.snapshotsChanged, self._live_progress),
                          (telemetry.workOrderChanged, self._on_wo_changed)):
            try:
                sig.disconnect(slot)
            except TypeError:
                pass

    def _on_wo_changed(self, _e):
        self.load()  # 模擬器改變工單狀態時自動刷新列表

    def load_refs(self):
        def safe(fn, default):
            try:
                return fn()
            except Exception:  # noqa: BLE001 - 沒有權限的參照資料不影響工單清單
                return default

        def load():
            return (safe(lambda: api.drones(pageSize=100)["items"], []), safe(api.routes, []),
                    safe(api.templates, []))

        def ok(res):
            self.drones, self.routes, self.templates = res

        run_async(load, ok, owner=self)

    def search(self, *_):
        self.pager.reset()
        self.load()

    def load(self):
        q = {"scope": "current", "page": self.pager.page, "pageSize": self.pager.page_size,
             "keyword": self.keyword.text().strip() or None, "status": self.status.currentData()}

        def ok(res):
            self.rows = res["items"]
            self.pager.set_total(res["total"])
            self._render()

        run_async(lambda: api.work_orders(**q), ok, self.fail("載入工單失敗"), owner=self)

    def _live_map(self) -> dict[int, int]:
        return {s["workOrderId"]: s["progressPercent"] for s in telemetry.snapshots if s.get("workOrderId")}

    def _live_progress(self):
        live = self._live_map()
        for oid, cell in self.progress_cells.items():
            if oid in live:
                set_progress_cell(cell, live[oid])

    def _render(self):
        t = self.table
        t.reset_rows(len(self.rows), "目前沒有進行中的工單")
        self.progress_cells = {}
        live = self._live_map()
        for i, o in enumerate(self.rows):
            link = button(o["orderNo"], "link", on_click=lambda oid=o["id"]: open_detail(self, oid))
            t.setCellWidget(i, 0, vbox_widget(link))
            t.set_text(i, 1, o["title"])
            t.setCellWidget(i, 2, tags_cell(tag(fmt.WORK_ORDER_STATUS_TEXT[o["status"]],
                                                fmt.WORK_ORDER_STATUS_TAG[o["status"]])))
            t.setCellWidget(i, 3, tags_cell(tag(fmt.PRIORITY_TEXT[o["priority"]], fmt.PRIORITY_TAG[o["priority"]])))
            t.set_text(i, 4, o.get("droneName") or "—")
            t.set_text(i, 5, o.get("routeName") or "—", dim=True)
            cell = progress_cell(live.get(o["id"], o["progressPercent"]))
            self.progress_cells[o["id"]] = cell
            t.setCellWidget(i, 6, cell)
            t.set_text(i, 7, fmt.fmt_datetime(o["scheduledAt"]), faint=True)
            t.setRowHeight(i, 46)
            btns = []
            if self.can_manage:
                st = o["status"]
                if st == WorkOrderStatus.Pending:
                    btns.append(button("排程", "primary", "sm", lambda oo=o: self.open_schedule(oo)))
                if st == WorkOrderStatus.Scheduled:
                    btns.append(button("立即起飛", None, "sm", lambda oo=o: self.start_now(oo)))
                if st != WorkOrderStatus.InProgress:
                    btns.append(button("編輯", "ghost", "sm", lambda oo=o: self.open_edit(oo)))
                if st == WorkOrderStatus.InProgress:
                    btns.append(button("結案", "ghost", "sm", lambda oo=o: self.complete(oo)))
                btns.append(button("取消", "danger", "sm", lambda oo=o: self.cancel(oo)))
            else:
                btns.append(button("檢視", "ghost", "sm", lambda oid=o["id"]: open_detail(self, oid)))
            t.set_actions(i, 8, btns)

    # ------------------------------------------------------------------ 動作

    def open_edit(self, o: dict | None):
        dlg = FormDialog(self, "建立工單" if o is None else f"編輯工單 #{o['id']}", "儲存", width=660)
        title = line_edit(o["title"] if o else "", "廠區例行巡檢")
        template = combo([("不使用模板", None)] + [(t["name"], t["id"]) for t in self.templates],
                         o["templateId"] if o else None)
        priority = combo([(t, k) for k, t in fmt.PRIORITY_TEXT.items()], o["priority"] if o else 1)
        route = combo([("稍後指派", None)] + [(f"{r['name']} ({r['estimatedMinutes']} 分)", r["id"])
                                          for r in self.published_routes], o["routeId"] if o else None)
        drone = combo([("稍後指派", None)] + [(f"{d['name']} ({d['batteryPercent']:.0f}%)", d["id"])
                                          for d in self.drones if d["isActive"]], o["droneId"] if o else None)
        scheduled = OptionalDateTime("指定時間", fmt.parse_dt(o["scheduledAt"]) if o else None)
        desc = QPlainTextEdit(o.get("description") or "" if o else "")
        desc.setFixedHeight(70)
        remark = line_edit(o.get("remark") or "" if o else "")

        def apply_template(*_):
            """選模板時自動帶入預設航線、優先度與標題。"""
            t = next((x for x in self.templates if x["id"] == template.currentData()), None)
            if not t:
                return
            if route.currentData() is None and t.get("defaultRouteId"):
                idx = route.findData(t["defaultRouteId"])
                if idx >= 0:
                    route.setCurrentIndex(idx)
            idx = priority.findData(t["defaultPriority"])
            priority.setCurrentIndex(max(0, idx))
            if not title.text().strip():
                title.setText(t["name"])
            if not desc.toPlainText().strip():
                desc.setPlainText(t.get("description") or "")

        template.currentIndexChanged.connect(apply_template)
        dlg.grid([full(field("標題 *", title)), field("套用模板", template), field("優先度", priority),
                  field("航線 (需已發布)", route), field("無人機", drone), full(field("排程時間", scheduled)),
                  full(field("說明", desc)), full(field("備註", remark))])

        def submit():
            if not title.text().strip():
                toast("請填寫工單標題", "warn")
                return
            body = {"title": title.text().strip(), "description": desc.toPlainText().strip() or None,
                    "templateId": template.currentData(), "routeId": route.currentData(),
                    "droneId": drone.currentData(), "priority": priority.currentData(),
                    "scheduledAt": fmt.local_to_utc_iso(scheduled.value()), "remark": remark.text().strip() or None}
            dlg.set_busy(True)

            def ok(_):
                dlg.accept()
                toast("工單已儲存", "success")
                self.load()

            def err(e):
                dlg.set_busy(False)
                toast(error_message(e, "儲存工單失敗"), "error")

            run_async(lambda: api.work_order_update(o["id"], body) if o else api.work_order_create(body), ok, err,
                      owner=dlg)

        dlg.on_confirm = submit
        dlg.exec_()

    def open_schedule(self, o: dict):
        dlg = FormDialog(self, f"排程 {o['orderNo']}", "確認排程", width=520)
        idle = self.idle_drones
        drone = combo([("請選擇", None)] + [(f"{d['name']} — 電量 {d['batteryPercent']:.0f}%", d["id"]) for d in idle],
                      o["droneId"] or (idle[0]["id"] if idle else None))
        routes = self.published_routes
        route = combo([("請選擇", None)] + [(f"{r['name']} — {r['estimatedMinutes']} 分 / {r['estimatedEnergyWh']:g} Wh",
                                          r["id"]) for r in routes], o["routeId"] or (routes[0]["id"] if routes else None))
        when = OptionalDateTime("指定時間 (不勾 = 立即)")
        dlg.add(field("無人機 (僅待命機可派工)", drone,
                      "目前沒有待命中的無人機" if not idle else None))
        dlg.add(field("航線 (僅已發布)", route))
        dlg.add(field("排程時間", when))
        dlg.add(label("排程時後端會檢查電量是否足以覆蓋航線預估耗電 × 1.3 的安全係數。", faint=True, small=True, wrap=True))

        def submit():
            if drone.currentData() is None or route.currentData() is None:
                toast("請選擇無人機與航線", "warn")
                return
            dlg.set_busy(True)
            args = (o["id"], drone.currentData(), route.currentData(), fmt.local_to_utc_iso(when.value()))

            def ok(_):
                dlg.accept()
                toast("已排程,模擬器將於數秒內接手起飛", "success")
                self.load()

            def err(e):
                dlg.set_busy(False)
                toast(error_message(e, "排程失敗"), "error")

            run_async(lambda: api.work_order_schedule(*args), ok, err, owner=dlg)

        dlg.on_confirm = submit
        dlg.exec_()

    def start_now(self, o: dict):
        def ok(_):
            toast(f"{o['orderNo']} 已排入立即起飛佇列", "success")
            self.load()
        run_async(lambda: api.work_order_start(o["id"]), ok, self.fail("起飛失敗"), owner=self)

    def cancel(self, o: dict):
        reason = prompt_text(self, "取消工單", f"取消 {o['orderNo']} 的原因:", "天候不佳")
        if reason is None:
            return

        def ok(_):
            toast("工單已取消", "success")
            self.load()
        run_async(lambda: api.work_order_cancel(o["id"], reason), ok, self.fail("取消失敗"), owner=self)

    def complete(self, o: dict):
        if not confirm(self, f"確定手動結案 {o['orderNo']}?"):
            return

        def ok(_):
            toast("工單已結案", "success")
            self.load()
        run_async(lambda: api.work_order_complete(o["id"]), ok, self.fail("結案失敗"), owner=self)


def vbox_widget(w: QWidget) -> QWidget:
    holder = QWidget()
    holder.setLayout(hbox(w, "stretch", margins=(8, 0, 8, 0)))
    return holder


# ============================================================ 歷史工單

class WorkOrderHistoryPage(Page):
    title = "歷史工單"
    subtitle = "已完成 / 已取消 / 失敗的工單歸檔查詢"

    def __init__(self, main):
        super().__init__(main)
        self.rows: list[dict] = []
        self.export_btn = self.add_head_action(button("匯出 CSV", "ghost", on_click=self.export_csv))
        self.k_done, self.k_bad = KpiCard("本頁完成"), KpiCard("失敗 / 取消")
        self.k_avg, self.k_energy = KpiCard("平均用時"), KpiCard("本頁耗電")
        self.add(kpi_row(self.k_done, self.k_bad, self.k_avg, self.k_energy))

        panel = Panel(padded=False)
        self.keyword = line_edit(placeholder="工單號 / 標題")
        self.keyword.returnPressed.connect(self.search)
        self.status = combo([("全部", None), ("已完成", 3), ("已取消", 4), ("失敗", 5)])
        self.drone = combo([("全部", None)])
        self.date_from = date_edit(fmt.day_offset(-30))
        self.date_to = date_edit(fmt.day_offset(0))
        panel.add(toolbar(field("關鍵字", self.keyword), field("狀態", self.status), field("無人機", self.drone),
                          field("起", self.date_from), field("迄", self.date_to),
                          button("查詢", on_click=self.search), "stretch"))
        self.table = DataTable([("工單號", "l", 160), ("標題", "l", 160), ("狀態", "l", 80), ("優先度", "l", 70),
                                ("無人機", "l", 90), ("航線", "l", 130), ("完成時間", "l", 130), ("用時", "r", 90),
                                ("耗電", "r", 80), ("備註", "l", None)])
        self.table.setMinimumHeight(500)
        panel.add(self.table)
        self.pager = Pager()
        self.pager.changed.connect(lambda *_: self.load())
        panel.add(self.pager)
        self.add(panel)
        self._drones_loaded = False

    def on_show(self):
        if not self._drones_loaded and api.can("drone.view"):
            def ok(res):
                self._drones_loaded = True
                for d in res["items"]:
                    self.drone.addItem(d["name"], d["id"])
            run_async(lambda: api.drones(pageSize=100), ok, lambda _e: None, owner=self)
        self.load()

    def search(self, *_):
        self.pager.reset()
        self.load()

    def load(self):
        q = {"scope": "history", "page": self.pager.page, "pageSize": self.pager.page_size,
             "keyword": self.keyword.text().strip() or None, "status": self.status.currentData(),
             "droneId": self.drone.currentData(), "from": fmt.local_day_start_utc(qdate_to_date(self.date_from)),
             "to": fmt.local_day_end_utc(qdate_to_date(self.date_to))}

        def ok(res):
            self.rows = res["items"]
            self.pager.set_total(res["total"])
            self._render()

        run_async(lambda: api.work_orders(**q), ok, self.fail("載入歷史工單失敗"), owner=self)

    def _render(self):
        rows = self.rows
        done = [r for r in rows if r["status"] == WorkOrderStatus.Completed]
        durations = [r["durationSeconds"] for r in done if r.get("durationSeconds")]
        energy = sum(r.get("energyUsedWh") or 0 for r in done)
        self.k_done.set(len(done), "", f"共 {self.pager.total} 筆符合條件", color=fmt.OK)
        self.k_bad.set(f"{sum(1 for r in rows if r['status'] == WorkOrderStatus.Failed)} / "
                       f"{sum(1 for r in rows if r['status'] == WorkOrderStatus.Cancelled)}", "", "本頁統計",
                       color=fmt.WARN)
        self.k_avg.set(fmt.fmt_num(sum(durations) / len(durations) / 60 if durations else 0, 1), "分", "僅計已完成工單")
        self.k_energy.set(fmt.fmt_num(energy, 0), "Wh", "已完成工單合計")
        self.export_btn.setEnabled(bool(rows))

        t = self.table
        t.reset_rows(len(rows))
        for i, o in enumerate(rows):
            t.setCellWidget(i, 0, vbox_widget(button(o["orderNo"], "link",
                                                     on_click=lambda oid=o["id"]: open_detail(self, oid))))
            t.set_text(i, 1, o["title"])
            t.setCellWidget(i, 2, tags_cell(tag(fmt.WORK_ORDER_STATUS_TEXT[o["status"]],
                                                fmt.WORK_ORDER_STATUS_TAG[o["status"]])))
            t.setCellWidget(i, 3, tags_cell(tag(fmt.PRIORITY_TEXT[o["priority"]], fmt.PRIORITY_TAG[o["priority"]])))
            t.set_text(i, 4, o.get("droneName") or "—")
            t.set_text(i, 5, o.get("routeName") or "—", dim=True)
            t.set_text(i, 6, fmt.fmt_datetime(o["completedAt"]), faint=True)
            t.set_text(i, 7, fmt.fmt_duration(o["durationSeconds"]), mono=True)
            t.set_text(i, 8, "—" if o["energyUsedWh"] is None else f"{fmt.fmt_num(o['energyUsedWh'], 0)} Wh", mono=True)
            t.set_text(i, 9, o.get("remark") or "—", faint=True, tooltip=o.get("remark"))

    def export_csv(self):
        """匯出目前頁面資料為 CSV (UTF-8 BOM,讓 Excel 正確識別中文)。"""
        f, t = qdate_to_date(self.date_from), qdate_to_date(self.date_to)
        path, _ = QFileDialog.getSaveFileName(self, "匯出 CSV", f"workorders_{f}_{t}.csv", "CSV (*.csv)")
        if not path:
            return
        header = ["工單號", "標題", "狀態", "優先度", "無人機", "航線", "起飛", "完成", "用時(秒)", "耗電(Wh)", "備註"]
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as fh:
                w = csv.writer(fh, quoting=csv.QUOTE_ALL)
                w.writerow(header)
                for r in self.rows:
                    w.writerow([r["orderNo"], r["title"], fmt.WORK_ORDER_STATUS_TEXT[r["status"]],
                                fmt.PRIORITY_TEXT[r["priority"]], r.get("droneName") or "", r.get("routeName") or "",
                                fmt.fmt_datetime(r["startedAt"], True) if r["startedAt"] else "",
                                fmt.fmt_datetime(r["completedAt"], True) if r["completedAt"] else "",
                                r.get("durationSeconds") or "", r.get("energyUsedWh") or "", r.get("remark") or ""])
        except OSError as e:
            toast(f"匯出失敗:{e}", "error")
            return
        toast(f"已匯出 {len(self.rows)} 筆:{path}", "success")


# ============================================================ 工單模板

class WorkOrderTemplatePage(Page):
    title = "工單模板"
    subtitle = "預先定義常用任務的航線、優先度與起飛前檢查項目"

    def __init__(self, main):
        super().__init__(main)
        self.templates: list[dict] = []
        self.routes: list[dict] = []
        self.add_head_action(button("＋ 新增模板", "primary", on_click=lambda: self.open_edit(None)))
        self.grid_box = QWidget()
        self.grid = QGridLayout(self.grid_box)
        self.grid.setSpacing(16)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.add(self.grid_box)

    def on_show(self):
        def load():
            return api.templates(), (api.routes() if api.can("map.view") else [])

        def ok(res):
            self.templates, self.routes = res
            self._render()

        run_async(load, ok, self.fail("載入模板失敗"), owner=self)

    def _render(self):
        clear_layout(self.grid)
        if not self.templates:
            empty = label("尚無模板", faint=True)
            empty.setObjectName("Empty")
            self.grid.addWidget(empty, 0, 0)
            return
        for i, t in enumerate(self.templates):
            card = Panel(t["name"])
            if not t["isActive"]:
                card.add_action(tag("停用", "dim"))
            card.add_action(tag(fmt.PRIORITY_TEXT[t["defaultPriority"]], fmt.PRIORITY_TAG[t["defaultPriority"]]))
            card.add(label(t.get("description") or "(無說明)", dim=True, small=True, wrap=True))
            meta = QGridLayout()
            meta.setHorizontalSpacing(14)
            for r, (k, v) in enumerate((("預設航線", t.get("defaultRouteName") or "未指定"),
                                        ("預估用時", f"{t['estimatedMinutes']} 分"),
                                        ("建立", fmt.fmt_datetime(t["createdAt"])))):
                meta.addWidget(label(k, faint=True, small=True), r, 0)
                meta.addWidget(label(v, mono=True, small=True), r, 1)
            card.add(meta)
            card.add(label(f"起飛前檢查 ({len(t['checklist'])})", faint=True, small=True))
            checks = "<br>".join(f"<span style='color:#00e5ff'>✓</span> {c}" for c in t["checklist"]) \
                or "<span style='color:#5d738f'>未設定檢查項目</span>"
            card.add(label(checks, small=True, wrap=True))
            card.add("stretch")
            card.add(hbox(button("編輯", "ghost", "sm", lambda tt=t: self.open_edit(tt)),
                          button("刪除", "danger", "sm", lambda tt=t: self.remove(tt)), "stretch"))
            self.grid.addWidget(card, i // 3, i % 3)
        for c in range(3):
            self.grid.setColumnStretch(c, 1)

    def open_edit(self, t: dict | None):
        dlg = FormDialog(self, "新增模板" if t is None else f"編輯模板 #{t['id']}", "儲存", width=600)
        name = line_edit(t["name"] if t else "", "日常廠區巡檢")
        route = combo([("不指定", None)] + [(r["name"], r["id"]) for r in self.routes], t["defaultRouteId"] if t else None)
        priority = combo([(x, k) for k, x in fmt.PRIORITY_TEXT.items()], t["defaultPriority"] if t else 1)
        minutes = int_spin(t["estimatedMinutes"] if t else 30, 1, 1440)
        active = checkbox("啟用", t["isActive"] if t else True)
        desc = line_edit(t.get("description") or "" if t else "")
        checklist = QPlainTextEdit("\n".join(t["checklist"]) if t else "")
        checklist.setPlaceholderText("電池 ≥ 80%\n螺旋槳外觀檢查\nGPS 定位 ≥ 12 顆")
        checklist.setFixedHeight(110)
        dlg.grid([full(field("模板名稱 *", name)), field("預設航線", route), field("預設優先度", priority),
                  field("預估用時 (分)", minutes), field(" ", active), full(field("說明", desc)),
                  full(field("起飛前檢查項目 (一行一項)", checklist))])

        def submit():
            if not name.text().strip():
                toast("請填寫模板名稱", "warn")
                return
            body = {"name": name.text().strip(), "description": desc.text().strip() or None,
                    "defaultRouteId": route.currentData(), "defaultPriority": priority.currentData(),
                    "estimatedMinutes": minutes.value(),
                    "checklist": [s.strip() for s in checklist.toPlainText().splitlines() if s.strip()],
                    "isActive": active.isChecked()}
            dlg.set_busy(True)

            def ok(_):
                dlg.accept()
                toast("模板已儲存", "success")
                self.on_show()

            def err(e):
                dlg.set_busy(False)
                toast(error_message(e, "儲存模板失敗"), "error")

            run_async(lambda: api.template_update(t["id"], body) if t else api.template_create(body), ok, err,
                      owner=dlg)

        dlg.on_confirm = submit
        dlg.exec_()

    def remove(self, t: dict):
        if not confirm(self, f"確定刪除模板「{t['name']}」?"):
            return

        def ok(_):
            toast("模板已刪除", "success")
            self.on_show()

        run_async(lambda: api.template_delete(t["id"]), ok, self.fail("刪除失敗"), owner=self)

