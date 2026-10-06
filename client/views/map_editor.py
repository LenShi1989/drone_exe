"""地圖編輯:新增點位 · 新增路徑 · 儲存路線 (儲存時自動建立版本快照)。"""
from __future__ import annotations

import math

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QButtonGroup, QFrame, QLabel, QScrollArea, QWidget

from .. import fmt
from ..api import api, error_message
from ..fmt import MapPointType, RouteStatus, WaypointAction
from ..tasks import run_async
from ..widgets.common import (
    DataTable, FormDialog, Panel, button, combo, confirm, field, float_spin, full, hbox, icon_button, int_spin, label,
    line_edit, tag, tags_cell, toast, vbox,
)
from ..widgets.map_view import GeoLine, GeoMarker, MapWidget
from .base import Page


def haversine(a: dict, b: dict) -> float:
    r = 6371000
    d_lat = math.radians(b["latitude"] - a["latitude"])
    d_lng = math.radians(b["longitude"] - a["longitude"])
    h = (math.sin(d_lat / 2) ** 2
         + math.cos(math.radians(a["latitude"])) * math.cos(math.radians(b["latitude"])) * math.sin(d_lng / 2) ** 2)
    return r * 2 * math.atan2(math.sqrt(h), math.sqrt(1 - h))


class MapEditorPage(Page):
    title = "地圖編輯"
    subtitle = "新增點位 · 新增路徑 · 儲存路線 (儲存時自動建立版本快照)"

    def __init__(self, main):
        super().__init__(main)
        self.points: list[dict] = []
        self.routes: list[dict] = []
        self.mode = "browse"
        self.route_id: int | None = None
        self.waypoints: list[dict] = []
        self.dirty = False
        self.saving = False

        # 模式切換
        self.mode_group = QButtonGroup(self)
        mode_box = QWidget()
        mode_lay = hbox(spacing=0)
        for key, text in (("browse", "瀏覽"), ("point", "新增點位"), ("path", "新增路徑")):
            b = button(text)
            b.setCheckable(True)
            b.setProperty("mode", True)
            b.setProperty("key", key)
            self.mode_group.addButton(b)
            mode_lay.addWidget(b)
        mode_box.setLayout(mode_lay)
        self.mode_group.buttonClicked.connect(lambda b: self.set_mode(b.property("key")))
        self.add_head_action(mode_box)

        # 左:地圖 + 航線清單
        self.map = MapWidget(min_height=520)
        self.map.mapClicked.connect(self._on_map_click)
        self.map.markerDragged.connect(self._on_marker_drag)
        self.hint = QFrame()
        self.hint.setObjectName("Hud")
        self.hint_label = label("", small=True, wrap=True)
        self.hint_label.setFixedWidth(230)
        self.hint.setLayout(vbox(self.hint_label, margins=(12, 9, 12, 9)))
        self.map.add_overlay(self.hint, "tl")

        routes_panel = Panel("航線清單", padded=False)
        routes_panel.add_action(button("＋ 新航線", "primary", "sm", self.new_route))
        self.route_table = DataTable([("名稱", "l", 260), ("狀態", "l", 90), ("版本", "r", 60), ("航點", "r", 60),
                                      ("距離", "r", 90), ("預估", "r", 70), ("", "r", None)])
        self.route_table.setMinimumHeight(260)
        routes_panel.add(self.route_table)
        left = vbox(self.map, routes_panel, spacing=16)

        # 右:航線編輯 + 航點順序 + 點位清單
        edit_panel = Panel("新航線")
        self.edit_panel = edit_panel
        self.dirty_tag = tag("未儲存", "warn")
        self.dirty_tag.hide()
        edit_panel.add_action(self.dirty_tag)
        self.name_edit = line_edit()
        self.desc_edit = line_edit()
        self.note_edit = line_edit(placeholder="例:新增倉庫頂拍照點")
        self.name_edit.textEdited.connect(self._mark_dirty)
        self.desc_edit.textEdited.connect(self._mark_dirty)
        self.summary = label("", mono=True, small=True)
        self.save_btn = button("儲存路線", "primary", on_click=self.save_route)
        self.publish_btn = button("發布", on_click=self.publish_route)
        edit_panel.add(field("航線名稱", self.name_edit))
        edit_panel.add(field("說明", self.desc_edit))
        edit_panel.add(field("變更備註 (寫入歷史版本)", self.note_edit))
        edit_panel.add(self.summary)
        edit_panel.add(hbox(self.save_btn, self.publish_btn, button("清空", "ghost", on_click=self.new_route), "stretch"))

        wp_panel = Panel("航點順序", padded=False)
        self.wp_box = QWidget()
        self.wp_lay = vbox(spacing=0)
        self.wp_box.setLayout(self.wp_lay)
        wp_scroll = QScrollArea()
        wp_scroll.setWidgetResizable(True)
        wp_scroll.setWidget(self.wp_box)
        wp_scroll.setMinimumHeight(240)
        wp_panel.add(wp_scroll)

        pt_panel = Panel("點位清單", padded=False)
        pt_panel.add_action(button("地圖上新增", "ghost", "sm", lambda: self.set_mode("point")))
        self.pt_box = QWidget()
        self.pt_lay = vbox(spacing=0)
        self.pt_box.setLayout(self.pt_lay)
        pt_scroll = QScrollArea()
        pt_scroll.setWidgetResizable(True)
        pt_scroll.setWidget(self.pt_box)
        pt_scroll.setMinimumHeight(260)
        pt_panel.add(pt_scroll)

        right = QWidget()
        right.setFixedWidth(400)
        right.setLayout(vbox(edit_panel, wp_panel, pt_panel, spacing=16))
        self.add(hbox(left, right, spacing=16))

        self.set_mode("browse")
        self.new_route(confirm_discard=False, keep_mode=True)

    # ------------------------------------------------------------------ 載入

    def on_show(self):
        def load():
            return api.map_points(), api.routes()

        def ok(res):
            self.points, self.routes = res
            self._render_points()
            self._render_routes()
            self.redraw()

        run_async(load, ok, self.fail("載入地圖資料失敗"), owner=self)

    def _reload_routes(self):
        run_async(api.routes, lambda r: (setattr(self, "routes", r), self._render_routes()), owner=self)

    def _reload_points(self):
        def ok(pts):
            self.points = pts
            self._render_points()
            self.redraw()
        run_async(api.map_points, ok, owner=self)

    # ------------------------------------------------------------------ 模式 / 互動

    def set_mode(self, mode: str):
        self.mode = mode
        for b in self.mode_group.buttons():
            b.setChecked(b.property("key") == mode)
        self.map.setClickable(mode != "browse")
        hints = {
            "point": "<b style='color:#00e5ff'>新增點位模式</b><br>點擊地圖任一位置以建立點位",
            "path": "<b style='color:#00e5ff'>新增路徑模式</b><br>依序點擊地圖加入航點,可拖曳航點微調",
            "browse": "<span style='color:#5d738f'>瀏覽模式 — 切換上方按鈕開始編輯</span>",
        }
        self.hint_label.setText(hints[mode])
        self.hint.adjustSize()

    def _on_map_click(self, lat: float, lng: float):
        if self.mode == "point":
            self.edit_point(None, lat=round(lat, 7), lng=round(lng, 7))
        elif self.mode == "path":
            self.waypoints.append({"sequence": len(self.waypoints) + 1, "latitude": round(lat, 7),
                                   "longitude": round(lng, 7), "altitudeM": 30, "action": WaypointAction.FlyThrough,
                                   "hoverSeconds": 0, "mapPointId": None})
            self._mark_dirty()
            self._render_waypoints()
            self.redraw()

    def _on_marker_drag(self, marker_id: str, lat: float, lng: float):
        if not marker_id.startswith("wp-"):
            self.redraw()  # 點位不可拖曳,還原位置
            return
        idx = int(marker_id[3:])
        if 0 <= idx < len(self.waypoints):
            w = self.waypoints[idx]
            w["latitude"], w["longitude"], w["mapPointId"] = round(lat, 7), round(lng, 7), None
            self._mark_dirty()
            self._render_waypoints()
            self.redraw()

    def _mark_dirty(self, *_):
        self.dirty = True
        self.dirty_tag.show()
        self._update_summary()

    # ------------------------------------------------------------------ 地圖圖層

    def redraw(self):
        markers = [GeoMarker(f"point-{p['id']}", p["latitude"], p["longitude"],
                             fmt.POINT_TYPE_COLOR.get(p["pointType"], fmt.ACCENT), p["name"]) for p in self.points]
        markers += [GeoMarker(f"wp-{i}", w["latitude"], w["longitude"], fmt.ACCENT, f"#{i + 1}", draggable=True)
                    for i, w in enumerate(self.waypoints)]
        lines = []
        if len(self.waypoints) >= 2:
            lines.append(GeoLine("editing", [(w["latitude"], w["longitude"]) for w in self.waypoints], fmt.ACCENT, 3))
        self.map.set_data(markers, lines)

    # ------------------------------------------------------------------ 航線編輯

    def _total_distance(self) -> float:
        return sum(haversine(a, b) for a, b in zip(self.waypoints, self.waypoints[1:]))

    def _update_summary(self):
        dist = self._total_distance()
        hover = sum(w["hoverSeconds"] for w in self.waypoints)
        minutes = max(1, math.ceil((dist / 9 + hover) / 60))
        self.summary.setText(f"<span style='color:#5d738f'>航點</span> {len(self.waypoints)}　　"
                             f"<span style='color:#5d738f'>距離</span> {fmt.fmt_distance(dist)}　　"
                             f"<span style='color:#5d738f'>預估用時</span> {minutes} 分")
        self.save_btn.setEnabled(len(self.waypoints) >= 2 and not self.saving)
        self.publish_btn.setVisible(self.route_id is not None)
        self.edit_panel.set_title(f"編輯航線 #{self.route_id}" if self.route_id else "新航線")

    def new_route(self, confirm_discard: bool = False, keep_mode: bool = False):
        self.route_id = None
        self.name_edit.setText(f"新航線 {len(self.routes) + 1}")
        self.desc_edit.clear()
        self.note_edit.clear()
        self.waypoints = []
        self.dirty = False
        self.dirty_tag.hide()
        if not keep_mode:
            self.set_mode("path")
        self._render_waypoints()
        self._render_routes()
        self.redraw()

    def load_route(self, route_id: int):
        if self.dirty and not confirm(self, "目前航線有未儲存的變更,要放棄嗎?"):
            return

        def ok(r):
            self.route_id = r["id"]
            self.name_edit.setText(r["name"])
            self.desc_edit.setText(r.get("description") or "")
            self.note_edit.clear()
            self.waypoints = [{k: w[k] for k in ("sequence", "latitude", "longitude", "altitudeM", "action",
                                                  "hoverSeconds", "mapPointId")} for w in r["waypoints"]]
            self.dirty = False
            self.dirty_tag.hide()
            self.set_mode("browse")
            self._render_waypoints()
            self._render_routes()
            self.redraw()
            self.map.fit()

        run_async(lambda: api.route(route_id), ok, self.fail("載入航線失敗"), owner=self)

    def _move(self, index: int, delta: int):
        target = index + delta
        if 0 <= target < len(self.waypoints):
            self.waypoints[index], self.waypoints[target] = self.waypoints[target], self.waypoints[index]
            self._renumber()

    def _remove(self, index: int):
        del self.waypoints[index]
        self._renumber()

    def _renumber(self):
        for i, w in enumerate(self.waypoints):
            w["sequence"] = i + 1
        self._mark_dirty()
        self._render_waypoints()
        self.redraw()

    def _render_waypoints(self):
        while self.wp_lay.count():
            item = self.wp_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self.waypoints:
            empty = label("切換「新增路徑」後點擊地圖,或從下方點位清單加入", faint=True, small=True, wrap=True)
            empty.setObjectName("Empty")
            self.wp_lay.addWidget(empty)
        for i, w in enumerate(self.waypoints):
            self.wp_lay.addWidget(self._waypoint_row(i, w))
        self.wp_lay.addStretch(1)
        self._update_summary()

    def _waypoint_row(self, i: int, w: dict) -> QWidget:
        row = QFrame()
        row.setStyleSheet("QFrame{border-bottom:1px solid rgba(148,178,214,0.10)}")
        seq = QLabel(str(i + 1))
        seq.setFixedSize(26, 26)
        seq.setAlignment(Qt.AlignCenter)
        seq.setStyleSheet("border:1px solid #00e5ff;border-radius:13px;color:#00e5ff;font-family:Consolas;"
                          "font-weight:600")
        coord = label(f"{w['latitude']:.5f}, {w['longitude']:.5f}", mono=True, small=True)
        action = combo([(t, k) for k, t in fmt.WAYPOINT_ACTION_TEXT.items()], w["action"])
        alt = int_spin(int(w["altitudeM"]), 0, 500, " m")
        alt.setToolTip("高度 (m)")
        hover = int_spin(int(w["hoverSeconds"]), 0, 600, " s")
        hover.setToolTip("懸停秒數")
        for wd in (action, alt, hover):
            wd.setFixedWidth(82)

        def set_val(key, value):
            w[key] = value
            self._mark_dirty()

        action.currentIndexChanged.connect(lambda _i: set_val("action", action.currentData()))
        alt.valueChanged.connect(lambda v: set_val("altitudeM", v))
        hover.valueChanged.connect(lambda v: set_val("hoverSeconds", v))
        ops = [icon_button("▲", "上移", lambda: self._move(i, -1)), icon_button("▼", "下移", lambda: self._move(i, 1)),
               icon_button("✕", "移除", lambda: self._remove(i), danger=True)]
        row.setLayout(hbox(seq, vbox(coord, hbox(action, alt, hover, spacing=5), spacing=4), "stretch",
                           vbox(hbox(*ops, spacing=3)), spacing=10, margins=(10, 7, 10, 7)))
        return row

    def save_route(self):
        if len(self.waypoints) < 2:
            toast("航線至少需要 2 個航點", "warn")
            return
        if not self.name_edit.text().strip():
            toast("請填寫航線名稱", "warn")
            return
        body = {"name": self.name_edit.text().strip(), "description": self.desc_edit.text() or None,
                "changeNote": self.note_edit.text() or None,
                "waypoints": [{**w, "sequence": i + 1} for i, w in enumerate(self.waypoints)]}
        self.saving = True
        self._update_summary()
        route_id = self.route_id

        def ok(saved):
            self.saving = False
            self.route_id = saved["id"]
            self.note_edit.clear()
            self.dirty = False
            self.dirty_tag.hide()
            self._update_summary()
            self._reload_routes()
            toast(f"航線已儲存 (v{saved['version']})", "success")

        def err(e):
            self.saving = False
            self._update_summary()
            toast(error_message(e, "儲存航線失敗"), "error")

        run_async(lambda: api.route_update(route_id, body) if route_id else api.route_create(body), ok, err, owner=self)

    def publish_route(self):
        if not self.route_id:
            return
        rid = self.route_id

        def ok(_):
            self._reload_routes()
            toast("航線已發布,可供工單指派", "success")

        run_async(lambda: api.route_publish(rid), ok, self.fail("發布失敗"), owner=self)

    def archive_route(self, route_id: int):
        if not confirm(self, "封存後將無法再編輯,確定?"):
            return

        def ok(_):
            self._reload_routes()
            toast("航線已封存", "success")

        run_async(lambda: api.route_archive(route_id), ok, self.fail("封存失敗"), owner=self)

    def delete_route(self, r: dict):
        if not confirm(self, f"確定刪除航線「{r['name']}」?歷史版本會一併移除。"):
            return

        def ok(_):
            if self.route_id == r["id"]:
                self.new_route(keep_mode=True)
            self._reload_routes()
            toast("航線已刪除", "success")

        run_async(lambda: api.route_delete(r["id"]), ok, self.fail("刪除失敗"), owner=self)

    def _render_routes(self):
        t = self.route_table
        t.reset_rows(len(self.routes), "尚無航線")
        for i, r in enumerate(self.routes):
            t.set_two_line(i, 0, r["name"], r.get("description") or "", sub_mono=False)
            t.setCellWidget(i, 1, tags_cell(tag(fmt.ROUTE_STATUS_TEXT[r["status"]], fmt.ROUTE_STATUS_TAG[r["status"]])))
            t.set_text(i, 2, f"v{r['version']}", mono=True)
            t.set_text(i, 3, r["waypointCount"], mono=True)
            t.set_text(i, 4, fmt.fmt_distance(r["totalDistanceM"]), mono=True)
            t.set_text(i, 5, f"{r['estimatedMinutes']} 分", mono=True)
            btns = [button("載入", "ghost", "sm", lambda rid=r["id"]: self.load_route(rid))]
            if r["status"] != RouteStatus.Archived:
                btns.append(button("封存", "ghost", "sm", lambda rid=r["id"]: self.archive_route(rid)))
            btns.append(button("刪除", "danger", "sm", lambda rr=r: self.delete_route(rr)))
            t.set_actions(i, 6, btns)
            if r["id"] == self.route_id:
                t.selectRow(i)

    # ------------------------------------------------------------------ 點位

    def _render_points(self):
        while self.pt_lay.count():
            item = self.pt_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self.points:
            empty = label("尚無點位", faint=True, small=True)
            empty.setObjectName("Empty")
            self.pt_lay.addWidget(empty)
        for p in self.points:
            row = QFrame()
            row.setStyleSheet("QFrame{border-bottom:1px solid rgba(148,178,214,0.10)}")
            dot = QLabel("●")
            dot.setStyleSheet(f"color:{fmt.POINT_TYPE_COLOR.get(p['pointType'], fmt.ACCENT)};border:none")
            info = vbox(label(p["name"], small=True),
                        label(f"{fmt.POINT_TYPE_TEXT.get(p['pointType'], '')} · {p['latitude']:.5f}, "
                              f"{p['longitude']:.5f}", faint=True, small=True, mono=True), spacing=1)
            ops = [icon_button("＋", "加入航線", lambda pp=p: self.append_point(pp)),
                   icon_button("✎", "編輯", lambda pp=p: self.edit_point(pp)),
                   icon_button("✕", "刪除", lambda pp=p: self.remove_point(pp), danger=True)]
            row.setLayout(hbox(dot, info, "stretch", *ops, spacing=6, margins=(10, 6, 10, 6)))
            self.pt_lay.addWidget(row)
        self.pt_lay.addStretch(1)

    def append_point(self, p: dict):
        """把既有點位加入正在編輯的航線。"""
        self.waypoints.append({"sequence": len(self.waypoints) + 1, "latitude": p["latitude"],
                               "longitude": p["longitude"], "altitudeM": p["altitudeM"] or 30,
                               "action": WaypointAction.Land if p["pointType"] == MapPointType.Landing
                               else WaypointAction.FlyThrough, "hoverSeconds": 0, "mapPointId": p["id"]})
        self._mark_dirty()
        self.set_mode("path")
        self._render_waypoints()
        self.redraw()

    def edit_point(self, p: dict | None, lat: float = 0, lng: float = 0):
        dlg = FormDialog(self, "新增點位" if p is None else "編輯點位", "儲存", width=560)
        name = line_edit(p["name"] if p else f"新點位 {len(self.points) + 1}")
        ptype = combo([(t, k) for k, t in fmt.POINT_TYPE_TEXT.items()], p["pointType"] if p else MapPointType.Waypoint)
        lat_s = float_spin(p["latitude"] if p else lat, -90, 90, 7, 0.0001)
        lng_s = float_spin(p["longitude"] if p else lng, -180, 180, 7, 0.0001)
        alt = float_spin(p["altitudeM"] if p else 30, 0, 1000, 1)
        desc = line_edit(p.get("description") or "" if p else "")
        dlg.grid([field("名稱", name), field("類型", ptype), field("緯度", lat_s), field("經度", lng_s),
                  field("高度 (m)", alt), full(field("說明", desc))])

        def submit():
            if not name.text().strip():
                toast("請填寫點位名稱", "warn")
                return
            body = {"name": name.text().strip(), "pointType": ptype.currentData(), "latitude": lat_s.value(),
                    "longitude": lng_s.value(), "altitudeM": alt.value(), "description": desc.text() or None}
            dlg.set_busy(True)

            def ok(_):
                dlg.accept()
                self.set_mode("browse")
                toast("點位已儲存", "success")
                self._reload_points()

            def err(e):
                dlg.set_busy(False)
                toast(error_message(e, "儲存點位失敗"), "error")

            run_async(lambda: api.map_point_update(p["id"], body) if p else api.map_point_create(body), ok, err,
                      owner=dlg)

        dlg.on_confirm = submit
        dlg.exec_()

    def remove_point(self, p: dict):
        if not confirm(self, f"確定刪除點位「{p['name']}」?"):
            return

        def ok(_):
            toast("點位已刪除", "success")
            self._reload_points()

        run_async(lambda: api.map_point_delete(p["id"]), ok, self.fail("刪除失敗"), owner=self)

