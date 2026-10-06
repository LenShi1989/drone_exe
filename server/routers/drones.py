from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import permissions as P
from .. import schemas as s
from ..db import as_utc, get_db, utcnow
from ..deps import CurrentUser, bad_request, conflict, not_found, require
from ..enums import DroneStatus, MapPointType, MissionEventType, RouteStatus, WorkOrderStatus, text_of
from ..models import ChargeSession, Drone, DroneTelemetry, FlightRoute, MapPoint, MissionLog, RouteWaypoint, WorkOrder
from ..realtime import live_store
from ..services import drone_dto
from ..simulator import SimCommandResult, simulator

router = APIRouter(prefix="/api/drones", tags=["Drones"])

SIM_SERIAL_PREFIX = "SIM-"


def _to_dto(d: Drone, wo_id: int | None = None, wo_no: str | None = None) -> s.DroneDto:
    state = simulator.try_get_state(d.id)
    patrolling = bool(state and state.is_patrol)
    return drone_dto(d, wo_id, wo_no, state.patrol_route_name if patrolling else None, patrolling)


@router.get("/live", response_model=list[s.TelemetrySnapshot])
def live(db: Session = Depends(get_db), _: CurrentUser = Depends(require(P.MONITOR_VIEW))):
    """即時監控快照。優先取模擬器記憶體資料,沒有時 fallback 到 DB 最新值。"""
    snapshots = live_store.get_all()
    if snapshots:
        return snapshots
    drones = db.scalars(select(Drone).where(Drone.is_active.is_(True)).order_by(Drone.id)).all()
    return [s.TelemetrySnapshot(
        drone_id=d.id, serial_number=d.serial_number, name=d.name, status=d.status,
        status_text=text_of(DroneStatus, d.status), latitude=d.latitude, longitude=d.longitude,
        altitude_m=d.altitude_m, speed_mps=d.speed_mps, heading_deg=d.heading_deg,
        battery_percent=d.battery_percent, recorded_at=d.last_heartbeat_at or d.updated_at) for d in drones]


@router.get("", response_model=s.Paged[s.DroneDto])
def list_drones(
    status: int | None = None, keyword: str | None = None, is_active: bool | None = Query(None, alias="isActive"),
    page: int = 1, page_size: int = Query(20, alias="pageSize"),
    db: Session = Depends(get_db), _: CurrentUser = Depends(require(P.DRONE_VIEW)),
):
    page, page_size = max(1, page), page_size if 1 <= page_size <= 200 else 20
    q = select(Drone)
    if status is not None:
        q = q.where(Drone.status == status)
    if is_active is not None:
        q = q.where(Drone.is_active.is_(is_active))
    if keyword and keyword.strip():
        kw = f"%{keyword.strip()}%"
        q = q.where(or_(Drone.name.ilike(kw), Drone.serial_number.ilike(kw), Drone.model.ilike(kw)))

    total = db.scalar(select(func.count()).select_from(q.subquery()))
    drones = db.scalars(q.order_by(Drone.id).offset((page - 1) * page_size).limit(page_size)).all()

    ids = [d.id for d in drones]
    running = {}
    if ids:
        for row in db.execute(select(WorkOrder.id, WorkOrder.order_no, WorkOrder.drone_id)
                              .where(WorkOrder.status == WorkOrderStatus.InProgress, WorkOrder.drone_id.in_(ids))):
            running[row.drone_id] = (row.id, row.order_no)

    items = [_to_dto(d, *running.get(d.id, (None, None))) for d in drones]
    return s.Paged[s.DroneDto](items=items, total=total, page=page, page_size=page_size)


@router.get("/{drone_id}", response_model=s.DroneDto)
def get_drone(drone_id: int, db: Session = Depends(get_db), _: CurrentUser = Depends(require(P.DRONE_VIEW))):
    drone = db.get(Drone, drone_id)
    if drone is None:
        raise not_found("無人機不存在")
    wo = db.execute(select(WorkOrder.id, WorkOrder.order_no)
                    .where(WorkOrder.drone_id == drone_id, WorkOrder.status == WorkOrderStatus.InProgress)).first()
    return _to_dto(drone, wo.id if wo else None, wo.order_no if wo else None)


@router.post("", response_model=s.DroneDto, status_code=201)
def create_drone(body: s.DroneUpsertRequest, db: Session = Depends(get_db),
                 _: CurrentUser = Depends(require(P.DRONE_CONFIG))):
    if db.scalar(select(Drone.id).where(Drone.serial_number == body.serial_number)):
        raise conflict("序號已存在")
    drone = Drone(
        serial_number=body.serial_number, name=body.name, model=body.model, firmware_version=body.firmware_version,
        battery_capacity_wh=body.battery_capacity_wh, max_speed_mps=body.max_speed_mps,
        max_flight_minutes=body.max_flight_minutes, home_latitude=body.home_latitude,
        home_longitude=body.home_longitude, latitude=body.home_latitude, longitude=body.home_longitude,
        status=body.status if body.status is not None else int(DroneStatus.Offline), is_active=body.is_active)
    db.add(drone)
    db.commit()
    simulator.attach(drone)  # 立即納入模擬,不必重啟服務
    return _to_dto(drone)


def _resolve_home(db: Session, body: s.SimulatedDroneRequest) -> tuple[float, float]:
    """模擬機起降點:指定值 > 既有起降場點位 > 既有無人機返航點。"""
    if body.home_latitude is not None and body.home_longitude is not None:
        return body.home_latitude, body.home_longitude
    takeoff = db.execute(select(MapPoint.latitude, MapPoint.longitude)
                         .where(MapPoint.point_type == MapPointType.Takeoff).order_by(MapPoint.id)).first()
    if takeoff:
        return takeoff.latitude, takeoff.longitude
    home = db.execute(select(Drone.home_latitude, Drone.home_longitude).order_by(Drone.id)).first()
    return (home.home_latitude, home.home_longitude) if home else (25.0559, 121.6156)


def _resolve_patrol_route(db: Session, route_id: int | None) -> FlightRoute | None:
    """取巡航航線:指定的必須已發布,未指定時挑第一條可用的已發布航線。"""
    wp_count = (select(func.count()).select_from(RouteWaypoint)
                .where(RouteWaypoint.route_id == FlightRoute.id).scalar_subquery())
    q = select(FlightRoute).where(FlightRoute.status == RouteStatus.Published, wp_count >= 2)
    if route_id is not None:
        q = q.where(FlightRoute.id == route_id)
    return db.scalars(q.order_by(FlightRoute.id).limit(1)).first()


@router.post("/simulated", response_model=s.SimulatedDroneResult)
def create_simulated(body: s.SimulatedDroneRequest, db: Session = Depends(get_db),
                     _: CurrentUser = Depends(require(P.DRONE_CONFIG))):
    """一鍵產生模擬機:自動編號建檔、納入模擬器,並可立即沿航線巡航。"""
    if not simulator.enabled:
        raise bad_request("模擬器已停用 (simulator.enabled=false),無法新增模擬機")

    home_lat, home_lng = _resolve_home(db, body)
    prefix = (body.name_prefix or "").strip() or "模擬機"
    model = (body.model or "").strip() or "SimDrone-X"

    used = db.scalars(select(Drone.serial_number).where(Drone.serial_number.like(f"{SIM_SERIAL_PREFIX}%"))).all()
    numbers = [int(x[len(SIM_SERIAL_PREFIX):]) for x in used if x[len(SIM_SERIAL_PREFIX):].isdigit()]
    next_index = max(numbers, default=0) + 1

    now = utcnow()
    created: list[Drone] = []
    for i in range(body.count):
        index = next_index + i
        lat = home_lat + (i % 4) * 0.00035  # 稍微錯開起降點,避免地圖上的標記完全重疊
        lng = home_lng + (i // 4) * 0.00045
        d = Drone(serial_number=f"{SIM_SERIAL_PREFIX}{index:03d}", name=f"{prefix}-{index:02d}", model=model,
                  firmware_version="sim-1.0", battery_capacity_wh=body.battery_capacity_wh,
                  battery_percent=body.battery_percent, max_speed_mps=18, max_flight_minutes=35,
                  home_latitude=lat, home_longitude=lng, latitude=lat, longitude=lng,
                  status=int(DroneStatus.Idle), last_heartbeat_at=now, is_active=True)
        db.add(d)
        created.append(d)
    db.commit()
    for d in created:
        simulator.attach(d)

    route = None
    patrolling = 0
    if body.start_patrol:
        route = _resolve_patrol_route(db, body.route_id)
        if route is not None:
            patrolling = sum(1 for d in created if simulator.start_patrol(d.id, route, body.loop))

    for d in created:
        db.add(MissionLog(drone_id=d.id, event_type=int(MissionEventType.Info),
                          message=f"新增模擬機 {d.name} ({d.serial_number})"
                                  + (f",指派巡航航線「{route.name}」" if route else "")))
    db.commit()

    if body.start_patrol and route is None:
        message = f"已新增 {len(created)} 台模擬機;目前沒有已發布的航線,待命中"
    elif patrolling > 0:
        message = f"已新增 {len(created)} 台模擬機,其中 {patrolling} 台開始巡航「{route.name}」"
    else:
        message = f"已新增 {len(created)} 台模擬機"

    return s.SimulatedDroneResult(drones=[_to_dto(d) for d in created], patrolling_count=patrolling,
                                  route_id=route.id if route else None, route_name=route.name if route else None,
                                  message=message)


@router.post("/{drone_id}/patrol")
def start_patrol(drone_id: int, body: s.DronePatrolRequest | None = None, db: Session = Depends(get_db),
                 _: CurrentUser = Depends(require(P.DRONE_CONFIG))):
    """讓模擬機沿航線巡航 (不產生工單),用於監控畫面展示。"""
    body = body or s.DronePatrolRequest()
    if not simulator.enabled:
        raise bad_request("模擬器已停用,無法指派巡航")
    drone = db.get(Drone, drone_id)
    if drone is None:
        raise not_found("無人機不存在")
    if not drone.is_active:
        raise bad_request("無人機已停用,請先啟用")
    route = _resolve_patrol_route(db, body.route_id)
    if route is None:
        raise bad_request("找不到可用的已發布航線 (至少需 2 個航點)")
    if not simulator.start_patrol(drone_id, route, body.loop):
        raise bad_request("該無人機正在執行工單或尚未納入模擬,無法開始巡航")
    db.add(MissionLog(drone_id=drone_id, event_type=int(MissionEventType.Takeoff),
                      message=f"{drone.name} 開始模擬巡航「{route.name}」" + (" (循環)" if body.loop else "")))
    db.commit()
    return {"routeId": route.id, "routeName": route.name}


@router.delete("/{drone_id}/patrol", status_code=204)
def stop_patrol(drone_id: int, db: Session = Depends(get_db), _: CurrentUser = Depends(require(P.DRONE_CONFIG))):
    """停止巡航。飛行中會先返航降落。"""
    if not simulator.stop_patrol(drone_id):
        raise bad_request("該無人機目前沒有進行中的巡航")
    db.add(MissionLog(drone_id=drone_id, event_type=int(MissionEventType.Info), message="操作員停止模擬巡航,返航降落"))
    db.commit()
    return Response(status_code=204)


@router.put("/{drone_id}", response_model=s.DroneDto)
def update_drone(drone_id: int, body: s.DroneUpsertRequest, db: Session = Depends(get_db),
                 _: CurrentUser = Depends(require(P.DRONE_CONFIG))):
    drone = db.get(Drone, drone_id)
    if drone is None:
        raise not_found("無人機不存在")
    if db.scalar(select(Drone.id).where(Drone.serial_number == body.serial_number, Drone.id != drone_id)):
        raise conflict("序號已存在")
    drone.serial_number = body.serial_number
    drone.name = body.name
    drone.model = body.model
    drone.firmware_version = body.firmware_version
    drone.battery_capacity_wh = body.battery_capacity_wh
    drone.max_speed_mps = body.max_speed_mps
    drone.max_flight_minutes = body.max_flight_minutes
    drone.home_latitude = body.home_latitude
    drone.home_longitude = body.home_longitude
    drone.is_active = body.is_active
    if body.status is not None:
        drone.status = body.status
    drone.updated_at = utcnow()
    db.commit()
    simulator.attach(drone)  # 啟用狀態或機身參數異動時同步模擬器 (停用會自動移出)
    return _to_dto(drone)


@router.delete("/{drone_id}", status_code=204)
def disable_drone(drone_id: int, db: Session = Depends(get_db), _: CurrentUser = Depends(require(P.DRONE_CONFIG))):
    """停用 (軟刪除)。有執行中工單時拒絕。"""
    drone = db.get(Drone, drone_id)
    if drone is None:
        raise not_found("無人機不存在")
    if db.scalar(select(WorkOrder.id).where(WorkOrder.drone_id == drone_id,
                                            WorkOrder.status == WorkOrderStatus.InProgress)):
        raise bad_request("該無人機仍有執行中的工單,無法停用")
    drone.is_active = False
    drone.status = int(DroneStatus.Offline)
    drone.updated_at = utcnow()
    db.commit()
    simulator.detach(drone_id)
    return Response(status_code=204)


@router.get("/{drone_id}/telemetry", response_model=list[s.TelemetryPointDto])
def telemetry(drone_id: int, from_: datetime | None = Query(None, alias="from"), to: datetime | None = None,
              limit: int = 500, db: Session = Depends(get_db), _: CurrentUser = Depends(require(P.DRONE_VIEW))):
    start = as_utc(from_) or utcnow() - timedelta(hours=6)
    end = as_utc(to) or utcnow()
    limit = min(5000, max(1, limit))
    rows = db.scalars(select(DroneTelemetry)
                      .where(DroneTelemetry.drone_id == drone_id, DroneTelemetry.recorded_at >= start,
                             DroneTelemetry.recorded_at <= end)
                      .order_by(DroneTelemetry.recorded_at.desc()).limit(limit)).all()
    # 回傳時間正序,方便直接畫線
    return [s.TelemetryPointDto(recorded_at=t.recorded_at, latitude=t.latitude, longitude=t.longitude,
                                altitude_m=t.altitude_m, speed_mps=t.speed_mps, heading_deg=t.heading_deg,
                                battery_percent=t.battery_percent, power_w=t.power_w, status=t.status)
            for t in reversed(rows)]


@router.get("/{drone_id}/charge-sessions", response_model=list[s.ChargeSessionDto])
def charge_sessions(drone_id: int, limit: int = 50, db: Session = Depends(get_db),
                    _: CurrentUser = Depends(require(P.DRONE_VIEW))):
    rows = db.scalars(select(ChargeSession).where(ChargeSession.drone_id == drone_id)
                      .order_by(ChargeSession.started_at.desc()).limit(min(500, max(1, limit)))).all()
    return [s.ChargeSessionDto(id=c.id, drone_id=c.drone_id, drone_name=c.drone.name, started_at=c.started_at,
                               ended_at=c.ended_at, start_percent=c.start_percent, end_percent=c.end_percent,
                               energy_wh=c.energy_wh, duration_seconds=c.duration_seconds,
                               station_name=c.station_name) for c in rows]


@router.post("/{drone_id}/command", status_code=204)
def command(drone_id: int, body: s.DroneCommandRequest, db: Session = Depends(get_db),
            _: CurrentUser = Depends(require(P.DRONE_CONFIG))):
    """下達指令。模擬中的機由模擬器套用;接真機時改為送 MAVLink 指令。"""
    if body.command not in ("Return", "Land", "Charge", "Standby"):
        raise bad_request("不支援的指令")
    drone = db.get(Drone, drone_id)
    if drone is None:
        raise not_found("無人機不存在")

    applied = simulator.apply_command(drone_id, body.command)
    if applied == SimCommandResult.BUSY:
        raise bad_request("該無人機正在執行工單,請先下達返航指令")
    if applied == SimCommandResult.NOT_SIMULATED:
        drone.status = int({"Return": DroneStatus.Returning, "Charge": DroneStatus.Charging}
                           .get(body.command, DroneStatus.Idle))

    drone.updated_at = utcnow()
    db.add(MissionLog(drone_id=drone.id, event_type=int(MissionEventType.Info),
                      message=f"操作員下達指令:{body.command}"))
    db.commit()
    return Response(status_code=204)
