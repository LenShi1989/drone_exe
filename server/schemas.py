"""
請求 / 回應模型。JSON 一律 camelCase,與原 API 契約相同。
Python 端以 snake_case 建構 (populate_by_name)。
"""
from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from .db import as_utc

T = TypeVar("T")

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class UtcModel(CamelModel):
    """請求中的 datetime 一律正規化為 UTC (無時區者視為 UTC)。"""

    @field_validator("*", mode="after")
    @classmethod
    def _utc(cls, v):
        return as_utc(v) if isinstance(v, datetime) else v


class Paged(CamelModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class Message(CamelModel):
    message: str


# ============================================================ Auth

class LoginRequest(CamelModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=100)


class RefreshRequest(CamelModel):
    refresh_token: str = Field(min_length=1)


class ChangePasswordRequest(CamelModel):
    old_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=100)


class CurrentUserDto(CamelModel):
    id: int
    username: str
    display_name: str
    email: str
    role_code: str
    role_name: str
    permissions: list[str]
    last_login_at: datetime | None = None


class LoginResponse(CamelModel):
    access_token: str
    refresh_token: str
    expires_in: int
    user: CurrentUserDto


class MenuNodeDto(CamelModel):
    id: int
    key: str
    title: str
    icon: str
    path: str
    permission_code: str | None = None
    children: list[MenuNodeDto] = []


# ============================================================ 無人機

class DroneDto(CamelModel):
    id: int
    serial_number: str
    name: str
    model: str
    status: int
    status_text: str
    battery_percent: float
    latitude: float
    longitude: float
    altitude_m: float
    speed_mps: float
    heading_deg: float
    firmware_version: str
    battery_capacity_wh: float
    max_speed_mps: float
    max_flight_minutes: int
    home_latitude: float
    home_longitude: float
    total_flight_seconds: int
    total_energy_wh: float
    last_heartbeat_at: datetime | None = None
    is_active: bool
    current_work_order_id: int | None = None
    current_work_order_no: str | None = None
    is_patrolling: bool = False
    patrol_route_name: str | None = None


class DroneUpsertRequest(CamelModel):
    serial_number: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=50)
    model: str = Field(min_length=1, max_length=50)
    firmware_version: str = Field(default="1.0.0", max_length=30)
    battery_capacity_wh: float = Field(default=280, ge=1, le=100000)
    max_speed_mps: float = Field(default=18, ge=1, le=100)
    max_flight_minutes: int = Field(default=35, ge=1, le=600)
    home_latitude: float = Field(default=0, ge=-90, le=90)
    home_longitude: float = Field(default=0, ge=-180, le=180)
    status: int | None = Field(default=None, ge=0, le=6)
    is_active: bool = True


class SimulatedDroneRequest(CamelModel):
    count: int = Field(default=1, ge=1, le=20)
    name_prefix: str | None = Field(default=None, max_length=30)
    model: str | None = Field(default=None, max_length=50)
    battery_capacity_wh: float = Field(default=320, ge=1, le=100000)
    battery_percent: float = Field(default=100, ge=0, le=100)
    home_latitude: float | None = Field(default=None, ge=-90, le=90)
    home_longitude: float | None = Field(default=None, ge=-180, le=180)
    route_id: int | None = None
    start_patrol: bool = True
    loop: bool = True


class SimulatedDroneResult(CamelModel):
    drones: list[DroneDto]
    patrolling_count: int
    route_id: int | None = None
    route_name: str | None = None
    message: str


class DronePatrolRequest(CamelModel):
    route_id: int | None = None
    loop: bool = True


class DroneCommandRequest(CamelModel):
    command: str = Field(min_length=1)  # Return / Land / Charge / Standby


class TelemetryPointDto(CamelModel):
    recorded_at: datetime
    latitude: float
    longitude: float
    altitude_m: float
    speed_mps: float
    heading_deg: float
    battery_percent: float
    power_w: float
    status: int


class ChargeSessionDto(CamelModel):
    id: int
    drone_id: int
    drone_name: str
    started_at: datetime
    ended_at: datetime | None = None
    start_percent: float
    end_percent: float
    energy_wh: float
    duration_seconds: int
    station_name: str


class TelemetrySnapshot(CamelModel):
    """WebSocket 推播與 /drones/live 共用的即時快照。"""
    drone_id: int
    serial_number: str
    name: str
    status: int
    status_text: str
    latitude: float
    longitude: float
    altitude_m: float = 0
    speed_mps: float = 0
    heading_deg: float = 0
    battery_percent: float = 0
    voltage_v: float = 0
    current_a: float = 0
    power_w: float = 0
    satellites: int = 0
    signal_percent: int = 0
    work_order_id: int | None = None
    work_order_no: str | None = None
    patrol_route_name: str | None = None
    progress_percent: int = 0
    recorded_at: datetime


# ============================================================ 攝影機

class CameraDto(CamelModel):
    id: int
    drone_id: int
    drone_name: str
    drone_serial_number: str
    name: str
    protocol: int
    protocol_text: str
    stream_url: str
    description: str | None = None
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CameraUpsertRequest(CamelModel):
    drone_id: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=50)
    protocol: int = Field(default=0, ge=0, le=1)
    stream_url: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=200)
    sort_order: int = 0
    is_active: bool = True


# ============================================================ 地圖

class MapPointDto(CamelModel):
    id: int
    name: str
    point_type: int
    point_type_text: str
    latitude: float
    longitude: float
    altitude_m: float
    description: str | None = None
    created_at: datetime


class MapPointUpsertRequest(CamelModel):
    name: str = Field(min_length=1, max_length=50)
    point_type: int = Field(default=0, ge=0, le=5)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    altitude_m: float = Field(default=30, ge=0, le=1000)
    description: str | None = Field(default=None, max_length=200)


class RouteWaypointDto(CamelModel):
    id: int
    map_point_id: int | None = None
    map_point_name: str | None = None
    sequence: int
    latitude: float
    longitude: float
    altitude_m: float
    action: int
    hover_seconds: int


class RouteWaypointInput(CamelModel):
    map_point_id: int | None = None
    sequence: int = Field(default=1, ge=1, le=500)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    altitude_m: float = Field(default=30, ge=0, le=1000)
    action: int = Field(default=0, ge=0, le=4)
    hover_seconds: int = Field(default=0, ge=0, le=3600)


class RouteDto(CamelModel):
    id: int
    name: str
    description: str | None = None
    status: int
    status_text: str
    version: int
    total_distance_m: float
    estimated_minutes: int
    estimated_energy_wh: float
    waypoint_count: int
    created_at: datetime
    updated_at: datetime
    waypoints: list[RouteWaypointDto] = []


class RouteSaveRequest(CamelModel):
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=300)
    change_note: str | None = Field(default=None, max_length=200)
    waypoints: list[RouteWaypointInput] = []


class RouteRevisionDto(CamelModel):
    id: int
    route_id: int
    route_name: str
    version: int
    change_note: str | None = None
    created_at: datetime
    created_by_name: str | None = None
    waypoint_count: int
    total_distance_m: float


class RouteRevisionDetailDto(RouteRevisionDto):
    snapshot_json: str  # GeoJSON FeatureCollection 字串


# ============================================================ 工單

class MissionLogDto(CamelModel):
    id: int
    work_order_id: int | None = None
    work_order_no: str | None = None
    drone_id: int | None = None
    drone_name: str | None = None
    event_type: int
    event_type_text: str
    message: str
    occurred_at: datetime


class WorkOrderDto(CamelModel):
    id: int
    order_no: str
    title: str
    description: str | None = None
    template_id: int | None = None
    template_name: str | None = None
    route_id: int | None = None
    route_name: str | None = None
    drone_id: int | None = None
    drone_name: str | None = None
    status: int
    status_text: str
    priority: int
    priority_text: str
    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: int | None = None
    energy_used_wh: float | None = None
    progress_percent: int
    assignee_user_id: int | None = None
    assignee_name: str | None = None
    created_by_name: str | None = None
    created_at: datetime
    remark: str | None = None


class WorkOrderDetailDto(WorkOrderDto):
    waypoints: list[RouteWaypointDto] = []
    mission_logs: list[MissionLogDto] = []


class WorkOrderUpsertRequest(UtcModel):
    title: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    template_id: int | None = None
    route_id: int | None = None
    drone_id: int | None = None
    priority: int = Field(default=1, ge=0, le=3)
    scheduled_at: datetime | None = None
    assignee_user_id: int | None = None
    remark: str | None = Field(default=None, max_length=500)


class WorkOrderScheduleRequest(UtcModel):
    drone_id: int
    route_id: int
    scheduled_at: datetime | None = None


class WorkOrderCancelRequest(CamelModel):
    reason: str | None = Field(default=None, max_length=200)


class WorkOrderTemplateDto(CamelModel):
    id: int
    name: str
    description: str | None = None
    default_route_id: int | None = None
    default_route_name: str | None = None
    default_priority: int
    estimated_minutes: int
    checklist: list[str]
    is_active: bool
    created_at: datetime


class WorkOrderTemplateUpsertRequest(CamelModel):
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=300)
    default_route_id: int | None = None
    default_priority: int = Field(default=1, ge=0, le=3)
    estimated_minutes: int = Field(default=30, ge=1, le=1440)
    checklist: list[str] = []
    is_active: bool = True


# ============================================================ 統計

class OverviewDto(CamelModel):
    total_drones: int
    online_drones: int
    flying_drones: int
    charging_drones: int
    avg_battery_percent: float
    today_work_orders: int
    active_work_orders: int
    completed_today: int
    today_energy_wh: float
    unread_notifications: int


class MissionCountPointDto(CamelModel):
    period: str
    completed: int = 0
    failed: int = 0
    cancelled: int = 0
    total: int = 0


class NameCountDto(CamelModel):
    name: str
    value: int = 0


class WorkOrderStatsDto(CamelModel):
    by_status: list[NameCountDto]
    by_priority: list[NameCountDto]
    trend: list[NameCountDto]


class DurationPointDto(CamelModel):
    period: str
    avg_minutes: float = 0
    min_minutes: float = 0
    max_minutes: float = 0
    count: int = 0


class ChargingPointDto(CamelModel):
    period: str
    sessions: int = 0
    energy_wh: float = 0
    avg_duration_minutes: float = 0


class DroneEnergyDto(CamelModel):
    drone_id: int
    drone_name: str
    energy_wh: float
    sessions: int


class ChargingStatsDto(CamelModel):
    trend: list[ChargingPointDto]
    by_drone: list[DroneEnergyDto]
    total_energy_wh: float
    total_sessions: int


# ============================================================ 記錄

class LoginLogDto(CamelModel):
    id: int
    user_id: int | None = None
    username: str
    ip_address: str
    user_agent: str | None = None
    is_success: bool
    fail_reason: str | None = None
    logged_at: datetime


class NotificationDto(CamelModel):
    id: int
    level: int
    level_text: str
    category: str
    title: str
    content: str | None = None
    link: str | None = None
    is_read: bool
    created_at: datetime


# ============================================================ 系統管理

class UserDto(CamelModel):
    id: int
    username: str
    email: str
    display_name: str
    role_id: int
    role_name: str
    role_code: str
    is_active: bool
    last_login_at: datetime | None = None
    is_locked: bool
    created_at: datetime


class UserCreateRequest(CamelModel):
    username: str = Field(min_length=1, max_length=50)
    email: str = Field(max_length=120, pattern=EMAIL_PATTERN)
    display_name: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=8, max_length=100)
    role_id: int
    is_active: bool = True


class UserUpdateRequest(CamelModel):
    email: str = Field(max_length=120, pattern=EMAIL_PATTERN)
    display_name: str = Field(min_length=1, max_length=50)
    role_id: int
    is_active: bool = True


class ResetPasswordRequest(CamelModel):
    new_password: str = Field(min_length=8, max_length=100)


class PermissionDto(CamelModel):
    id: int
    code: str
    name: str
    group_name: str


class RoleDto(CamelModel):
    id: int
    code: str
    name: str
    description: str | None = None
    is_system: bool
    user_count: int
    permission_ids: list[int]
    permission_codes: list[str]
    created_at: datetime


class RoleUpsertRequest(CamelModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=200)
    permission_ids: list[int] = []
