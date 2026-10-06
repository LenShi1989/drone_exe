"""
統計聚合。先撈出區間資料後在記憶體分組 (資料量小);
量大時應改為每日彙總表或物化檢視,對外介面不變。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import permissions as P
from .. import schemas as s
from ..db import as_utc, get_db, utcnow
from ..deps import CurrentUser, get_current_user, require
from ..enums import CURRENT_STATUSES, DroneStatus, WorkOrderPriority, WorkOrderStatus, text_of
from ..models import ChargeSession, Drone, Notification, WorkOrder
from ..realtime import live_store

router = APIRouter(prefix="/api/statistics", tags=["Statistics"])


def _day_start(dt: datetime) -> datetime:
    return datetime.combine(dt.astimezone(timezone.utc).date(), time.min, tzinfo=timezone.utc)


def _range(from_: datetime | None, to: datetime | None) -> tuple[datetime, datetime]:
    end = _day_start(as_utc(to) or utcnow()) + timedelta(days=1)
    start = _day_start(as_utc(from_)) if from_ else end - timedelta(days=30)
    if start >= end:
        start = end - timedelta(days=1)
    return start, end


def _period_key(at: datetime, granularity: str) -> str:
    at = at.astimezone(timezone.utc)
    g = (granularity or "day").lower()
    if g == "month":
        return f"{at:%Y-%m}"
    if g == "week":
        year, week, _ = at.isocalendar()
        return f"{year}-W{week:02d}"
    return f"{at:%Y-%m-%d}"


def _periods(start: datetime, end: datetime, granularity: str) -> list[str]:
    """區間內所有分組鍵,用來補齊沒有資料的區間,避免折線圖出現斷點。"""
    keys: list[str] = []
    cursor = start
    g = (granularity or "day").lower()
    while cursor < end:
        key = _period_key(cursor, g)
        if not keys or keys[-1] != key:
            keys.append(key)
        if g == "month":
            month = cursor.month + 1
            cursor = cursor.replace(year=cursor.year + (month - 1) // 12, month=(month - 1) % 12 + 1, day=1)
        elif g == "week":
            cursor += timedelta(days=7)
        else:
            cursor += timedelta(days=1)
    return keys


def _stats_query(from_: datetime | None = Query(None, alias="from"), to: datetime | None = None,
                 granularity: str = "day"):
    start, end = _range(from_, to)
    return start, end, granularity


@router.get("/overview", response_model=s.OverviewDto)
def overview(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    today = _day_start(utcnow())
    drones = db.scalars(select(Drone).where(Drone.is_active.is_(True))).all()

    # 有模擬器在跑時用即時狀態,否則用 DB 快照
    snapshots = live_store.get_all()
    statuses = ([(x.status, x.battery_percent) for x in snapshots] if snapshots
                else [(d.status, float(d.battery_percent)) for d in drones])

    today_orders = db.scalars(select(WorkOrder.status).where(WorkOrder.created_at >= today)).all()
    active_orders = db.scalar(select(func.count()).select_from(WorkOrder)
                              .where(WorkOrder.status.in_([int(x) for x in CURRENT_STATUSES])))
    today_energy = db.scalar(select(func.coalesce(func.sum(ChargeSession.energy_wh), 0))
                             .where(ChargeSession.started_at >= today))
    unread = db.scalar(select(func.count()).select_from(Notification).where(
        Notification.is_read.is_(False), or_(Notification.user_id.is_(None), Notification.user_id == user.id)))

    return s.OverviewDto(
        total_drones=len(drones),
        online_drones=sum(1 for st, _ in statuses if st != DroneStatus.Offline),
        flying_drones=sum(1 for st, _ in statuses if st in (DroneStatus.Flying, DroneStatus.Returning)),
        charging_drones=sum(1 for st, _ in statuses if st == DroneStatus.Charging),
        avg_battery_percent=round(sum(b for _, b in statuses) / len(statuses), 1) if statuses else 0,
        today_work_orders=len(today_orders), active_work_orders=active_orders,
        completed_today=sum(1 for x in today_orders if x == WorkOrderStatus.Completed),
        today_energy_wh=round(float(today_energy or 0), 2), unread_notifications=unread)


@router.get("/mission-count", response_model=list[s.MissionCountPointDto])
def mission_count(q=Depends(_stats_query), db: Session = Depends(get_db),
                  _: CurrentUser = Depends(require(P.STATS_VIEW))):
    """任務數量:依區間統計完成 / 失敗 / 取消。"""
    start, end, g = q
    rows = db.execute(select(WorkOrder.created_at, WorkOrder.status)
                      .where(WorkOrder.created_at >= start, WorkOrder.created_at < end)).all()
    buckets: dict[str, s.MissionCountPointDto] = {}
    for r in rows:
        key = _period_key(r.created_at, g)
        b = buckets.setdefault(key, s.MissionCountPointDto(period=key))
        b.total += 1
        if r.status == WorkOrderStatus.Completed:
            b.completed += 1
        elif r.status == WorkOrderStatus.Failed:
            b.failed += 1
        elif r.status == WorkOrderStatus.Cancelled:
            b.cancelled += 1
    return [buckets.get(k) or s.MissionCountPointDto(period=k) for k in _periods(start, end, g)]


@router.get("/work-orders", response_model=s.WorkOrderStatsDto)
def work_orders(q=Depends(_stats_query), db: Session = Depends(get_db),
                _: CurrentUser = Depends(require(P.STATS_VIEW))):
    """工單圖表:狀態 / 優先度分佈 + 建立趨勢。"""
    start, end, g = q
    rows = db.execute(select(WorkOrder.created_at, WorkOrder.status, WorkOrder.priority)
                      .where(WorkOrder.created_at >= start, WorkOrder.created_at < end)).all()
    by_status = [s.NameCountDto(name=text_of(WorkOrderStatus, st), value=sum(1 for r in rows if r.status == st))
                 for st in WorkOrderStatus]
    by_priority = [s.NameCountDto(name=text_of(WorkOrderPriority, p), value=sum(1 for r in rows if r.priority == p))
                   for p in WorkOrderPriority]
    trend: dict[str, int] = defaultdict(int)
    for r in rows:
        trend[_period_key(r.created_at, g)] += 1
    return s.WorkOrderStatsDto(
        by_status=[x for x in by_status if x.value > 0], by_priority=by_priority,
        trend=[s.NameCountDto(name=k, value=trend.get(k, 0)) for k in _periods(start, end, g)])


@router.get("/work-order-duration", response_model=list[s.DurationPointDto])
def duration(q=Depends(_stats_query), db: Session = Depends(get_db), _: CurrentUser = Depends(require(P.STATS_VIEW))):
    """工單用時:已完成工單的平均 / 最短 / 最長分鐘數。"""
    start, end, g = q
    rows = db.execute(select(WorkOrder.completed_at, WorkOrder.duration_seconds).where(
        WorkOrder.completed_at.is_not(None), WorkOrder.duration_seconds.is_not(None),
        WorkOrder.completed_at >= start, WorkOrder.completed_at < end)).all()
    groups: dict[str, list[int]] = defaultdict(list)
    for r in rows:
        groups[_period_key(r.completed_at, g)].append(r.duration_seconds)
    result = []
    for k in _periods(start, end, g):
        secs = groups.get(k)
        if secs:
            result.append(s.DurationPointDto(period=k, avg_minutes=round(sum(secs) / len(secs) / 60, 1),
                                             min_minutes=round(min(secs) / 60, 1),
                                             max_minutes=round(max(secs) / 60, 1), count=len(secs)))
        else:
            result.append(s.DurationPointDto(period=k))
    return result


@router.get("/charging", response_model=s.ChargingStatsDto)
def charging(q=Depends(_stats_query), db: Session = Depends(get_db), _: CurrentUser = Depends(require(P.STATS_VIEW))):
    """充電圖表:區間趨勢 + 各機累計耗電。"""
    start, end, g = q
    rows = db.execute(
        select(ChargeSession.started_at, ChargeSession.energy_wh, ChargeSession.duration_seconds,
               ChargeSession.drone_id, Drone.name.label("drone_name"))
        .join(Drone, Drone.id == ChargeSession.drone_id)
        .where(ChargeSession.started_at >= start, ChargeSession.started_at < end)).all()

    groups: dict[str, list] = defaultdict(list)
    per_drone: dict[tuple[int, str], list] = defaultdict(list)
    for r in rows:
        groups[_period_key(r.started_at, g)].append(r)
        per_drone[(r.drone_id, r.drone_name)].append(r)

    trend = []
    for k in _periods(start, end, g):
        items = groups.get(k)
        if items:
            trend.append(s.ChargingPointDto(
                period=k, sessions=len(items), energy_wh=round(sum(float(i.energy_wh) for i in items), 2),
                avg_duration_minutes=round(sum(i.duration_seconds for i in items) / len(items) / 60, 1)))
        else:
            trend.append(s.ChargingPointDto(period=k))

    by_drone = sorted(
        (s.DroneEnergyDto(drone_id=did, drone_name=name, energy_wh=round(sum(float(i.energy_wh) for i in items), 2),
                          sessions=len(items)) for (did, name), items in per_drone.items()),
        key=lambda x: x.energy_wh, reverse=True)

    return s.ChargingStatsDto(trend=trend, by_drone=by_drone,
                              total_energy_wh=round(sum(float(r.energy_wh) for r in rows), 2),
                              total_sessions=len(rows))
