"""統計圖表:任務數量、工單圖表、工單用時、充電圖表。"""
from __future__ import annotations

from PyQt5.QtCore import QDate, QTimer, pyqtSignal
from PyQt5.QtWidgets import QDateEdit, QWidget

from .. import fmt
from ..api import api
from ..tasks import run_async
from ..widgets.charts import ChartWidget, Series
from ..widgets.common import DataTable, KpiCard, Panel, button, combo, field, hbox, kpi_row, label, toolbar, vbox
from .base import Page


class StatsFilter(QWidget):
    """起訖日 + 彙總粒度 + 快速區間,任一變動即發出 changed(query)。"""

    changed = pyqtSignal(dict)

    def __init__(self, default_days: int = 30):
        super().__init__()
        self.date_from = self._date(fmt.day_offset(-default_days))
        self.date_to = self._date(fmt.day_offset(0))
        self.granularity = combo([("日", "day"), ("週", "week"), ("月", "month")], "day")
        presets = [button(text, "ghost", "sm", lambda d=d, g=g: self.preset(d, g))
                   for text, d, g in (("近 7 日", 6, "day"), ("近 30 日", 29, "day"), ("近 90 日 (週)", 89, "week"),
                                      ("近 1 年 (月)", 364, "month"))]
        bar = toolbar(field("起始日", self.date_from), field("結束日", self.date_to), field("彙總粒度", self.granularity),
                      "stretch", *presets, margins=(0, 0, 0, 0))
        self.setLayout(vbox(bar))
        self._debounce = QTimer(self, singleShot=True, interval=250, timeout=self.emit_change)
        for w in (self.date_from, self.date_to):
            w.dateChanged.connect(self._debounce.start)
        self.granularity.currentIndexChanged.connect(self._debounce.start)

    @staticmethod
    def _date(d) -> QDateEdit:
        e = QDateEdit(QDate(d.year, d.month, d.day))
        e.setCalendarPopup(True)
        e.setDisplayFormat("yyyy-MM-dd")
        return e

    def preset(self, days: int, granularity: str):
        for w in (self.date_from, self.date_to, self.granularity):
            w.blockSignals(True)
        d = fmt.day_offset(-days)
        t = fmt.day_offset(0)
        self.date_from.setDate(QDate(d.year, d.month, d.day))
        self.date_to.setDate(QDate(t.year, t.month, t.day))
        self.granularity.setCurrentIndex(self.granularity.findData(granularity))
        for w in (self.date_from, self.date_to, self.granularity):
            w.blockSignals(False)
        self.emit_change()

    def query(self) -> dict:
        # 伺服器以 UTC 日界分組;這裡直接送日期字串 (視為 UTC 日期),與原版行為一致
        return {"from": self.date_from.date().toString("yyyy-MM-dd"),
                "to": self.date_to.date().toString("yyyy-MM-dd"), "granularity": self.granularity.currentData()}

    def emit_change(self):
        self.changed.emit(self.query())


class StatsPage(Page):
    kind = ""

    def __init__(self, main):
        super().__init__(main)
        self.filter = StatsFilter()
        self.filter.changed.connect(self.fetch)
        self.top = Panel()
        self.top.add(self.filter)
        self.add(self.top)

    def on_show(self):
        self.fetch(self.filter.query())

    def fetch(self, query: dict):
        run_async(lambda: api.stats(self.kind, **query), self.render, self.fail("載入統計失敗"), owner=self)

    def render(self, data):  # pragma: no cover - 子類別實作
        raise NotImplementedError


# ============================================================ 任務數量

class MissionCountPage(StatsPage):
    title = "任務數量"
    subtitle = "依區間統計任務完成、失敗與取消的數量分佈"
    kind = "mission-count"

    def __init__(self, main):
        super().__init__(main)
        self.k_total, self.k_done = KpiCard("任務總數"), KpiCard("已完成")
        self.k_bad, self.k_rate = KpiCard("失敗 / 取消"), KpiCard("成功率")
        self.top.add(kpi_row(self.k_total, self.k_done, self.k_bad, self.k_rate))
        p1, p2 = Panel("任務結果分佈"), Panel("任務數量趨勢")
        self.stack_chart, self.trend_chart = ChartWidget(340), ChartWidget(300)
        p1.add(self.stack_chart)
        p2.add(self.trend_chart)
        self.add(p1)
        self.add(p2)

    def render(self, data: list[dict]):
        total = sum(p["total"] for p in data)
        done = sum(p["completed"] for p in data)
        failed = sum(p["failed"] for p in data)
        cancelled = sum(p["cancelled"] for p in data)
        self.k_total.set(total)
        self.k_done.set(done, color=fmt.OK)
        self.k_bad.set(f"{failed} / {cancelled}", color=fmt.WARN)
        self.k_rate.set(fmt.fmt_num(done / total * 100 if total else 0, 1), "%")
        labels = [p["period"] for p in data]
        self.stack_chart.category_chart(labels, [
            Series("已完成", [p["completed"] for p in data], "bar", fmt.OK, stack=True),
            Series("失敗", [p["failed"] for p in data], "bar", fmt.DANGER, stack=True),
            Series("已取消", [p["cancelled"] for p in data], "bar", fmt.TEXT_DIM, stack=True),
        ], ylabels=("任務數", ""), integer_y=True)
        self.trend_chart.category_chart(labels, [Series("任務總數", [p["total"] for p in data], "area", fmt.ACCENT,
                                                        marker=True)], ylabels=("總任務數", ""), integer_y=True)


# ============================================================ 工單圖表

STATUS_COLORS = {"待處理": "#5d738f", "已排程": fmt.INFO, "執行中": fmt.ACCENT, "已完成": fmt.OK, "已取消": fmt.TEXT_DIM,
                 "失敗": fmt.DANGER}
PRIORITY_COLORS = {"低": "#5d738f", "一般": fmt.INFO, "高": fmt.WARN, "緊急": fmt.DANGER}


class WorkOrderChartPage(StatsPage):
    title = "工單圖表"
    subtitle = "工單狀態與優先度分佈,以及建立趨勢"
    kind = "work-orders"

    def __init__(self, main):
        super().__init__(main)
        self.total_label = label("", dim=True, small=True)
        self.top.add(self.total_label)
        p1, p2, p3 = Panel("狀態分佈"), Panel("優先度分佈"), Panel("工單建立趨勢")
        self.pie, self.priority_chart, self.trend_chart = ChartWidget(320), ChartWidget(320), ChartWidget(300)
        p1.add(self.pie)
        p2.add(self.priority_chart)
        p3.add(self.trend_chart)
        self.add(hbox(p1, p2, spacing=16))
        self.add(p3)

    def render(self, data: dict):
        total = sum(x["value"] for x in data["byStatus"])
        self.total_label.setText(f"區間內共 <b style='color:#00e5ff;font-family:Consolas'>{total}</b> 張工單")
        self.pie.donut_chart([(x["name"], x["value"], STATUS_COLORS.get(x["name"], fmt.ACCENT))
                              for x in data["byStatus"]])
        # 優先度:每根柱子各自配色,以多個單點數列呈現
        names = [x["name"] for x in data["byPriority"]]
        series = []
        for i, x in enumerate(data["byPriority"]):
            vals = [None] * len(names)
            vals[i] = x["value"]
            series.append(Series(x["name"], [v or 0 for v in vals], "bar", PRIORITY_COLORS.get(x["name"], fmt.ACCENT),
                                 stack=True))
        self.priority_chart.category_chart(names, series, ylabels=("張數", ""), integer_y=True, legend=False)
        self.trend_chart.category_chart([x["name"] for x in data["trend"]],
                                        [Series("建立工單", [x["value"] for x in data["trend"]], "bar", fmt.ACCENT)],
                                        ylabels=("建立張數", ""), integer_y=True)


# ============================================================ 工單用時

class DurationChartPage(StatsPage):
    title = "工單用時"
    subtitle = "已完成工單的執行時間分佈 (起飛至降落)"
    kind = "work-order-duration"

    def __init__(self, main):
        super().__init__(main)
        self.k_avg, self.k_min = KpiCard("加權平均用時"), KpiCard("最短")
        self.k_max, self.k_cover = KpiCard("最長"), KpiCard("有資料區間")
        self.top.add(kpi_row(self.k_avg, self.k_min, self.k_max, self.k_cover))
        p1, p2 = Panel("用時趨勢 (平均 / 最短 / 最長)"), Panel("各區間完成筆數")
        self.chart, self.count_chart = ChartWidget(360), ChartWidget(260)
        p1.add(self.chart)
        p2.add(self.count_chart)
        self.add(p1)
        self.add(p2)

    def render(self, data: list[dict]):
        with_data = [p for p in data if p["count"] > 0]
        count = sum(p["count"] for p in with_data)
        # 以各區間筆數加權,避免小樣本區間拉偏平均
        avg = sum(p["avgMinutes"] * p["count"] for p in with_data) / count if count else 0
        self.k_avg.set(fmt.fmt_num(avg, 1), "分", f"樣本 {count} 筆")
        self.k_min.set(fmt.fmt_num(min((p["minMinutes"] for p in with_data), default=0), 1), "分", color=fmt.OK)
        self.k_max.set(fmt.fmt_num(max((p["maxMinutes"] for p in with_data), default=0), 1), "分", color=fmt.DANGER)
        self.k_cover.set(len(with_data), f"/ {len(data)}", "無完成工單的區間以空值跳過")
        labels = [p["period"] for p in data]
        extra = {i: f"樣本數: {p['count']}" for i, p in enumerate(data)}

        def vals(key):
            return [p[key] if p["count"] > 0 else None for p in data]

        self.chart.category_chart(labels, [
            Series("最長", vals("maxMinutes"), "line", fmt.DANGER, dashed=True),
            Series("平均", vals("avgMinutes"), "area", fmt.ACCENT, marker=True),
            Series("最短", vals("minMinutes"), "line", fmt.OK, dashed=True),
        ], ylabels=("分鐘", ""), unit="分", extra=extra)
        self.count_chart.category_chart(labels, [Series("完成筆數", [p["count"] for p in data], "bar", fmt.ACCENT_2)],
                                        ylabels=("完成筆數", ""), integer_y=True)


# ============================================================ 充電圖表

class ChargingChartPage(StatsPage):
    title = "充電圖表"
    subtitle = "機隊用電記錄:充入電量、充電次數與平均充電時間"
    kind = "charging"

    def __init__(self, main):
        super().__init__(main)
        self.k_total, self.k_sessions = KpiCard("總充入電量"), KpiCard("充電次數")
        self.k_avg, self.k_top = KpiCard("平均每次充入"), KpiCard("耗電最高機體")
        self.top.add(kpi_row(self.k_total, self.k_sessions, self.k_avg, self.k_top))
        p1 = Panel("充電趨勢")
        self.trend = ChartWidget(340)
        p1.add(self.trend)
        self.add(p1)
        p2, p3 = Panel("各機體累計充入電量"), Panel("平均充電時間")
        self.by_drone, self.duration = ChartWidget(300), ChartWidget(300)
        p2.add(self.by_drone)
        p3.add(self.duration)
        self.add(hbox(p2, p3, spacing=16))
        p4 = Panel("各機體明細", padded=False)
        self.table = DataTable([("無人機", "l", 200), ("充電次數", "r", 110), ("累計充入", "r", 140),
                                ("平均每次", "r", 140), ("佔比", "r", None)])
        self.table.setMinimumHeight(260)
        p4.add(self.table)
        self.add(p4)

    def render(self, s: dict):
        total, sessions = s["totalEnergyWh"], s["totalSessions"]
        self.k_total.set(fmt.fmt_num(total / 1000, 2), "kWh", f"{fmt.fmt_num(total, 0)} Wh")
        self.k_sessions.set(sessions, "次")
        self.k_avg.set(fmt.fmt_num(total / sessions if sessions else 0, 1), "Wh")
        top = s["byDrone"][0] if s["byDrone"] else None
        self.k_top.set(top["droneName"] if top else "—", "", f"{fmt.fmt_num(top['energyWh'] if top else None, 0)} Wh",
                       size_pt=15)
        labels = [p["period"] for p in s["trend"]]
        self.trend.category_chart(labels, [
            Series("充入電量 Wh", [p["energyWh"] for p in s["trend"]], "bar", fmt.OK),
            Series("充電次數", [p["sessions"] for p in s["trend"]], "line", fmt.WARN, axis=1, marker=True),
        ], ylabels=("Wh", "次數"))
        if s["byDrone"]:
            items = list(reversed(s["byDrone"]))
            self.by_drone.hbar_chart([d["droneName"] for d in items], [d["energyWh"] for d in items], fmt.ACCENT, "Wh")
        else:
            self.by_drone.empty("此區間沒有充電記錄")
        self.duration.category_chart(labels, [Series("平均充電時間", [p["avgDurationMinutes"] or None for p in s["trend"]],
                                                     "area", fmt.ACCENT_2)], ylabels=("分鐘", ""), unit="分")
        t = self.table
        t.reset_rows(len(s["byDrone"]), "此區間沒有充電記錄")
        for i, d in enumerate(s["byDrone"]):
            t.set_text(i, 0, d["droneName"])
            t.set_text(i, 1, d["sessions"], mono=True)
            t.set_text(i, 2, f"{fmt.fmt_num(d['energyWh'], 1)} Wh", mono=True)
            t.set_text(i, 3, f"{fmt.fmt_num(d['energyWh'] / max(1, d['sessions']), 1)} Wh", mono=True)
            t.set_text(i, 4, f"{fmt.fmt_num(d['energyWh'] / total * 100 if total else 0, 1)}%", mono=True)
