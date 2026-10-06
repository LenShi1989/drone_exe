"""系統管理:帳號管理、角色管理 (勾選權限即設定側邊欄,附側邊欄預覽)。"""
from __future__ import annotations

from PyQt5.QtCore import QSize
from PyQt5.QtWidgets import QCheckBox, QFrame, QGridLayout, QLineEdit, QListWidget, QListWidgetItem, QWidget

from .. import fmt
from ..api import api, error_message
from ..tasks import run_async
from ..widgets.common import (
    DataTable, FormDialog, Pager, Panel, button, checkbox, clear_layout, combo, confirm, field, full, hbox, label,
    line_edit, tag, tags_cell, toast, toolbar, vbox,
)
from .base import Page


# ============================================================ 帳號管理

class UserPage(Page):
    title = "帳號管理"
    subtitle = "使用者帳號與角色指派。角色決定側邊欄可見的功能"

    def __init__(self, main):
        super().__init__(main)
        self.rows: list[dict] = []
        self.roles: list[dict] = []
        self.add_head_action(button("＋ 新增帳號", "primary", on_click=lambda: self.open_edit(None)))
        panel = Panel(padded=False)
        self.keyword = line_edit(placeholder="帳號 / 姓名 / Email")
        self.keyword.returnPressed.connect(self.search)
        self.role = combo([("全部", None)])
        self.active = combo([("全部", None), ("啟用", True), ("停用", False)])
        self.role.currentIndexChanged.connect(self.search)
        self.active.currentIndexChanged.connect(self.search)
        panel.add(toolbar(field("關鍵字", self.keyword), field("角色", self.role), field("狀態", self.active),
                          button("查詢", on_click=self.search), "stretch"))
        self.table = DataTable([("帳號", "l", 120), ("姓名", "l", 110), ("Email", "l", 200), ("角色", "l", 110),
                                ("狀態", "l", 130), ("最後登入", "l", 140), ("建立日期", "l", 110), ("", "r", None)])
        self.table.setMinimumHeight(520)
        panel.add(self.table)
        self.pager = Pager()
        self.pager.changed.connect(lambda *_: self.load())
        panel.add(self.pager)
        self.add(panel)

    def on_show(self):
        def ok(roles):
            self.roles = roles
            current = self.role.currentData()
            self.role.blockSignals(True)
            self.role.clear()
            self.role.addItem("全部", None)
            for r in roles:
                self.role.addItem(r["name"], r["id"])
            self.role.setCurrentIndex(max(0, self.role.findData(current)))
            self.role.blockSignals(False)

        if api.can("system.role"):
            run_async(api.roles, ok, lambda _e: None, owner=self)
        self.load()

    def search(self, *_):
        self.pager.reset()
        self.load()

    def load(self):
        active = self.active.currentData()
        q = {"page": self.pager.page, "pageSize": self.pager.page_size, "keyword": self.keyword.text().strip() or None,
             "roleId": self.role.currentData(), "isActive": None if active is None else str(active).lower()}

        def ok(res):
            self.rows = res["items"]
            self.pager.set_total(res["total"])
            self._render()

        run_async(lambda: api.users(**q), ok, self.fail("載入帳號清單失敗"), owner=self)

    def _render(self):
        me = (api.user or {}).get("id")
        t = self.table
        t.reset_rows(len(self.rows))
        for i, u in enumerate(self.rows):
            t.set_text(i, 0, u["username"], mono=True)
            t.set_text(i, 1, u["displayName"])
            t.set_text(i, 2, u["email"], dim=True)
            t.setCellWidget(i, 3, tags_cell(tag(u["roleName"], "accent" if u["roleCode"] == "admin" else "info")))
            tags = [tag("啟用", "ok") if u["isActive"] else tag("停用", "dim")]
            if u["isLocked"]:
                tags.append(tag("鎖定中", "danger"))
            t.setCellWidget(i, 4, tags_cell(*tags))
            t.set_text(i, 5, fmt.fmt_datetime(u["lastLoginAt"]), faint=True)
            t.set_text(i, 6, fmt.fmt_date(u["createdAt"]), faint=True)
            btns = [button("編輯", "ghost", "sm", lambda uu=u: self.open_edit(uu)),
                    button("重設密碼", "ghost", "sm", lambda uu=u: self.open_reset(uu))]
            if u["id"] != me:
                btns.append(button("停用" if u["isActive"] else "啟用", "ghost", "sm", lambda uu=u: self.toggle(uu)))
                btns.append(button("刪除", "danger", "sm", lambda uu=u: self.remove(uu)))
            t.set_actions(i, 7, btns)

    def open_edit(self, u: dict | None):
        if not self.roles:
            toast("無法取得角色清單 (需「角色管理」權限才能指派角色)", "warn")
            return
        dlg = FormDialog(self, "新增帳號" if u is None else f"編輯帳號 {u['username']}", "儲存", width=560)
        username = line_edit(u["username"] if u else "", mono=True)
        username.setEnabled(u is None)
        name = line_edit(u["displayName"] if u else "")
        email = line_edit(u["email"] if u else "")
        password = QLineEdit()
        password.setEchoMode(QLineEdit.Password)
        role = combo([(r["name"], r["id"]) for r in self.roles], u["roleId"] if u else None)
        active = checkbox("啟用", u["isActive"] if u else True)
        fields = [field("帳號 *", username), field("姓名 *", name), full(field("Email *", email))]
        if u is None:
            fields.append(field("密碼 * (至少 8 字元)", password))
        fields += [field("角色 *", role), field(" ", active)]
        dlg.grid(fields)

        def submit():
            if not (username.text().strip() and name.text().strip() and email.text().strip()):
                toast("請填寫帳號、姓名與 Email", "warn")
                return
            if u is None and len(password.text()) < 8:
                toast("密碼至少 8 個字元", "warn")
                return
            if u is None:
                body = {"username": username.text().strip(), "displayName": name.text().strip(),
                        "email": email.text().strip(), "password": password.text(), "roleId": role.currentData(),
                        "isActive": active.isChecked()}
            else:
                body = {"displayName": name.text().strip(), "email": email.text().strip(),
                        "roleId": role.currentData(), "isActive": active.isChecked()}
            dlg.set_busy(True)

            def ok(_):
                dlg.accept()
                toast("帳號已儲存", "success")
                self.load()

            def err(e):
                dlg.set_busy(False)
                toast(error_message(e, "儲存帳號失敗"), "error")

            run_async(lambda: api.user_update(u["id"], body) if u else api.user_create(body), ok, err, owner=dlg)

        dlg.on_confirm = submit
        dlg.exec_()

    def open_reset(self, u: dict):
        dlg = FormDialog(self, f"重設密碼 — {u['username']}", "重設", width=420)
        pwd = QLineEdit()
        pwd.setEchoMode(QLineEdit.Password)
        dlg.add(field("新密碼 (至少 8 字元)", pwd))

        def submit():
            if len(pwd.text()) < 8:
                toast("密碼至少 8 個字元", "warn")
                return
            dlg.set_busy(True)

            def ok(_):
                dlg.accept()
                toast("密碼已重設,該帳號的登入狀態已失效", "success")
                self.load()

            def err(e):
                dlg.set_busy(False)
                toast(error_message(e, "重設密碼失敗"), "error")

            run_async(lambda: api.user_reset_password(u["id"], pwd.text()), ok, err, owner=dlg)

        dlg.on_confirm = submit
        dlg.exec_()

    def toggle(self, u: dict):
        def ok(res):
            toast("帳號已啟用" if res["isActive"] else "帳號已停用", "success")
            self.load()
        run_async(lambda: api.user_toggle_active(u["id"]), ok, self.fail("操作失敗"), owner=self)

    def remove(self, u: dict):
        if not confirm(self, f"確定刪除帳號「{u['username']}」?此操作無法復原。"):
            return

        def ok(_):
            toast("帳號已刪除", "success")
            self.load()
        run_async(lambda: api.user_delete(u["id"]), ok, self.fail("刪除失敗"), owner=self)


# ============================================================ 角色管理

def filter_menu(nodes: list[dict], granted: set[str]) -> list[dict]:
    """與後端 build_menu 相同規則:葉節點需權限,群組沒有可見子節點就整組隱藏。"""
    out = []
    for n in nodes:
        children = filter_menu(n.get("children", []), granted)
        is_group = not n.get("path")
        if is_group and not children:
            continue
        if not is_group and n.get("permissionCode") and n["permissionCode"] not in granted:
            continue
        out.append({**n, "children": children})
    return out


def render_menu_preview(layout, nodes: list[dict]) -> None:
    clear_layout(layout)
    if not nodes:
        empty = label("此角色沒有任何可見的選單", faint=True, small=True)
        empty.setObjectName("Empty")
        layout.addWidget(empty)
    for n in nodes:
        layout.addWidget(label(f"▸ {n['title']}" if not n.get("path") else f"• {n['title']}", small=True,
                               bold=not n.get("path")))
        for c in n.get("children", []):
            layout.addWidget(label(f"      {c['title']}", small=True, dim=True))
    layout.addStretch(1)


class RolePage(Page):
    title = "角色管理"
    subtitle = "勾選權限即決定該角色的側邊欄可見範圍;後端 API 也以同一組權限碼把關"

    def __init__(self, main):
        super().__init__(main)
        self.roles: list[dict] = []
        self.permissions: list[dict] = []
        self.menus: list[dict] = []
        self.selected_id: int | None = None
        self.add_head_action(button("＋ 新增角色", "primary", on_click=lambda: self.open_edit(None)))

        list_panel = Panel("角色清單", padded=False)
        list_panel.setFixedWidth(300)
        self.role_list = QListWidget()
        self.role_list.setMinimumHeight(520)
        self.role_list.currentRowChanged.connect(self._select_row)
        list_panel.add(self.role_list)

        self.detail = Panel("角色詳情")
        self.detail_body = vbox(spacing=10)
        self.detail.add(self.detail_body)

        preview_panel = Panel("側邊欄預覽")
        preview_panel.setFixedWidth(260)
        self.preview_box = vbox(spacing=3)
        preview_panel.add(self.preview_box)

        self.add(hbox(list_panel, self.detail, preview_panel, spacing=16))

    def on_show(self):
        def load():
            return api.roles(), api.permissions(), api.role_menus()

        def ok(res):
            self.roles, self.permissions, self.menus = res
            self.role_list.blockSignals(True)
            self.role_list.clear()
            for r in self.roles:
                item = QListWidgetItem(f"{r['name']}\n{r['code']} · {r['userCount']} 個帳號"
                                       + ("  · 系統" if r["isSystem"] else ""))
                item.setSizeHint(QSize(0, 50))
                self.role_list.addItem(item)
            self.role_list.blockSignals(False)
            if self.selected_id is None and self.roles:
                self.selected_id = self.roles[0]["id"]
            idx = next((i for i, r in enumerate(self.roles) if r["id"] == self.selected_id), 0)
            self.role_list.setCurrentRow(idx)
            self._render_detail()

        run_async(load, ok, self.fail("載入角色資料失敗"), owner=self)

    def _select_row(self, row: int):
        if 0 <= row < len(self.roles):
            self.selected_id = self.roles[row]["id"]
            self._render_detail()

    def _groups(self) -> dict[str, list[dict]]:
        groups: dict[str, list[dict]] = {}
        for p in self.permissions:
            groups.setdefault(p["groupName"], []).append(p)
        return groups

    def _render_detail(self):
        clear_layout(self.detail_body)
        role = next((r for r in self.roles if r["id"] == self.selected_id), None)
        if role is None:
            render_menu_preview(self.preview_box, [])
            return
        self.detail.set_title(f"{role['name']} ({role['code']})")
        head = [label(role.get("description") or "(無說明)", dim=True, small=True, wrap=True), "stretch",
                button("編輯權限", "ghost", "sm", lambda: self.open_edit(role))]
        if not role["isSystem"]:
            head.append(button("刪除", "danger", "sm", lambda: self.remove(role)))
        self.detail_body.addLayout(hbox(*head))
        granted = set(role["permissionCodes"])
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(12)
        for i, (group, items) in enumerate(self._groups().items()):
            box = QFrame()
            box.setStyleSheet("QFrame{border:1px solid rgba(148,178,214,0.14);border-radius:4px}"
                              "QLabel{border:none}")
            rows = [label(group, bold=True, small=True)]
            for p in items:
                on = p["code"] in granted
                rows.append(label(f"{'✓' if on else '·'} {p['name']}  <span style='color:#5d738f'>{p['code']}</span>",
                                  small=True, color=fmt.ACCENT if on else fmt.TEXT_FAINT))
            box.setLayout(vbox(*rows, spacing=3, margins=(10, 8, 10, 8)))
            grid.addWidget(box, i // 2, i % 2)
        self.detail_body.addLayout(grid)
        self.detail_body.addStretch(1)
        render_menu_preview(self.preview_box, filter_menu(self.menus, granted))

    def open_edit(self, role: dict | None):
        dlg = FormDialog(self, "新增角色" if role is None else f"編輯角色 — {role['name']}", "儲存", width=1080)
        code = line_edit(role["code"] if role else "", "inspector", mono=True)
        code.setEnabled(not (role and role["isSystem"]))
        name = line_edit(role["name"] if role else "", "巡檢員")
        desc = line_edit(role.get("description") or "" if role else "")
        dlg.grid([field("角色代碼 *", code), field("角色名稱 *", name), full(field("說明", desc))])

        checks: dict[int, QCheckBox] = {}
        granted = set(role["permissionIds"]) if role else set()
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        for i, (group, items) in enumerate(self._groups().items()):
            box = QFrame()
            box.setStyleSheet("QFrame{border:1px solid rgba(148,178,214,0.14);border-radius:4px}"
                              "QCheckBox,QPushButton{border:none}")
            head = button(f"{group}  (全選/取消)", "ghost", "sm")
            rows = [head]
            group_checks = []
            for p in items:
                cb = checkbox(f"{p['name']}  ({p['code']})", p["id"] in granted)
                checks[p["id"]] = cb
                group_checks.append(cb)
                rows.append(cb)

            def toggle(_=False, cbs=group_checks):
                state = not all(c.isChecked() for c in cbs)
                for c in cbs:
                    c.setChecked(state)

            head.clicked.connect(toggle)
            box.setLayout(vbox(*rows, spacing=4, margins=(10, 8, 10, 8)))
            grid.addWidget(box, i // 3, i % 3)

        preview = vbox(spacing=2)
        preview_frame = QFrame()
        preview_frame.setStyleSheet("QFrame{border:1px solid rgba(0,229,255,0.2);border-radius:4px}QLabel{border:none}")
        preview_frame.setLayout(vbox(label("側邊欄預覽", faint=True, small=True), preview, margins=(10, 8, 10, 8)))
        preview_frame.setFixedWidth(200)

        def refresh_preview(*_):
            codes = {p["code"] for p in self.permissions if checks[p["id"]].isChecked()}
            render_menu_preview(preview, filter_menu(self.menus, codes))

        for cb in checks.values():
            cb.toggled.connect(refresh_preview)
        refresh_preview()
        holder = QWidget()
        holder.setLayout(grid)
        dlg.add(hbox(holder, preview_frame, spacing=14))

        def submit():
            if not code.text().strip() or not name.text().strip():
                toast("請填寫角色代碼與名稱", "warn")
                return
            body = {"code": code.text().strip(), "name": name.text().strip(), "description": desc.text().strip() or None,
                    "permissionIds": [pid for pid, cb in checks.items() if cb.isChecked()]}
            dlg.set_busy(True)

            def ok(saved):
                dlg.accept()
                toast("角色已儲存", "success")
                self.selected_id = saved["id"]
                if (api.user or {}).get("roleCode") == saved["code"]:
                    toast("您的角色權限已變更,請重新登入以套用完整設定", "warn", 6000)
                self.on_show()

            def err(e):
                dlg.set_busy(False)
                toast(error_message(e, "儲存角色失敗"), "error")

            run_async(lambda: api.role_update(role["id"], body) if role else api.role_create(body), ok, err, owner=dlg)

        dlg.on_confirm = submit
        dlg.exec_()

    def remove(self, role: dict):
        if not confirm(self, f"確定刪除角色「{role['name']}」?"):
            return

        def ok(_):
            toast("角色已刪除", "success")
            self.selected_id = None
            self.on_show()
        run_async(lambda: api.role_delete(role["id"]), ok, self.fail("刪除失敗"), owner=self)

