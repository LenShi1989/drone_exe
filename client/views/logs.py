"""記錄管理:任務紀錄、登入紀錄、通知中心。"""
from __future__ import annotations

from PyQt5.QtCore import QDate
from PyQt5.QtWidgets import QDateEdit

from .. import fmt
from ..api import api
from ..tasks import run_async
from ..widgets.common import (
    DataTable, Pager, Panel, button, checkbox, combo, field, line_edit, tag, tags_cell, toast, toolbar,
)
from .base import Page
from .workorders import open_detail, vbox_widget


def _date(days: int) -> QDateEdit:
    d = fmt.day_offset(days)
    e = QDateEdit(QDate(d.year, d.month, d.day))
    e.setCalendarPopup(True)
    e.setDisplayFormat("yyyy-MM-dd")
    return e


class _PagedLogPage(Page):
    def _table_panel(self, toolbar_items: list, columns) -> DataTable:
        panel = Panel(padded=False)
        panel.add(toolbar(*toolbar_items))
        self.table = DataTable(columns)
        self.table.setMinimumHeight(560)
        panel.add(self.table)
        self.pager = Pager()
        self.pager.changed.connect(lambda *_: self.load())
        panel.add(self.pager)
        self.add(panel)
        return self.table

    def search(self, *_):
        self.pager.reset()
        self.load()

    def load(self):  # pragma: no cover - 子類別實作
        raise NotImplementedError

    def on_show(self):
        self.load()


# ============================================================ 任務紀錄

class MissionLogPage(_PagedLogPage):
    title = "任務紀錄"
    subtitle = "無人機執行工單時的起飛、航點、降落與異常事件"

    def __init__(self, main):
        super().__init__(main)
        self.add_head_action(button("重新整理", "ghost", on_click=self.load))
        self.auto = checkbox("自動更新 (10 秒)")
        self.add_head_action(self.auto)
        from PyQt5.QtCore import QTimer
        self._timer = QTimer(self, interval=10000, timeout=self.load)
        self.auto.toggled.connect(lambda on: self._timer.start() if on else self._timer.stop())
        self.event = combo([("全部", None)] + [(t, k) for k, t in fmt.MISSION_EVENT_TEXT.items()])
        self.drone = combo([("全部", None)])
        self.date_from, self.date_to = _date(-7), _date(0)
        self._table_panel([field("事件", self.event), field("無人機", self.drone), field("起", self.date_from),
                           field("迄", self.date_to), button("查詢", on_click=self.search), "stretch"],
                          [("時間", "l", 150), ("事件", "l", 80), ("無人機", "l", 110), ("工單", "l", 170),
                           ("內容", "l", None)])
        self._drones_loaded = False

    def on_show(self):
        if not self._drones_loaded and api.can("drone.view"):
            def ok(res):
                self._drones_loaded = True
                for d in res["items"]:
                    self.drone.addItem(d["name"], d["id"])
            run_async(lambda: api.drones(pageSize=100), ok, lambda _e: None, owner=self)
        if self.auto.isChecked():
            self._timer.start()
        self.load()

    def on_hide(self):
        self._timer.stop()

    def load(self):
        q = {"page": self.pager.page, "pageSize": self.pager.page_size, "eventType": self.event.currentData(),
             "droneId": self.drone.currentData(),
             "from": fmt.local_day_start_utc(self.date_from.date().toPyDate()),
             "to": fmt.local_day_end_utc(self.date_to.date().toPyDate())}

        def ok(res):
            self.pager.set_total(res["total"])
            t = self.table
            rows = res["items"]
            t.reset_rows(len(rows))
            for i, log in enumerate(rows):
                t.set_text(i, 0, fmt.fmt_datetime(log["occurredAt"], True), mono=True, faint=True)
                t.setCellWidget(i, 1, tags_cell(tag(fmt.MISSION_EVENT_TEXT[log["eventType"]],
                                                    fmt.MISSION_EVENT_TAG[log["eventType"]])))
                t.set_text(i, 2, log.get("droneName") or "—")
                if log.get("workOrderId") is not None:
                    t.setCellWidget(i, 3, vbox_widget(button(log.get("workOrderNo") or f"#{log['workOrderId']}", "link",
                                                             on_click=lambda oid=log["workOrderId"]: open_detail(self, oid))))
                else:
                    t.set_text(i, 3, "—", faint=True)
                t.set_text(i, 4, log["message"], tooltip=log["message"])

        run_async(lambda: api.mission_logs(**q), ok, self.fail("載入任務紀錄失敗"), owner=self)


# ============================================================ 登入紀錄

class LoginLogPage(_PagedLogPage):
    title = "登入紀錄"
    subtitle = "使用者帳號登入成功與失敗的稽核紀錄"

    def __init__(self, main):
        super().__init__(main)
        self.add_head_action(button("重新整理", "ghost", on_click=self.load))
        self.username = line_edit(placeholder="帳號關鍵字")
        self.username.returnPressed.connect(self.search)
        self.result = combo([("全部", None), ("成功", True), ("失敗", False)])
        self.date_from, self.date_to = _date(-30), _date(0)
        self._table_panel([field("帳號", self.username), field("結果", self.result), field("起", self.date_from),
                           field("迄", self.date_to), button("查詢", on_click=self.search), "stretch"],
                          [("時間", "l", 150), ("帳號", "l", 110), ("結果", "l", 80), ("失敗原因", "l", 120),
                           ("IP", "l", 130), ("User Agent", "l", None)])

    def load(self):
        result = self.result.currentData()
        q = {"page": self.pager.page, "pageSize": self.pager.page_size,
             "username": self.username.text().strip() or None,
             "isSuccess": None if result is None else str(result).lower(),
             "from": fmt.local_day_start_utc(self.date_from.date().toPyDate()),
             "to": fmt.local_day_end_utc(self.date_to.date().toPyDate())}

        def ok(res):
            self.pager.set_total(res["total"])
            t = self.table
            rows = res["items"]
            t.reset_rows(len(rows))
            for i, r in enumerate(rows):
                t.set_text(i, 0, fmt.fmt_datetime(r["loggedAt"], True), mono=True, faint=True)
                t.set_text(i, 1, r["username"], mono=True)
                t.setCellWidget(i, 2, tags_cell(tag("成功", "ok") if r["isSuccess"] else tag("失敗", "danger")))
                t.set_text(i, 3, r.get("failReason") or "—", faint=not r.get("failReason"))
                t.set_text(i, 4, r["ipAddress"], mono=True)
                t.set_text(i, 5, r.get("userAgent") or "—", faint=True, tooltip=r.get("userAgent"))

        run_async(lambda: api.login_logs(**q), ok, self.fail("載入登入紀錄失敗"), owner=self)


# ============================================================ 通知中心

class NotificationPage(_PagedLogPage):
    title = "通知中心"
    subtitle = ""

    def __init__(self, main):
        super().__init__(main)
        self.read_all_btn = self.add_head_action(button("全部標為已讀", "ghost", on_click=self.mark_all_read))
        self.read = combo([("全部", None), ("未讀", False), ("已讀", True)])
        self.category = combo([("全部", None)] + [(t, k) for k, t in fmt.NOTIFICATION_CATEGORY_TEXT.items()])
        self.read.currentIndexChanged.connect(self.search)
        self.category.currentIndexChanged.connect(self.search)
        self._table_panel([field("狀態", self.read), field("分類", self.category),
                           button("重新整理", on_click=self.load), "stretch"],
                          [("等級", "l", 80), ("分類", "l", 80), ("標題", "l", 220), ("內容", "l", 380),
                           ("時間", "l", 140), ("", "r", None)])
        self.set_unread(0)

    def set_unread(self, count: int):
        self.sub_label.setText(f"無人機、工單與系統事件通知 · 未讀 {count} 則")
        self.read_all_btn.setEnabled(count > 0)

    def on_show(self):
        self.main.refresh_unread()
        self.load()

    def load(self):
        read = self.read.currentData()
        q = {"page": self.pager.page, "pageSize": self.pager.page_size,
             "isRead": None if read is None else str(read).lower(), "category": self.category.currentData()}

        def ok(res):
            self.pager.set_total(res["total"])
            t = self.table
            rows = res["items"]
            t.reset_rows(len(rows), "沒有通知")
            for i, n in enumerate(rows):
                t.setCellWidget(i, 0, tags_cell(tag(fmt.NOTIFICATION_LEVEL_TEXT[n["level"]],
                                                    fmt.NOTIFICATION_LEVEL_TAG[n["level"]])))
                t.set_text(i, 1, fmt.NOTIFICATION_CATEGORY_TEXT.get(n["category"], n["category"]), dim=True)
                if n.get("link"):
                    t.setCellWidget(i, 2, vbox_widget(button(n["title"], "link", on_click=lambda nn=n: self.open(nn))))
                else:
                    t.set_text(i, 2, n["title"], color=None if not n["isRead"] else fmt.TEXT_DIM)
                t.set_text(i, 3, n.get("content") or "", dim=n["isRead"], tooltip=n.get("content"))
                t.set_text(i, 4, fmt.fmt_datetime(n["createdAt"]), mono=True, faint=True)
                if not n["isRead"]:
                    t.set_actions(i, 5, [button("標為已讀", "ghost", "sm", lambda nn=n: self.mark_read(nn))])
                else:
                    t.set_text(i, 5, "已讀", faint=True)

        run_async(lambda: api.notifications(**q), ok, self.fail("載入通知失敗"), owner=self)

    def mark_read(self, n: dict, then=None):
        def ok(_):
            self.main.refresh_unread()
            if then:
                then()
            else:
                self.load()
        run_async(lambda: api.notification_read(n["id"]), ok, self.fail("標記已讀失敗"), owner=self)

    def mark_all_read(self):
        def ok(_):
            toast("已全部標記為已讀", "success")
            self.main.refresh_unread()
            self.load()
        run_async(api.notification_read_all, ok, self.fail("標記已讀失敗"), owner=self)

    def open(self, n: dict):
        """點擊有連結的通知:標為已讀並導向對應頁面。"""
        link = n.get("link")
        if not n["isRead"]:
            self.mark_read(n, then=lambda: self.main.navigate(link))
        else:
            self.main.navigate(link)
