"""選單樹、通知派送與 DTO 轉換等共用服務。"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import schemas as s
from .enums import (
    CameraProtocol, DroneStatus, MapPointType, MissionEventType, NotificationLevel, RouteStatus,
    WorkOrderPriority, WorkOrderStatus, text_of,
)
from .models import (
    Camera, Drone, FlightRoute, MapPoint, MenuItem, MissionLog, Notification, User, WorkOrder,
    WorkOrderTemplate,
)
from .realtime import hub


# ============================================================ 選單

def build_menu(db: Session, permissions: list[str] | None) -> list[s.MenuNodeDto]:
    """依權限碼過濾選單樹;群組節點若沒有任何可見子節點則整組隱藏。permissions=None 表示不過濾。"""
    q = select(MenuItem).order_by(MenuItem.sort_order)
    if permissions is not None:
        q = q.where(MenuItem.is_visible.is_(True))
    items = db.scalars(q).all()
    granted = set(permissions or [])

    def build(parent_id: int | None) -> list[s.MenuNodeDto]:
        result = []
        for item in (i for i in items if i.parent_id == parent_id):
            children = build(item.id)
            is_group = not item.path
            if permissions is not None:
                if is_group and not children:
                    continue
                if not is_group and item.permission_code and item.permission_code not in granted:
                    continue
            result.append(s.MenuNodeDto(
                id=item.id, key=item.key, title=item.title, icon=item.icon or "", path=item.path or "",
                permission_code=item.permission_code, children=children))
        return result

    return build(None)


# ============================================================ 通知

def notification_dto(n: Notification) -> s.NotificationDto:
    return s.NotificationDto(
        id=n.id, level=n.level, level_text=text_of(NotificationLevel, n.level), category=n.category,
        title=n.title, content=n.content, link=n.link, is_read=n.is_read, created_at=n.created_at)


def push_notification(db: Session, level: NotificationLevel, category: str, title: str,
                      content: str | None = None, link: str | None = None, user_id: int | None = None) -> None:
    """建立通知並即時推播。user_id 為 None 表示全體廣播。呼叫端負責 commit 之前的變更。"""
    n = Notification(level=int(level), category=category, title=title, content=content, link=link, user_id=user_id)
    db.add(n)
    db.commit()
    hub.publish("NotificationReceived", notification_dto(n))


# ============================================================ DTO 轉換

def drone_dto(d: Drone, work_order_id: int | None = None, work_order_no: str | None = None,
              patrol_route_name: str | None = None, is_patrolling: bool = False) -> s.DroneDto:
    return s.DroneDto(
        id=d.id, serial_number=d.serial_number, name=d.name, model=d.model,
        status=d.status, status_text=text_of(DroneStatus, d.status),
        battery_percent=d.battery_percent, latitude=d.latitude, longitude=d.longitude,
        altitude_m=d.altitude_m, speed_mps=d.speed_mps, heading_deg=d.heading_deg,
        firmware_version=d.firmware_version, battery_capacity_wh=d.battery_capacity_wh,
        max_speed_mps=d.max_speed_mps, max_flight_minutes=d.max_flight_minutes,
        home_latitude=d.home_latitude, home_longitude=d.home_longitude,
        total_flight_seconds=d.total_flight_seconds, total_energy_wh=d.total_energy_wh,
        last_heartbeat_at=d.last_heartbeat_at, is_active=d.is_active,
        current_work_order_id=work_order_id, current_work_order_no=work_order_no,
        is_patrolling=is_patrolling, patrol_route_name=patrol_route_name if is_patrolling else None)


def camera_dto(c: Camera) -> s.CameraDto:
    return s.CameraDto(
        id=c.id, drone_id=c.drone_id, drone_name=c.drone.name if c.drone else "",
        drone_serial_number=c.drone.serial_number if c.drone else "", name=c.name,
        protocol=c.protocol, protocol_text=text_of(CameraProtocol, c.protocol), stream_url=c.stream_url,
        description=c.description, sort_order=c.sort_order, is_active=c.is_active,
        created_at=c.created_at, updated_at=c.updated_at)


def map_point_dto(p: MapPoint) -> s.MapPointDto:
    return s.MapPointDto(
        id=p.id, name=p.name, point_type=p.point_type, point_type_text=text_of(MapPointType, p.point_type),
        latitude=p.latitude, longitude=p.longitude, altitude_m=p.altitude_m, description=p.description,
        created_at=p.created_at)


def waypoint_dtos(route: FlightRoute | None) -> list[s.RouteWaypointDto]:
    if route is None:
        return []
    return [s.RouteWaypointDto(
        id=w.id, map_point_id=w.map_point_id, map_point_name=w.map_point.name if w.map_point else None,
        sequence=w.sequence, latitude=w.latitude, longitude=w.longitude, altitude_m=w.altitude_m,
        action=w.action, hover_seconds=w.hover_seconds) for w in sorted(route.waypoints, key=lambda x: x.sequence)]


def route_dto(r: FlightRoute, include_waypoints: bool) -> s.RouteDto:
    return s.RouteDto(
        id=r.id, name=r.name, description=r.description, status=r.status,
        status_text=text_of(RouteStatus, r.status), version=r.version, total_distance_m=r.total_distance_m,
        estimated_minutes=r.estimated_minutes, estimated_energy_wh=r.estimated_energy_wh,
        waypoint_count=len(r.waypoints), created_at=r.created_at, updated_at=r.updated_at,
        waypoints=waypoint_dtos(r) if include_waypoints else [])


def work_order_dto(w: WorkOrder, created_by_name: str | None = None) -> s.WorkOrderDto:
    return s.WorkOrderDto(
        id=w.id, order_no=w.order_no, title=w.title, description=w.description,
        template_id=w.template_id, template_name=w.template.name if w.template else None,
        route_id=w.route_id, route_name=w.route.name if w.route else None,
        drone_id=w.drone_id, drone_name=w.drone.name if w.drone else None,
        status=w.status, status_text=text_of(WorkOrderStatus, w.status),
        priority=w.priority, priority_text=text_of(WorkOrderPriority, w.priority),
        scheduled_at=w.scheduled_at, started_at=w.started_at, completed_at=w.completed_at,
        duration_seconds=w.duration_seconds, energy_used_wh=w.energy_used_wh,
        progress_percent=w.progress_percent, assignee_user_id=w.assignee_user_id,
        assignee_name=w.assignee.display_name if w.assignee else None, created_by_name=created_by_name,
        created_at=w.created_at, remark=w.remark)


def template_dto(t: WorkOrderTemplate) -> s.WorkOrderTemplateDto:
    checklist = t.checklist_json
    if isinstance(checklist, str):
        try:
            checklist = json.loads(checklist)
        except ValueError:
            checklist = []
    return s.WorkOrderTemplateDto(
        id=t.id, name=t.name, description=t.description, default_route_id=t.default_route_id,
        default_route_name=t.default_route.name if t.default_route else None,
        default_priority=t.default_priority, estimated_minutes=t.estimated_minutes,
        checklist=[str(x) for x in (checklist or [])], is_active=t.is_active, created_at=t.created_at)


def mission_log_dto(log: MissionLog, work_order_no: str | None = None, drone_name: str | None = None) -> s.MissionLogDto:
    return s.MissionLogDto(
        id=log.id, work_order_id=log.work_order_id, work_order_no=work_order_no, drone_id=log.drone_id,
        drone_name=drone_name, event_type=log.event_type,
        event_type_text=text_of(MissionEventType, log.event_type), message=log.message,
        occurred_at=log.occurred_at)


def current_user_dto(user: User) -> s.CurrentUserDto:
    return s.CurrentUserDto(
        id=user.id, username=user.username, display_name=user.display_name, email=user.email,
        role_code=user.role.code, role_name=user.role.name,
        permissions=sorted(p.code for p in user.role.permissions), last_login_at=user.last_login_at)


def user_names(db: Session, ids) -> dict[int, str]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = db.execute(select(User.id, User.display_name).where(User.id.in_(wanted))).all()
    return {r.id: r.display_name for r in rows}
