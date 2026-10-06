"""
ORM 實體。表名、欄位名、型別與索引名稱與原 EF Core 版一致 (snake_case),
因此新舊後端可以共用同一個 PostgreSQL 資料庫。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Double, ForeignKey, Identity, Index, Integer, Numeric, String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .db import utcnow
from .enums import TERMINAL_STATUSES, DroneStatus, WorkOrderPriority, WorkOrderStatus

TZ = DateTime(timezone=True)


def money(precision: int, scale: int = 2) -> Numeric:
    # asdecimal=False:直接回傳 float,JSON 序列化不會變成字串
    return Numeric(precision, scale, asdecimal=False)


class Base(DeclarativeBase):
    pass


# ============================================================ 帳號與權限

class Role(Base):
    __tablename__ = "roles"
    __table_args__ = (Index("IX_roles_code", "code", unique=True),)

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(String(200))
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TZ, default=utcnow)

    permissions: Mapped[list[Permission]] = relationship(secondary="role_permissions", lazy="selectin",
                                                         order_by="Permission.id")


class Permission(Base):
    __tablename__ = "permissions"
    __table_args__ = (Index("IX_permissions_code", "code", unique=True),)

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(80))
    group_name: Mapped[str] = mapped_column(String(50))


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (Index("IX_role_permissions_permission_id", "permission_id"),)

    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    permission_id: Mapped[int] = mapped_column(ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("IX_users_username", "username", unique=True),
        Index("IX_users_email", "email", unique=True),
        Index("IX_users_role_id", "role_id"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    username: Mapped[str] = mapped_column(String(50))
    email: Mapped[str] = mapped_column(String(120))
    display_name: Mapped[str] = mapped_column(String(50))
    password_hash: Mapped[str] = mapped_column(String(200))
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="RESTRICT"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(TZ)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(TZ)
    created_at: Mapped[datetime] = mapped_column(TZ, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZ, default=utcnow)

    role: Mapped[Role] = relationship(lazy="joined")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        Index("IX_refresh_tokens_token", "token", unique=True),
        Index("IX_refresh_tokens_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token: Mapped[str] = mapped_column(String(200))
    expires_at: Mapped[datetime] = mapped_column(TZ)
    revoked_at: Mapped[datetime | None] = mapped_column(TZ)
    created_at: Mapped[datetime] = mapped_column(TZ, default=utcnow)

    user: Mapped[User] = relationship(lazy="joined")

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None and self.expires_at > utcnow()


class MenuItem(Base):
    """側邊欄節點。以 permission_code 決定該角色是否看得到。"""
    __tablename__ = "menu_items"
    __table_args__ = (
        Index("IX_menu_items_key", "key", unique=True),
        Index("IX_menu_items_parent_id", "parent_id"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("menu_items.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(50))
    icon: Mapped[str] = mapped_column(String(50), default="")
    path: Mapped[str] = mapped_column(String(120), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    permission_code: Mapped[str | None] = mapped_column(String(80))
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True)


# ============================================================ 機隊與用電

class Drone(Base):
    __tablename__ = "drones"
    __table_args__ = (Index("IX_drones_serial_number", "serial_number", unique=True),)

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    serial_number: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(50))
    status: Mapped[int] = mapped_column(Integer, default=int(DroneStatus.Offline))
    battery_percent: Mapped[float] = mapped_column(money(5), default=100.0)
    latitude: Mapped[float] = mapped_column(Double, default=0.0)
    longitude: Mapped[float] = mapped_column(Double, default=0.0)
    altitude_m: Mapped[float] = mapped_column(Double, default=0.0)
    speed_mps: Mapped[float] = mapped_column(Double, default=0.0)
    heading_deg: Mapped[float] = mapped_column(Double, default=0.0)
    firmware_version: Mapped[str] = mapped_column(String(30), default="1.0.0")
    battery_capacity_wh: Mapped[float] = mapped_column(money(8), default=280.0)
    max_speed_mps: Mapped[float] = mapped_column(money(6), default=18.0)
    max_flight_minutes: Mapped[int] = mapped_column(Integer, default=35)
    home_latitude: Mapped[float] = mapped_column(Double, default=0.0)
    home_longitude: Mapped[float] = mapped_column(Double, default=0.0)
    total_flight_seconds: Mapped[int] = mapped_column(BigInteger, default=0)
    total_energy_wh: Mapped[float] = mapped_column(money(12), default=0.0)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(TZ)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(TZ, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZ, default=utcnow)


class Camera(Base):
    """掛載於無人機的 IP 攝影機。一台無人機可有多個,提供 HTTP/RTSP 即時影像串流。"""
    __tablename__ = "cameras"
    __table_args__ = (Index("IX_cameras_drone_id_sort_order", "drone_id", "sort_order"),)

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    drone_id: Mapped[int] = mapped_column(ForeignKey("drones.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(50))
    protocol: Mapped[int] = mapped_column(Integer, default=0)
    stream_url: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(String(200))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(TZ, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZ, default=utcnow)

    drone: Mapped[Drone] = relationship(lazy="joined")


class DroneTelemetry(Base):
    """時序遙測明細,供航跡回放與統計。"""
    __tablename__ = "drone_telemetry"
    __table_args__ = (Index("ix_drone_telemetry_drone_recorded", "drone_id", "recorded_at"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    drone_id: Mapped[int] = mapped_column(ForeignKey("drones.id", ondelete="CASCADE"))
    recorded_at: Mapped[datetime] = mapped_column(TZ)
    latitude: Mapped[float] = mapped_column(Double)
    longitude: Mapped[float] = mapped_column(Double)
    altitude_m: Mapped[float] = mapped_column(Double)
    speed_mps: Mapped[float] = mapped_column(Double)
    heading_deg: Mapped[float] = mapped_column(Double)
    battery_percent: Mapped[float] = mapped_column(money(5))
    voltage_v: Mapped[float] = mapped_column(money(8))
    current_a: Mapped[float] = mapped_column(money(8))
    power_w: Mapped[float] = mapped_column(money(8))
    satellites: Mapped[int] = mapped_column(Integer)
    signal_percent: Mapped[int] = mapped_column(Integer)
    status: Mapped[int] = mapped_column(Integer)
    work_order_id: Mapped[int | None] = mapped_column(BigInteger)


class ChargeSession(Base):
    """充電 / 用電記錄。"""
    __tablename__ = "charge_sessions"
    __table_args__ = (Index("IX_charge_sessions_drone_id_started_at", "drone_id", "started_at"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    drone_id: Mapped[int] = mapped_column(ForeignKey("drones.id", ondelete="CASCADE"))
    started_at: Mapped[datetime] = mapped_column(TZ)
    ended_at: Mapped[datetime | None] = mapped_column(TZ)
    start_percent: Mapped[float] = mapped_column(money(5), default=0.0)
    end_percent: Mapped[float] = mapped_column(money(5), default=0.0)
    energy_wh: Mapped[float] = mapped_column(money(10), default=0.0)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    station_name: Mapped[str] = mapped_column(String(50), default="Station-A")

    drone: Mapped[Drone] = relationship(lazy="joined")


# ============================================================ 地圖與航線

class MapPoint(Base):
    __tablename__ = "map_points"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    point_type: Mapped[int] = mapped_column(Integer, default=0)
    latitude: Mapped[float] = mapped_column(Double)
    longitude: Mapped[float] = mapped_column(Double)
    altitude_m: Mapped[float] = mapped_column(Double, default=0.0)
    description: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(TZ, default=utcnow)


class FlightRoute(Base):
    __tablename__ = "flight_routes"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    total_distance_m: Mapped[float] = mapped_column(Double, default=0.0)
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=0)
    estimated_energy_wh: Mapped[float] = mapped_column(money(8), default=0.0)
    created_by: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(TZ, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZ, default=utcnow)

    waypoints: Mapped[list[RouteWaypoint]] = relationship(
        back_populates="route", cascade="all, delete-orphan", order_by="RouteWaypoint.sequence", lazy="selectin")


class RouteWaypoint(Base):
    __tablename__ = "route_waypoints"
    __table_args__ = (
        Index("IX_route_waypoints_route_id_sequence", "route_id", "sequence", unique=True),
        Index("IX_route_waypoints_map_point_id", "map_point_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("flight_routes.id", ondelete="CASCADE"))
    map_point_id: Mapped[int | None] = mapped_column(ForeignKey("map_points.id", ondelete="SET NULL"))
    sequence: Mapped[int] = mapped_column(Integer)
    latitude: Mapped[float] = mapped_column(Double)
    longitude: Mapped[float] = mapped_column(Double)
    altitude_m: Mapped[float] = mapped_column(Double, default=30.0)
    action: Mapped[int] = mapped_column(Integer, default=0)
    hover_seconds: Mapped[int] = mapped_column(Integer, default=0)

    route: Mapped[FlightRoute] = relationship(back_populates="waypoints")
    map_point: Mapped[MapPoint | None] = relationship(lazy="joined")


class RouteRevision(Base):
    """每次「儲存路線」的快照,即歷史地圖的資料來源。"""
    __tablename__ = "route_revisions"
    __table_args__ = (Index("IX_route_revisions_route_id_version", "route_id", "version", unique=True),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("flight_routes.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    snapshot_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    change_note: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(TZ, default=utcnow)

    route: Mapped[FlightRoute] = relationship(lazy="joined")


# ============================================================ 工單與記錄

class WorkOrderTemplate(Base):
    __tablename__ = "work_order_templates"
    __table_args__ = (Index("IX_work_order_templates_default_route_id", "default_route_id"),)

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(String(300))
    default_route_id: Mapped[int | None] = mapped_column(ForeignKey("flight_routes.id", ondelete="SET NULL"))
    default_priority: Mapped[int] = mapped_column(Integer, default=int(WorkOrderPriority.Normal))
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=30)
    checklist_json: Mapped[list] = mapped_column(JSONB, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(TZ, default=utcnow)

    default_route: Mapped[FlightRoute | None] = relationship(lazy="joined")


class WorkOrder(Base):
    __tablename__ = "work_orders"
    __table_args__ = (
        Index("IX_work_orders_order_no", "order_no", unique=True),
        Index("IX_work_orders_status", "status"),
        Index("IX_work_orders_created_at", "created_at"),
        Index("IX_work_orders_drone_id", "drone_id"),
        Index("IX_work_orders_route_id", "route_id"),
        Index("IX_work_orders_template_id", "template_id"),
        Index("IX_work_orders_assignee_user_id", "assignee_user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    order_no: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(String(500))
    template_id: Mapped[int | None] = mapped_column(ForeignKey("work_order_templates.id", ondelete="SET NULL"))
    route_id: Mapped[int | None] = mapped_column(ForeignKey("flight_routes.id", ondelete="SET NULL"))
    drone_id: Mapped[int | None] = mapped_column(ForeignKey("drones.id", ondelete="SET NULL"))
    status: Mapped[int] = mapped_column(Integer, default=int(WorkOrderStatus.Pending))
    priority: Mapped[int] = mapped_column(Integer, default=int(WorkOrderPriority.Normal))
    scheduled_at: Mapped[datetime | None] = mapped_column(TZ)
    started_at: Mapped[datetime | None] = mapped_column(TZ)
    completed_at: Mapped[datetime | None] = mapped_column(TZ)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    energy_used_wh: Mapped[float | None] = mapped_column(money(10))
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    assignee_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_by: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(TZ, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZ, default=utcnow)
    remark: Mapped[str | None] = mapped_column(String(500))

    template: Mapped[WorkOrderTemplate | None] = relationship(lazy="joined")
    route: Mapped[FlightRoute | None] = relationship(lazy="joined")
    drone: Mapped[Drone | None] = relationship(lazy="joined")
    assignee: Mapped[User | None] = relationship(lazy="joined")

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


class MissionLog(Base):
    __tablename__ = "mission_logs"
    __table_args__ = (
        Index("IX_mission_logs_occurred_at", "occurred_at"),
        Index("IX_mission_logs_drone_id", "drone_id"),
        Index("IX_mission_logs_work_order_id", "work_order_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    work_order_id: Mapped[int | None] = mapped_column(ForeignKey("work_orders.id", ondelete="CASCADE"))
    drone_id: Mapped[int | None] = mapped_column(ForeignKey("drones.id", ondelete="SET NULL"))
    event_type: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(String(300))
    detail_json: Mapped[dict | None] = mapped_column(JSONB)
    occurred_at: Mapped[datetime] = mapped_column(TZ, default=utcnow)

    # 清單查詢會另以 join 投影欄位,這裡保持延遲載入避免一路 join 到使用者/角色
    work_order: Mapped[WorkOrder | None] = relationship()
    drone: Mapped[Drone | None] = relationship()


class LoginLog(Base):
    __tablename__ = "login_logs"
    __table_args__ = (Index("IX_login_logs_logged_at", "logged_at"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer)
    username: Mapped[str] = mapped_column(String(50))
    ip_address: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str | None] = mapped_column(String(300))
    is_success: Mapped[bool] = mapped_column(Boolean)
    fail_reason: Mapped[str | None] = mapped_column(String(100))
    logged_at: Mapped[datetime] = mapped_column(TZ, default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_read", "user_id", "is_read", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer)  # null = 全體廣播
    level: Mapped[int] = mapped_column(Integer, default=0)
    category: Mapped[str] = mapped_column(String(30), default="system")
    title: Mapped[str] = mapped_column(String(120))
    content: Mapped[str | None] = mapped_column(String(500))
    link: Mapped[str | None] = mapped_column(String(200))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TZ, default=utcnow)
