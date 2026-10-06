"""初始資料。僅在對應資料表為空時寫入,重複啟動不會重覆灌入。"""
from __future__ import annotations

import logging
import random
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import permissions as P
from .db import utcnow
from .enums import (
    CameraProtocol, DroneStatus, MapPointType, MissionEventType, NotificationLevel, RouteStatus,
    WaypointAction, WorkOrderPriority, WorkOrderStatus,
)
from .geo import recalculate_route, route_geojson
from .models import (
    Camera, ChargeSession, Drone, FlightRoute, LoginLog, MapPoint, MenuItem, MissionLog, Notification,
    Permission, Role, RolePermission, RouteRevision, RouteWaypoint, User, WorkOrder, WorkOrderTemplate,
)
from .security import hash_password

log = logging.getLogger("drone.seeder")

# 廠區中心 (台北南港軟體園區附近),模擬資料以此為基準
BASE_LAT = 25.0559
BASE_LNG = 121.6156


def _any(db: Session, model) -> bool:
    return db.scalar(select(func.count()).select_from(model)) > 0


def _today_utc() -> datetime:
    return datetime.combine(utcnow().date(), time.min, tzinfo=timezone.utc)


def seed(db: Session) -> None:
    _seed_permissions_and_roles(db)
    _seed_menus(db)
    _ensure_camera_menu(db)
    _seed_users(db)
    _seed_drones(db)
    _seed_cameras(db)
    _seed_map(db)
    _seed_work_orders(db)
    _seed_logs(db)
    log.info("Seed 檢查完成")


# ---------------------------------------------------------------- 權限 / 角色

def _seed_permissions_and_roles(db: Session) -> None:
    existing = set(db.scalars(select(Permission.code)).all())
    missing = [Permission(code=c, name=n, group_name=g) for c, n, g in P.ALL if c not in existing]
    if missing:
        db.add_all(missing)
        db.commit()

    # admin 一律補齊所有權限:新增權限碼後,既有資料庫的管理員也能立即使用新功能
    admin_role = db.scalar(select(Role).where(Role.code == "admin"))
    if admin_role:
        granted = set(db.scalars(select(RolePermission.permission_id).where(RolePermission.role_id == admin_role.id)))
        all_ids = set(db.scalars(select(Permission.id)))
        if all_ids - granted:
            db.add_all(RolePermission(role_id=admin_role.id, permission_id=pid) for pid in all_ids - granted)
            db.commit()

    if _any(db, Role):
        return

    perm_by_code = {p.code: p for p in db.scalars(select(Permission))}
    admin = Role(code="admin", name="系統管理員", description="擁有全部權限", is_system=True)
    op = Role(code="operator", name="操作員", description="可執行監控、地圖編輯與工單派工", is_system=True)
    viewer = Role(code="viewer", name="檢視者", description="唯讀權限", is_system=True)
    db.add_all([admin, op, viewer])
    db.flush()

    def grant(role: Role, *codes: str) -> None:
        db.add_all(RolePermission(role_id=role.id, permission_id=perm_by_code[c].id) for c in codes)

    grant(admin, *(c for c, _, _ in P.ALL))
    grant(op, P.MONITOR_VIEW, P.MAP_VIEW, P.MAP_EDIT, P.MAP_HISTORY, P.DRONE_VIEW, P.DRONE_CONFIG,
          P.CAMERA_VIEW, P.CAMERA_MANAGE, P.WORKORDER_VIEW, P.WORKORDER_MANAGE, P.WORKORDER_TEMPLATE,
          P.STATS_VIEW, P.LOG_MISSION, P.LOG_NOTIFICATION)
    grant(viewer, P.MONITOR_VIEW, P.MAP_VIEW, P.MAP_HISTORY, P.DRONE_VIEW, P.CAMERA_VIEW, P.WORKORDER_VIEW,
          P.STATS_VIEW, P.LOG_MISSION, P.LOG_NOTIFICATION)
    db.commit()


# ---------------------------------------------------------------- 選單

def _seed_menus(db: Session) -> None:
    if _any(db, MenuItem):
        return

    def add(key, title, icon, path, order, perm, parent_id=None) -> MenuItem:
        item = MenuItem(key=key, title=title, icon=icon, path=path, sort_order=order,
                        permission_code=perm, parent_id=parent_id, is_visible=True)
        db.add(item)
        db.flush()
        return item

    add("monitor", "即時監控", "radar", "/monitor", 10, P.MONITOR_VIEW)

    m = add("map", "地圖管理", "map", "", 20, None)
    add("map-editor", "地圖編輯", "edit-map", "/map/editor", 21, P.MAP_EDIT, m.id)
    add("map-history", "歷史地圖", "history", "/map/history", 22, P.MAP_HISTORY, m.id)

    d = add("drone", "無人機管理", "drone", "", 30, None)
    add("drone-settings", "無人機設定", "settings", "/drone/settings", 31, P.DRONE_CONFIG, d.id)
    add("drone-status", "無人機狀態", "battery", "/drone/status", 32, P.DRONE_VIEW, d.id)

    add("camera", "攝影機管理", "camera", "/cameras", 35, P.CAMERA_VIEW)

    w = add("workorder", "工單管理", "clipboard", "", 40, None)
    add("workorder-current", "當前工單", "play", "/workorder/current", 41, P.WORKORDER_VIEW, w.id)
    add("workorder-history", "歷史工單", "archive", "/workorder/history", 42, P.WORKORDER_VIEW, w.id)
    add("workorder-template", "工單模板", "template", "/workorder/templates", 43, P.WORKORDER_TEMPLATE, w.id)

    s = add("stats", "統計圖表", "chart", "", 50, None)
    add("stats-mission", "任務數量", "chart-bar", "/stats/missions", 51, P.STATS_VIEW, s.id)
    add("stats-workorder", "工單圖表", "chart-pie", "/stats/workorders", 52, P.STATS_VIEW, s.id)
    add("stats-duration", "工單用時", "clock", "/stats/duration", 53, P.STATS_VIEW, s.id)
    add("stats-charging", "充電圖表", "bolt", "/stats/charging", 54, P.STATS_VIEW, s.id)

    lg = add("log", "記錄管理", "list", "", 60, None)
    add("log-mission", "任務紀錄", "route", "/logs/missions", 61, P.LOG_MISSION, lg.id)
    add("log-login", "登入紀錄", "login", "/logs/logins", 62, P.LOG_LOGIN, lg.id)
    add("log-notification", "通知中心", "bell", "/logs/notifications", 63, P.LOG_NOTIFICATION, lg.id)

    sy = add("system", "系統管理", "shield", "", 70, None)
    add("system-user", "帳號管理", "user", "/system/users", 71, P.SYSTEM_USER, sy.id)
    add("system-role", "角色管理", "key", "/system/roles", 72, P.SYSTEM_ROLE, sy.id)
    db.commit()


def _ensure_camera_menu(db: Session) -> None:
    """冪等補上「攝影機管理」選單 (既有資料庫需靠這裡才會出現新選單)。"""
    if db.scalar(select(MenuItem).where(MenuItem.key == "camera")):
        return
    db.add(MenuItem(key="camera", title="攝影機管理", icon="camera", path="/cameras", sort_order=35,
                    permission_code=P.CAMERA_VIEW, parent_id=None, is_visible=True))
    db.commit()


# ---------------------------------------------------------------- 帳號

def _seed_users(db: Session) -> None:
    if _any(db, User):
        return
    roles = {r.code: r for r in db.scalars(select(Role))}
    db.add_all([
        User(username="admin", email="admin@drone.local", display_name="系統管理員",
             password_hash=hash_password("Admin@123"), role_id=roles["admin"].id),
        User(username="operator", email="operator@drone.local", display_name="王志明",
             password_hash=hash_password("Operator@123"), role_id=roles["operator"].id),
        User(username="viewer", email="viewer@drone.local", display_name="陳雅婷",
             password_hash=hash_password("Viewer@123"), role_id=roles["viewer"].id),
    ])
    db.commit()


# ---------------------------------------------------------------- 無人機 / 攝影機

def _seed_drones(db: Session) -> None:
    if _any(db, Drone):
        return
    specs = [
        ("DRN-001", "巡檢一號", "MatrixPro-4T", DroneStatus.Idle, 96.0, 320, 40),
        ("DRN-002", "巡檢二號", "MatrixPro-4T", DroneStatus.Idle, 88.5, 320, 40),
        ("DRN-003", "測繪一號", "SurveyX-200", DroneStatus.Idle, 73.2, 280, 35),
        ("DRN-004", "夜巡一號", "NightHawk-S", DroneStatus.Charging, 41.0, 300, 32),
        ("DRN-005", "備援機", "MatrixPro-4T", DroneStatus.Maintenance, 55.0, 320, 40),
        ("DRN-006", "測試機", "SurveyX-200", DroneStatus.Offline, 12.0, 280, 35),
    ]
    now = utcnow()
    for i, (sn, name, model, status, battery, capacity, minutes) in enumerate(specs):
        lat = BASE_LAT + (i % 3) * 0.0012
        lng = BASE_LNG + (i // 3) * 0.0016
        db.add(Drone(
            serial_number=sn, name=name, model=model, status=int(status), battery_percent=battery,
            battery_capacity_wh=capacity, max_flight_minutes=minutes, max_speed_mps=18, firmware_version="2.4.1",
            latitude=lat, longitude=lng, altitude_m=0, home_latitude=lat, home_longitude=lng,
            last_heartbeat_at=now - timedelta(hours=6) if status == DroneStatus.Offline else now,
            total_flight_seconds=3600 * (8 + i * 3), total_energy_wh=1200 + i * 340, is_active=True))
    db.commit()


def _seed_cameras(db: Session) -> None:
    if _any(db, Camera):
        return
    drones = db.scalars(select(Drone).order_by(Drone.id).limit(3)).all()
    for d in drones:
        sn = d.serial_number.lower()
        db.add(Camera(drone_id=d.id, name="雲台主鏡", protocol=int(CameraProtocol.Http),
                      stream_url=f"http://{sn}.cam.local/video.mjpg",
                      description="前視 4K 雲台 (MJPEG over HTTP)", sort_order=1, is_active=True))
        db.add(Camera(drone_id=d.id, name="熱像鏡頭", protocol=int(CameraProtocol.Rtsp),
                      stream_url=f"rtsp://{sn}.cam.local:554/thermal",
                      description="紅外熱像 (RTSP)", sort_order=2, is_active=True))
    db.commit()


# ---------------------------------------------------------------- 地圖 / 航線

def _seed_map(db: Session) -> None:
    if _any(db, MapPoint):
        return
    admin = db.scalar(select(User).where(User.username == "admin"))
    defs = [
        ("A 棟停機坪", MapPointType.Takeoff, 0, 0, 0, "主起降場"),
        ("1 號充電站", MapPointType.ChargingStation, 0.0004, 0.0003, 0, "8 槽位快充"),
        ("東側圍牆", MapPointType.Waypoint, 0.0021, 0.0027, 35, None),
        ("倉庫頂", MapPointType.Waypoint, 0.0033, 0.0009, 45, None),
        ("北側水塔", MapPointType.Poi, 0.0046, -0.0012, 60, "月檢重點"),
        ("西側停車場", MapPointType.Waypoint, 0.0011, -0.0031, 30, None),
        ("B 棟降落點", MapPointType.Landing, -0.0014, 0.0018, 0, None),
        ("變電站禁飛", MapPointType.NoFlyMarker, 0.0026, -0.0026, 0, "半徑 80m 禁飛"),
    ]
    points = [MapPoint(name=n, point_type=int(t), latitude=BASE_LAT + dlat, longitude=BASE_LNG + dlng,
                       altitude_m=alt, description=desc, created_by=admin.id)
              for n, t, dlat, dlng, alt, desc in defs]
    db.add_all(points)
    db.flush()

    A = WaypointAction
    route_defs = [
        ("廠區巡檢 A 線", "停機坪 → 東側圍牆 → 倉庫頂 → 返場", RouteStatus.Published,
         [0, 2, 3, 0], [A.FlyThrough, A.Photo, A.Scan, A.Land]),
        ("周界夜巡 B 線", "夜間周界巡查,含水塔與停車場", RouteStatus.Published,
         [0, 4, 5, 6], [A.FlyThrough, A.Hover, A.Photo, A.Land]),
        ("屋頂設備測繪", "倉庫頂與水塔的高解析測繪 (草稿)", RouteStatus.Draft,
         [0, 3, 4, 0], [A.FlyThrough, A.Scan, A.Scan, A.Land]),
    ]
    for name, desc, status, idx, actions in route_defs:
        route = FlightRoute(name=name, description=desc, status=int(status), version=1, created_by=admin.id)
        for seq, (pi, action) in enumerate(zip(idx, actions), start=1):
            mp = points[pi]
            route.waypoints.append(RouteWaypoint(
                map_point_id=mp.id, sequence=seq, latitude=mp.latitude, longitude=mp.longitude,
                altitude_m=0 if action == A.Land else max(mp.altitude_m, 30), action=int(action),
                hover_seconds=20 if action in (A.Hover, A.Scan) else 0))
        recalculate_route(route)
        db.add(route)
        db.flush()
        db.add(RouteRevision(route_id=route.id, version=1, change_note="初版建立", created_by=admin.id,
                             snapshot_json=route_geojson(route)))
    db.commit()


# ---------------------------------------------------------------- 工單

def _seed_work_orders(db: Session) -> None:
    if _any(db, WorkOrder):
        return
    routes = db.scalars(select(FlightRoute).order_by(FlightRoute.id)).all()
    flyable = [r for r in routes if r.status == RouteStatus.Published]
    drones = db.scalars(select(Drone).where(Drone.is_active.is_(True)).order_by(Drone.id)).all()
    users = {u.username: u for u in db.scalars(select(User))}
    admin, op = users["admin"], users["operator"]
    if not routes or not drones:
        return

    if not _any(db, WorkOrderTemplate):
        def route_id(i: int):
            return routes[i].id if i < len(routes) else None
        db.add_all([
            WorkOrderTemplate(name="日常廠區巡檢", description="每日 09:00 例行巡檢", default_route_id=route_id(0),
                              default_priority=int(WorkOrderPriority.Normal), estimated_minutes=25,
                              checklist_json=["電池 ≥ 80%", "螺旋槳外觀檢查", "GPS 定位 ≥ 12 顆", "回傳影像確認"]),
            WorkOrderTemplate(name="夜間周界巡查", description="22:00 周界安防巡查", default_route_id=route_id(1),
                              default_priority=int(WorkOrderPriority.High), estimated_minutes=35,
                              checklist_json=["夜航燈開啟", "紅外鏡頭校正", "電池 ≥ 90%"]),
            WorkOrderTemplate(name="屋頂設備測繪", description="月度高解析測繪", default_route_id=route_id(2),
                              default_priority=int(WorkOrderPriority.Low), estimated_minutes=50,
                              checklist_json=["記憶卡剩餘空間 ≥ 32GB", "測繪參數確認"]),
        ])
        db.commit()

    templates = db.scalars(select(WorkOrderTemplate).order_by(WorkOrderTemplate.id)).all()
    rnd = random.Random(20260815)
    titles = ["廠區例行巡檢", "夜間周界巡查", "屋頂設備測繪", "臨時異常複查", "圍牆破損確認", "太陽能板熱點檢查"]
    today = _today_utc()
    orders: list[WorkOrder] = []

    for d in range(30, -1, -1):
        count = 3 if d == 0 else rnd.randint(1, 3)
        for k in range(count):
            created = today - timedelta(days=d) + timedelta(hours=rnd.randint(7, 19), minutes=rnd.randint(0, 58))
            tpl = rnd.choice(templates)
            # 未結案的工單只掛已發布航線,否則模擬器不會派飛
            route = rnd.choice(flyable if d == 0 and flyable else routes)
            drone = rnd.choice(drones)
            order = WorkOrder(
                order_no=f"WO-{created:%Y%m%d}-{len(orders) + 1:04d}", title=rnd.choice(titles),
                description=tpl.description, template_id=tpl.id, route_id=route.id, drone_id=drone.id,
                priority=rnd.randint(0, 3), assignee_user_id=op.id, created_by=admin.id,
                created_at=created, updated_at=created, scheduled_at=created + timedelta(minutes=30))

            if d == 0 and k == 0:
                order.status = int(WorkOrderStatus.Pending)
            elif d == 0 and k == 1:
                order.status = int(WorkOrderStatus.Scheduled)
            else:
                roll = rnd.random()
                if roll < 0.82:
                    minutes = tpl.estimated_minutes + rnd.randint(-8, 14)
                    order.status = int(WorkOrderStatus.Completed)
                    order.started_at = created + timedelta(minutes=30)
                    order.completed_at = order.started_at + timedelta(minutes=minutes)
                    order.duration_seconds = minutes * 60
                    order.energy_used_wh = round(minutes * (5.5 + rnd.random() * 2.5), 2)
                    order.progress_percent = 100
                elif roll < 0.92:
                    order.status = int(WorkOrderStatus.Cancelled)
                    order.remark = "天候不佳取消"
                else:
                    minutes = rnd.randint(5, 19)
                    order.status = int(WorkOrderStatus.Failed)
                    order.started_at = created + timedelta(minutes=30)
                    order.completed_at = order.started_at + timedelta(minutes=minutes)
                    order.duration_seconds = minutes * 60
                    order.energy_used_wh = round(minutes * 6.2, 2)
                    order.progress_percent = rnd.randint(20, 79)
                    order.remark = "回傳訊號中斷,任務中止"
            orders.append(order)

    db.add_all(orders)
    db.commit()


# ---------------------------------------------------------------- 記錄

def _seed_logs(db: Session) -> None:
    rnd = random.Random(4242)
    drones = db.scalars(select(Drone).order_by(Drone.id)).all()
    users = db.scalars(select(User).order_by(User.id)).all()
    today = _today_utc()
    now = utcnow()

    if not _any(db, ChargeSession):
        for d in range(30, -1, -1):
            for drone in (x for x in drones if x.is_active):
                if rnd.random() > 0.62:
                    continue
                start = today - timedelta(days=d) + timedelta(hours=rnd.randint(0, 21), minutes=rnd.randint(0, 58))
                start_pct = rnd.randint(12, 44)
                end_pct = rnd.randint(88, 100)
                minutes = int((end_pct - start_pct) * 0.85) + rnd.randint(2, 9)
                db.add(ChargeSession(
                    drone_id=drone.id, started_at=start, ended_at=start + timedelta(minutes=minutes),
                    start_percent=start_pct, end_percent=end_pct,
                    energy_wh=round(float(drone.battery_capacity_wh) * (end_pct - start_pct) / 100 * 1.08, 2),
                    duration_seconds=minutes * 60, station_name=rnd.choice(["Station-A", "Station-B"])))
        db.commit()

    if not _any(db, MissionLog):
        done = db.scalars(select(WorkOrder).where(WorkOrder.started_at.is_not(None))
                          .order_by(WorkOrder.created_at.desc()).limit(60)).unique().all()
        E = MissionEventType
        for w in done:
            t = w.started_at
            db.add(MissionLog(work_order_id=w.id, drone_id=w.drone_id, event_type=int(E.Takeoff),
                              message=f"{w.order_no} 起飛,航線已載入", occurred_at=t))
            db.add(MissionLog(work_order_id=w.id, drone_id=w.drone_id, event_type=int(E.Waypoint),
                              message="抵達航點 #2,執行拍照", occurred_at=t + timedelta(minutes=4)))
            db.add(MissionLog(work_order_id=w.id, drone_id=w.drone_id, event_type=int(E.Waypoint),
                              message="抵達航點 #3,執行掃描", occurred_at=t + timedelta(minutes=9)))
            if w.status == WorkOrderStatus.Failed:
                db.add(MissionLog(work_order_id=w.id, drone_id=w.drone_id, event_type=int(E.Error),
                                  message="資料鏈路中斷超過 30 秒,自動返航",
                                  occurred_at=w.completed_at or t + timedelta(minutes=12)))
            else:
                db.add(MissionLog(work_order_id=w.id, drone_id=w.drone_id, event_type=int(E.Landing),
                                  message=f"{w.order_no} 降落完成",
                                  occurred_at=w.completed_at or t + timedelta(minutes=25)))
        db.commit()

    if not _any(db, LoginLog):
        for d in range(14, -1, -1):
            for u in users:
                if rnd.random() > 0.7:
                    continue
                db.add(LoginLog(user_id=u.id, username=u.username, ip_address=f"192.168.10.{rnd.randint(2, 199)}",
                                user_agent="DroneClient/1.0 (Windows NT 10.0; Win64; x64)", is_success=True,
                                logged_at=today - timedelta(days=d) + timedelta(hours=rnd.randint(8, 18))))
        db.add(LoginLog(username="admin", ip_address="203.0.113.44", user_agent="curl/8.4.0", is_success=False,
                        fail_reason="密碼錯誤", logged_at=now - timedelta(days=2) + timedelta(hours=3)))
        db.commit()

    if not _any(db, Notification):
        L = NotificationLevel
        db.add_all([
            Notification(level=int(L.Warning), category="drone", title="DRN-004 電量偏低",
                         content="電量降至 41%,已自動進入充電程序。", link="/drone/status",
                         created_at=now - timedelta(hours=3)),
            Notification(level=int(L.Error), category="drone", title="DRN-006 離線",
                         content="已超過 6 小時未回報心跳,請確認機體狀態。", link="/drone/status",
                         created_at=now - timedelta(hours=6)),
            Notification(level=int(L.Info), category="workorder", title="今日排程已產生",
                         content="共 3 張工單待執行。", link="/workorder/current", created_at=now - timedelta(hours=8)),
            Notification(level=int(L.Success), category="workorder", title="夜巡任務完成",
                         content="周界夜巡 B 線全部航點執行完畢。", link="/workorder/history", is_read=True,
                         created_at=now - timedelta(days=1)),
            Notification(level=int(L.Info), category="system", title="系統初始化完成",
                         content="預設角色與選單已建立。", created_at=now - timedelta(days=2)),
        ])
        db.commit()
