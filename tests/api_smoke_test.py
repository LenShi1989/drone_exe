"""
API 冒煙測試:走過每個模組的主要端點與權限把關。需先啟動後端。

    python tests/api_smoke_test.py [http://localhost:5080]
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date, timedelta

import requests

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5080").rstrip("/")
failures: list[str] = []


def check(name: str, cond: bool, detail="") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def login(username: str, password: str) -> tuple[requests.Session, dict]:
    s = requests.Session()
    r = s.post(f"{BASE}/api/auth/login", json={"username": username, "password": password})
    r.raise_for_status()
    data = r.json()
    s.headers["Authorization"] = f"Bearer {data['accessToken']}"
    return s, data


def main() -> int:
    check("health", requests.get(f"{BASE}/health").json()["status"] == "ok")

    r = requests.post(f"{BASE}/api/auth/login", json={"username": "admin", "password": "wrong"})
    check("錯誤密碼 401 + message", r.status_code == 401 and r.json()["message"] == "帳號或密碼錯誤", r.text)
    check("未帶 token 401", requests.get(f"{BASE}/api/drones").status_code == 401)
    r = requests.post(f"{BASE}/api/auth/login", json={"username": ""})
    check("驗證失敗回 400", r.status_code == 400 and "message" in r.json(), r.text)

    admin, data = login("admin", "Admin@123")
    check("admin 權限 17 項", len(data["user"]["permissions"]) == 17, data["user"]["permissions"])
    r = requests.post(f"{BASE}/api/auth/refresh", json={"refreshToken": data["refreshToken"]})
    check("refresh token 換發", r.status_code == 200 and r.json()["accessToken"], r.text)
    check("/auth/me", admin.get(f"{BASE}/api/auth/me").json()["username"] == "admin")

    menu = admin.get(f"{BASE}/api/menu").json()
    check("admin 選單 8 個頂層節點", len(menu) == 8, [m["title"] for m in menu])

    viewer, vdata = login("viewer", "Viewer@123")
    vmenu = viewer.get(f"{BASE}/api/menu").json()
    vtitles = [m["title"] for m in vmenu]
    check("viewer 看不到系統管理", "系統管理" not in vtitles, vtitles)
    check("viewer 呼叫 /users 403", viewer.get(f"{BASE}/api/users").status_code == 403)
    check("viewer 不可建立工單 403", viewer.post(f"{BASE}/api/workorders", json={"title": "x"}).status_code == 403)

    # ---------------- 無人機
    drones = admin.get(f"{BASE}/api/drones", params={"pageSize": 100}).json()
    check("無人機清單", drones["total"] >= 6 and "statusText" in drones["items"][0], drones)
    d1 = drones["items"][0]
    check("無人機詳情", admin.get(f"{BASE}/api/drones/{d1['id']}").json()["serialNumber"] == d1["serialNumber"])
    r = admin.post(f"{BASE}/api/drones", json={"serialNumber": d1["serialNumber"], "name": "x", "model": "y"})
    check("重複序號 409", r.status_code == 409, r.text)
    sn = f"TST-{int(time.time()) % 100000}"
    r = admin.post(f"{BASE}/api/drones", json={"serialNumber": sn, "name": "測試機 X", "model": "T1",
                                               "homeLatitude": 25.0559, "homeLongitude": 121.6156, "status": 1})
    check("新增無人機", r.status_code == 201, r.text)
    new_drone = r.json()
    body = {**{k: new_drone[k] for k in ("serialNumber", "model", "firmwareVersion", "batteryCapacityWh",
                                           "maxSpeedMps", "maxFlightMinutes", "homeLatitude", "homeLongitude")},
            "name": "測試機 Y", "isActive": True}
    check("修改無人機", admin.put(f"{BASE}/api/drones/{new_drone['id']}", json=body).json()["name"] == "測試機 Y")
    check("live 快照", isinstance(admin.get(f"{BASE}/api/drones/live").json(), list))
    check("遙測歷史", admin.get(f"{BASE}/api/drones/{d1['id']}/telemetry").status_code == 200)
    sessions = admin.get(f"{BASE}/api/drones/{d1['id']}/charge-sessions").json()
    check("充電記錄", isinstance(sessions, list) and (not sessions or "energyWh" in sessions[0]))
    r = admin.post(f"{BASE}/api/drones/simulated", json={"count": 2, "startPatrol": True, "loop": True})
    check("新增模擬機並巡航", r.status_code == 200 and len(r.json()["drones"]) == 2, r.text)
    sim = r.json()
    if sim["drones"]:
        sid = sim["drones"][0]["id"]
        check("停止巡航", admin.delete(f"{BASE}/api/drones/{sid}/patrol").status_code == 204)
        check("下達返航指令", admin.post(f"{BASE}/api/drones/{sid}/command", json={"command": "Return"}).status_code == 204)
        check("不支援指令 400", admin.post(f"{BASE}/api/drones/{sid}/command", json={"command": "Fly"}).status_code == 400)
    check("停用無人機", admin.delete(f"{BASE}/api/drones/{new_drone['id']}").status_code == 204)

    # ---------------- 攝影機
    cams = admin.get(f"{BASE}/api/cameras").json()
    check("攝影機清單", len(cams) >= 6)
    r = admin.post(f"{BASE}/api/cameras", json={"droneId": d1["id"], "name": "測試鏡頭", "protocol": 1,
                                                "streamUrl": "http://bad"})
    check("協定與網址不符 400", r.status_code == 400 and "rtsp" in r.json()["message"], r.text)
    r = admin.post(f"{BASE}/api/cameras", json={"droneId": d1["id"], "name": "測試鏡頭", "protocol": 1,
                                                "streamUrl": "rtsp://127.0.0.1:554/test"})
    check("新增攝影機", r.status_code == 201 and r.json()["sortOrder"] >= 1, r.text)
    cam = r.json()
    check("刪除攝影機", admin.delete(f"{BASE}/api/cameras/{cam['id']}").status_code == 204)

    # ---------------- 地圖
    points = admin.get(f"{BASE}/api/map/points").json()
    check("點位清單", len(points) >= 8)
    r = admin.post(f"{BASE}/api/map/points", json={"name": "測試點", "pointType": 4, "latitude": 25.06,
                                                   "longitude": 121.62, "altitudeM": 40})
    check("新增點位", r.status_code == 200, r.text)
    pid = r.json()["id"]
    check("刪除點位", admin.delete(f"{BASE}/api/map/points/{pid}").status_code == 204)
    wps = [{"sequence": 1, "latitude": 25.0559, "longitude": 121.6156, "altitudeM": 30, "action": 0},
           {"sequence": 2, "latitude": 25.0580, "longitude": 121.6180, "altitudeM": 40, "action": 2},
           {"sequence": 3, "latitude": 25.0560, "longitude": 121.6157, "altitudeM": 0, "action": 4}]
    r = admin.post(f"{BASE}/api/map/routes", json={"name": "測試航線", "waypoints": wps})
    check("建立航線 v1", r.status_code == 200 and r.json()["version"] == 1, r.text)
    route = r.json()
    r = admin.put(f"{BASE}/api/map/routes/{route['id']}",
                  json={"name": "測試航線", "changeNote": "調整", "waypoints": wps[::-1]})
    check("更新航線 v2", r.status_code == 200 and r.json()["version"] == 2, r.text)
    revs = admin.get(f"{BASE}/api/map/routes/{route['id']}/revisions").json()
    check("版本清單 2 筆", len(revs) == 2 and revs[0]["waypointCount"] == 3, revs)
    rev = admin.get(f"{BASE}/api/map/routes/{route['id']}/revisions/1").json()
    snap = json.loads(rev["snapshotJson"])
    check("版本快照為 GeoJSON", snap["type"] == "FeatureCollection" and len(snap["features"]) == 4)
    check("全部版本", len(admin.get(f"{BASE}/api/map/revisions").json()) >= 5)
    check("發布航線", admin.post(f"{BASE}/api/map/routes/{route['id']}/publish").status_code == 204)
    r = admin.post(f"{BASE}/api/map/routes", json={"name": "x", "waypoints": wps[:1]})
    check("航點不足 400", r.status_code == 400, r.text)

    # ---------------- 工單
    templates = admin.get(f"{BASE}/api/workorders/templates").json()
    check("模板清單", len(templates) >= 3 and isinstance(templates[0]["checklist"], list))
    r = admin.post(f"{BASE}/api/workorders/templates", json={"name": "測試模板", "checklist": ["a", "b"]})
    check("新增模板", r.status_code == 200 and r.json()["checklist"] == ["a", "b"], r.text)
    check("刪除模板", admin.delete(f"{BASE}/api/workorders/templates/{r.json()['id']}").status_code == 204)

    cur = admin.get(f"{BASE}/api/workorders", params={"scope": "current"}).json()
    hist = admin.get(f"{BASE}/api/workorders", params={"scope": "history", "pageSize": 5}).json()
    check("當前 / 歷史工單", cur["total"] >= 1 and hist["total"] >= 1 and len(hist["items"]) == 5)
    r = admin.post(f"{BASE}/api/workorders", json={"title": "測試工單", "templateId": templates[0]["id"]})
    check("建立工單 (套模板)", r.status_code == 200 and r.json()["orderNo"].startswith("WO-"), r.text)
    wo = r.json()
    idle = [d for d in admin.get(f"{BASE}/api/drones", params={"pageSize": 100}).json()["items"]
            if d["isActive"] and d["batteryPercent"] > 60]
    r = admin.post(f"{BASE}/api/workorders/{wo['id']}/schedule", json={"droneId": idle[0]["id"], "routeId": route["id"]})
    check("排程工單", r.status_code == 204, r.text)
    check("立即起飛", admin.post(f"{BASE}/api/workorders/{wo['id']}/start").status_code == 204)
    detail = admin.get(f"{BASE}/api/workorders/{wo['id']}").json()
    check("工單明細含航點與紀錄", len(detail["waypoints"]) == 3 and len(detail["missionLogs"]) >= 1, detail)
    r = admin.post(f"{BASE}/api/workorders", json={"title": "取消用"})
    check("取消工單", admin.post(f"{BASE}/api/workorders/{r.json()['id']}/cancel", json={"reason": "測試"})
          .status_code == 204)
    check("已結案不可再取消", admin.post(f"{BASE}/api/workorders/{r.json()['id']}/cancel", json={}).status_code == 400)
    check("航線被未結案工單引用不可刪", admin.delete(f"{BASE}/api/map/routes/{route['id']}").status_code == 400)

    # ---------------- 統計
    q = {"from": str(date.today() - timedelta(days=29)), "to": str(date.today())}
    check("overview", "totalDrones" in admin.get(f"{BASE}/api/statistics/overview").json())
    mc = admin.get(f"{BASE}/api/statistics/mission-count", params=q).json()
    check("任務數量 30 個區間", len(mc) == 30, len(mc))
    wk = admin.get(f"{BASE}/api/statistics/mission-count", params={**q, "granularity": "week"}).json()
    check("週粒度", 4 <= len(wk) <= 6 and "-W" in wk[0]["period"], wk)
    ws = admin.get(f"{BASE}/api/statistics/work-orders", params=q).json()
    check("工單圖表", len(ws["byPriority"]) == 4 and len(ws["trend"]) == 30)
    du = admin.get(f"{BASE}/api/statistics/work-order-duration", params=q).json()
    check("工單用時", any(p["count"] > 0 for p in du))
    ch = admin.get(f"{BASE}/api/statistics/charging", params={**q, "granularity": "month"}).json()
    check("充電圖表", ch["totalSessions"] > 0 and ch["byDrone"], ch["totalSessions"])

    # ---------------- 記錄
    check("任務紀錄", admin.get(f"{BASE}/api/logs/missions").json()["total"] > 0)
    lg = admin.get(f"{BASE}/api/logs/logins", params={"isSuccess": "false"}).json()
    check("登入紀錄 (失敗篩選)", lg["total"] >= 1 and all(not x["isSuccess"] for x in lg["items"]))
    nt = admin.get(f"{BASE}/api/notifications").json()
    check("通知清單", nt["total"] >= 5)
    unread = admin.get(f"{BASE}/api/notifications/unread-count").json()["count"]
    check("標為已讀", admin.post(f"{BASE}/api/notifications/{nt['items'][0]['id']}/read").status_code == 204)
    check("全部已讀", admin.post(f"{BASE}/api/notifications/read-all").status_code == 204
          and admin.get(f"{BASE}/api/notifications/unread-count").json()["count"] == 0, unread)

    # ---------------- 系統
    roles = admin.get(f"{BASE}/api/roles").json()
    perms = admin.get(f"{BASE}/api/roles/permissions").json()
    check("角色 / 權限", len(roles) >= 3 and len(perms) == 17)
    check("完整選單樹", len(admin.get(f"{BASE}/api/roles/menus").json()) == 8)
    r = admin.post(f"{BASE}/api/roles", json={"code": f"tst{int(time.time()) % 10000}", "name": "測試角色",
                                              "permissionIds": [perms[0]["id"], perms[1]["id"]]})
    check("新增角色", r.status_code == 200 and len(r.json()["permissionIds"]) == 2, r.text)
    role = r.json()
    uname = f"u{int(time.time()) % 100000}"
    r = admin.post(f"{BASE}/api/users", json={"username": uname, "email": f"{uname}@drone.local",
                                              "displayName": "測試員", "password": "Test@1234", "roleId": role["id"]})
    check("新增帳號", r.status_code == 200, r.text)
    user = r.json()
    r = admin.post(f"{BASE}/api/users", json={"username": uname + "x", "email": "not-an-email", "displayName": "x",
                                              "password": "Test@1234", "roleId": role["id"]})
    check("Email 格式驗證 400", r.status_code == 400, r.text)
    tester, tdata = login(uname, "Test@1234")
    check("新帳號依角色只看到 1 個選單", len(tester.get(f"{BASE}/api/menu").json()) == 1)
    check("角色仍被使用不可刪", admin.delete(f"{BASE}/api/roles/{role['id']}").status_code == 400)
    check("停用帳號", admin.post(f"{BASE}/api/users/{user['id']}/toggle-active").json()["isActive"] is False)
    r = requests.post(f"{BASE}/api/auth/login", json={"username": uname, "password": "Test@1234"})
    check("停用帳號無法登入", r.status_code == 401, r.text)
    check("重設密碼", admin.post(f"{BASE}/api/users/{user['id']}/reset-password",
                                 json={"newPassword": "New@12345"}).status_code == 204)
    check("刪除帳號", admin.delete(f"{BASE}/api/users/{user['id']}").status_code == 204)
    check("刪除角色", admin.delete(f"{BASE}/api/roles/{role['id']}").status_code == 204)
    check("不可刪除自己", admin.delete(f"{BASE}/api/users/{data['user']['id']}").status_code == 400)
    check("系統角色不可刪", admin.delete(f"{BASE}/api/roles/{roles[0]['id']}").status_code == 400)

    # ---------------- 帳號鎖定
    for _ in range(5):
        requests.post(f"{BASE}/api/auth/login", json={"username": "viewer", "password": "bad"})
    r = requests.post(f"{BASE}/api/auth/login", json={"username": "viewer", "password": "Viewer@123"})
    check("連續失敗 5 次鎖定 (423)", r.status_code == 423, r.text)
    vid = next(u["id"] for u in admin.get(f"{BASE}/api/users").json()["items"] if u["username"] == "viewer")
    admin.post(f"{BASE}/api/users/{vid}/reset-password", json={"newPassword": "Viewer@123"})
    r = requests.post(f"{BASE}/api/auth/login", json={"username": "viewer", "password": "Viewer@123"})
    check("重設密碼後解除鎖定", r.status_code == 200, r.text)

    print(f"\n{'全部通過' if not failures else f'{len(failures)} 項失敗:' + ', '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
