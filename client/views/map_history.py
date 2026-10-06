"""歷史地圖:每次儲存路線都會產生版本快照 (GeoJSON),可在此回放任一版本。"""
from __future__ import annotations

import json

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QListWidget, QListWidgetItem, QWidget

from .. import fmt
from ..api import api
from ..tasks import run_async
from ..widgets.common import DataTable, Panel, combo, field, hbox, label, tag, tags_cell, vbox
from ..widgets.map_view import GeoLine, GeoMarker, MapWidget
from .base import Page


def parse_snapshot(raw: str) -> tuple[list[dict], list[tuple[float, float]]]:
    try:
        doc = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return [], []
    waypoints, path = [], []
    for f in doc.get("features", []):
        geom = f.get("geometry") or {}
        props = f.get("properties") or {}
        if geom.get("type") == "LineString":
            path = [(lat, lng) for lng, lat in geom.get("coordinates", [])]
        elif geom.get("type") == "Point":
            lng, lat = geom.get("coordinates", [0, 0])
            waypoints.append({"sequence": int(props.get("sequence", 0)), "altitudeM": props.get("altitudeM", 0),
                              "action": str(props.get("action", "")), "hoverSeconds": props.get("hoverSeconds", 0),
                              "lat": lat, "lng": lng})
    waypoints.sort(key=lambda w: w["sequence"])
    return waypoints, path


class RevisionItem(QFrame):
    def __init__(self, rev: dict):
        super().__init__()
        name = label(rev["routeName"], bold=True)
        ver = tag(f"v{rev['version']}", "accent")
        note = label(rev.get("changeNote") or "(無備註)", faint=True, small=True, wrap=True)
        foot = hbox(label(fmt.fmt_datetime(rev["createdAt"]), faint=True, small=True, mono=True), "stretch",
                    label(f"{rev['waypointCount']} 航點 · {fmt.fmt_distance(rev['totalDistanceM'])}", faint=True,
                          small=True, mono=True))
        items = [hbox(name, "stretch", ver), note, foot]
        if rev.get("createdByName"):
            items.append(label(f"by {rev['createdByName']}", faint=True, small=True))
        self.setLayout(vbox(*items, spacing=3, margins=(12, 9, 12, 9)))
        self.setAttribute(Qt.WA_TransparentForMouseEvents)


class MapHistoryPage(Page):
    title = "歷史地圖"
    subtitle = "每次儲存路線都會產生版本快照 (GeoJSON),可在此回放任一版本"

    def __init__(self, main):
        super().__init__(main)
        self.routes: list[dict] = []
        self.revisions: list[dict] = []
        self.current: dict | None = None

        self.route_filter = combo([("全部航線", None)])
        self.route_filter.setMinimumWidth(220)
        self.route_filter.currentIndexChanged.connect(self._filter_changed)
        self.add_head_action(field("篩選航線", self.route_filter))

        rev_panel = Panel("版本紀錄", padded=False)
        rev_panel.setFixedWidth(340)
        self.rev_list = QListWidget()
        self.rev_list.setMinimumHeight(640)
        self.rev_list.currentRowChanged.connect(self._open_revision)
        rev_panel.add(self.rev_list)

        self.map = MapWidget(min_height=440)
        self.hint = QFrame()
        self.hint.setObjectName("Hud")
        self.hint_label = label("從左側選擇一個版本以回放", small=True, faint=True)
        self.hint.setLayout(vbox(self.hint_label, margins=(12, 8, 12, 8)))
        self.map.add_overlay(self.hint, "tl")

        self.detail_panel = Panel("航點明細", padded=False)
        self.wp_table = DataTable([("#", "r", 50), ("座標", "l", 230), ("高度", "r", 80), ("動作", "l", 90),
                                   ("懸停", "r", None)])
        self.wp_table.setMinimumHeight(220)
        self.detail_panel.add(self.wp_table)
        self.detail_panel.hide()

        status_panel = Panel("航線現況", padded=False)
        self.route_table = DataTable([("航線", "l", 260), ("狀態", "l", 100), ("目前版本", "r", 90), ("距離", "r", None)])
        self.route_table.setMinimumHeight(200)
        status_panel.add(self.route_table)

        right = QWidget()
        right.setLayout(vbox(self.map, self.detail_panel, status_panel, spacing=16))
        self.add(hbox(rev_panel, right, spacing=16))

    def on_show(self):
        def load():
            return api.routes(), api.all_revisions(200)

        def ok(res):
            self.routes, revisions = res
            self.route_filter.blockSignals(True)
            current = self.route_filter.currentData()
            self.route_filter.clear()
            self.route_filter.addItem("全部航線", None)
            for r in self.routes:
                self.route_filter.addItem(r["name"], r["id"])
            idx = self.route_filter.findData(current)
            self.route_filter.setCurrentIndex(max(0, idx))
            self.route_filter.blockSignals(False)
            self._render_routes()
            if current is None:
                self._set_revisions(revisions)
            else:
                self._filter_changed()

        run_async(load, ok, self.fail("載入歷史地圖失敗"), owner=self)

    def _filter_changed(self, *_):
        route_id = self.route_filter.currentData()
        run_async(lambda: api.all_revisions(200) if route_id is None else api.route_revisions(route_id),
                  self._set_revisions, self.fail("載入版本清單失敗"), owner=self)

    def _set_revisions(self, revisions: list[dict]):
        self.revisions = revisions
        self.rev_list.blockSignals(True)
        self.rev_list.clear()
        for rev in revisions:
            item = QListWidgetItem()
            widget = RevisionItem(rev)
            item.setSizeHint(widget.sizeHint())
            self.rev_list.addItem(item)
            self.rev_list.setItemWidget(item, widget)
        if not revisions:
            self.rev_list.addItem("尚無版本紀錄")
        self.rev_list.blockSignals(False)
        self.current = None
        self._show_current()

    def _open_revision(self, row: int):
        if row < 0 or row >= len(self.revisions):
            return
        rev = self.revisions[row]
        self.hint_label.setText("載入快照…")
        run_async(lambda: api.route_revision(rev["routeId"], rev["version"]),
                  lambda d: (setattr(self, "current", d), self._show_current()),
                  self.fail("載入版本快照失敗"), owner=self)

    def _show_current(self):
        cur = self.current
        if cur is None:
            self.hint_label.setText("<span style='color:#5d738f'>從左側選擇一個版本以回放</span>")
            self.hint.adjustSize()
            self.detail_panel.hide()
            self.map.set_data([], [])
            return
        waypoints, path = parse_snapshot(cur["snapshotJson"])
        self.hint_label.setText(f"<b>{cur['routeName']}</b> <span style='color:#00e5ff'>v{cur['version']}</span>"
                                f"<br><span style='color:#5d738f'>{fmt.fmt_datetime(cur['createdAt'])}</span>")
        self.hint.adjustSize()
        markers = [GeoMarker(f"wp-{w['sequence']}", w["lat"], w["lng"], fmt.ACCENT_2, f"#{w['sequence']}")
                   for w in waypoints]
        lines = [GeoLine("snapshot", path, fmt.ACCENT_2, 3)] if len(path) >= 2 else []
        self.map.set_data(markers, lines, fit=True)
        self.detail_panel.set_title(f"v{cur['version']} 航點明細")
        t = self.wp_table
        t.reset_rows(len(waypoints))
        for i, w in enumerate(waypoints):
            t.set_text(i, 0, w["sequence"], mono=True)
            t.set_text(i, 1, f"{w['lat']:.6f}, {w['lng']:.6f}", mono=True)
            t.set_text(i, 2, f"{w['altitudeM']} m", mono=True)
            t.set_text(i, 3, fmt.WAYPOINT_ACTION_BY_NAME.get(w["action"], w["action"]))
            t.set_text(i, 4, f"{w['hoverSeconds']} s", mono=True)
        self.detail_panel.show()

    def _render_routes(self):
        t = self.route_table
        t.reset_rows(len(self.routes), "尚無航線")
        for i, r in enumerate(self.routes):
            t.set_text(i, 0, r["name"])
            t.setCellWidget(i, 1, tags_cell(tag(fmt.ROUTE_STATUS_TEXT[r["status"]], fmt.ROUTE_STATUS_TAG[r["status"]])))
            t.set_text(i, 2, f"v{r['version']}", mono=True)
            t.set_text(i, 3, fmt.fmt_distance(r["totalDistanceM"]), mono=True)
