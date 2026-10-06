"""
假遙測產生器。以固定 tick 推進每台無人機沿航線飛行、耗電、返航與充電,
並經 WebSocket 推播、週期性落盤。

接真機時改以 MAVLink / MQTT 來源餵 live_store 與 hub 即可,其餘不動。

執行於獨立的背景執行緒;REST 端點 (執行緒池) 透過 self.lock 與其互斥。
"""
from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from sqlalchemy import select

from . import geo
from .config import SimulatorSettings, settings
from .db import session_scope, utcnow
from .enums import (
    DroneStatus, MissionEventType, NotificationLevel, RouteStatus, WaypointAction, WorkOrderStatus, text_of,
)
from .models import ChargeSession, Drone, DroneTelemetry, FlightRoute, MissionLog, WorkOrder
from .realtime import hub, live_store
from .schemas import TelemetrySnapshot
from .services import push_notification

log = logging.getLogger("drone.simulator")


@dataclass
class SimWaypoint:
    lat: float
    lng: float
    altitude_m: float
    action: int
    hover_seconds: int
    sequence: int


@dataclass
class SimDroneState:
    """單台無人機的模擬狀態 (常駐記憶體,週期性落盤)。"""
    drone_id: int
    serial_number: str
    name: str
    battery_capacity_wh: float
    home_lat: float
    home_lng: float

    status: int = DroneStatus.Idle
    lat: float = 0.0
    lng: float = 0.0
    altitude_m: float = 0.0
    speed_mps: float = 0.0
    heading_deg: float = 0.0
    battery_percent: float = 100.0
    power_w: float = 0.0
    satellites: int = 14
    signal_percent: int = 95

    # 任務執行狀態
    work_order_id: int | None = None
    work_order_no: str | None = None
    waypoints: list[SimWaypoint] = field(default_factory=list)
    leg_index: int = 0
    leg_progress_m: float = 0.0
    hover_remain_seconds: float = 0.0
    flight_started_at: datetime | None = None
    energy_used_wh: float = 0.0
    progress_percent: int = 0
    accumulated_flight_seconds: float = 0.0

    # 巡航狀態 (不掛工單的模擬飛行,供展示用)
    is_patrol: bool = False
    patrol_loop: bool = False
    patrol_route_id: int | None = None
    patrol_route_name: str | None = None
    patrol_waypoints: list[SimWaypoint] = field(default_factory=list)

    # 充電狀態
    charge_session_id: int | None = None
    charge_start_percent: float = 0.0
    charge_started_at: datetime | None = None


class SimCommandResult(Enum):
    APPLIED = "applied"
    NOT_SIMULATED = "not_simulated"  # 模擬器未啟用或該機不在模擬中,由呼叫端直接改 DB
    BUSY = "busy"                    # 執行工單中,需先返航
    UNSUPPORTED = "unsupported"


def _route_waypoints(route: FlightRoute) -> list[SimWaypoint]:
    return [SimWaypoint(w.latitude, w.longitude, w.altitude_m, w.action, w.hover_seconds, w.sequence)
            for w in sorted(route.waypoints, key=lambda x: x.sequence)]


class DroneSimulator:
    def __init__(self, opt: SimulatorSettings):
        self.opt = opt
        self.lock = threading.RLock()
        self._states: dict[int, SimDroneState] = {}
        self._rnd = random.Random()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_telemetry_persist = 0.0
        self._last_drone_persist = 0.0
        self._last_dispatch = 0.0
        self._last_sync = 0.0

    # ------------------------------------------------------------------ 生命週期

    @property
    def enabled(self) -> bool:
        return self.opt.enabled

    def start(self) -> None:
        if not self.opt.enabled:
            log.info("無人機模擬器已停用 (simulator.enabled=false)")
            return
        self._thread = threading.Thread(target=self._run, name="drone-simulator", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        if self._stop.wait(1.0):
            return
        try:
            with self.lock:
                self._sync_states()
        except Exception:  # noqa: BLE001
            log.exception("模擬器初始同步失敗")
        self._last_sync = time.monotonic()
        log.info("無人機模擬器啟動,共 %d 台", len(self._states))

        interval = max(0.2, float(self.opt.tick_seconds))
        next_tick = time.monotonic() + interval
        while not self._stop.wait(max(0.0, next_tick - time.monotonic())):
            next_tick += interval
            if next_tick < time.monotonic():  # 落後太多 (例如 DB 卡住) 就重新對齊,不補跑
                next_tick = time.monotonic() + interval
            try:
                with self.lock:
                    self._tick(interval)
            except Exception:  # noqa: BLE001
                log.exception("模擬器 tick 發生錯誤")

    # ------------------------------------------------------------------ 機隊同步 (熱插拔)

    def try_get_state(self, drone_id: int) -> SimDroneState | None:
        return self._states.get(drone_id)

    def _sync_states(self) -> None:
        """與 drones 表對帳:新增的啟用機納入模擬,停用/刪除的移出。"""
        with session_scope() as db:
            drones = db.scalars(select(Drone).where(Drone.is_active.is_(True))).all()
        for d in drones:
            self.attach(d)
        active = {d.id for d in drones}
        for drone_id in [i for i in self._states if i not in active]:
            self.detach(drone_id)

    def attach(self, drone: Drone) -> None:
        """把一台無人機納入模擬;已在模擬中的只更新機身參數,不打斷飛行。"""
        if not self.opt.enabled:
            return
        with self.lock:
            if not drone.is_active:
                self.detach(drone.id)
                return
            existing = self._states.get(drone.id)
            if existing:
                existing.serial_number = drone.serial_number
                existing.name = drone.name
                existing.battery_capacity_wh = float(drone.battery_capacity_wh)
                existing.home_lat = drone.home_latitude
                existing.home_lng = drone.home_longitude
                return
            status = drone.status
            if status in (DroneStatus.Flying, DroneStatus.Returning):
                status = DroneStatus.Idle  # 重啟後不接續舊航程
            self._states[drone.id] = SimDroneState(
                drone_id=drone.id, serial_number=drone.serial_number, name=drone.name,
                battery_capacity_wh=float(drone.battery_capacity_wh),
                home_lat=drone.home_latitude, home_lng=drone.home_longitude,
                status=int(status), lat=drone.latitude, lng=drone.longitude,
                battery_percent=float(drone.battery_percent))
            log.info("模擬器納入無人機 %s (%s)", drone.name, drone.serial_number)

    def detach(self, drone_id: int) -> None:
        with self.lock:
            s = self._states.pop(drone_id, None)
            if s:
                log.info("模擬器移出無人機 %s (%s)", s.name, s.serial_number)
        live_store.remove(drone_id)

    # ------------------------------------------------------------------ 主迴圈

    def _tick(self, dt: float) -> None:
        now_m = time.monotonic()
        now = utcnow()

        if now_m - self._last_sync >= self.opt.sync_interval_seconds:
            self._last_sync = now_m
            self._sync_states()

        if self.opt.auto_dispatch and now_m - self._last_dispatch >= self.opt.dispatch_interval_seconds:
            self._last_dispatch = now_m
            self._dispatch()

        completed: list[tuple[SimDroneState, bool]] = []
        for state in list(self._states.values()):
            if state.status in (DroneStatus.Flying, DroneStatus.Returning):
                if self._advance_flight(state, dt):
                    completed.append((state, state.status == DroneStatus.Flying))
            elif state.status == DroneStatus.Charging:
                self._advance_charging(state, dt)
            elif state.status == DroneStatus.Idle:
                state.speed_mps = 0
                state.power_w = 4
                state.altitude_m = 0
                # 巡航機充飽後自動再起飛,形成「飛行 → 返航 → 充電 → 再飛」的循環
                if (state.is_patrol and state.patrol_loop
                        and state.battery_percent >= self.opt.patrol_resume_battery_percent):
                    self._launch_patrol(state)
                    continue
                if state.battery_percent < 95 and state.charge_started_at is None:
                    self._start_charging(state)
            else:
                state.speed_mps = 0
                state.power_w = 0

        for state, success in completed:
            self._finish_mission(state, success)

        snapshots = [self._to_snapshot(s, now) for s in self._states.values()]
        live_store.update_all(snapshots)
        hub.publish("TelemetryUpdate", snapshots)

        if now_m - self._last_drone_persist >= self.opt.persist_drone_seconds:
            self._last_drone_persist = now_m
            self._persist_drones(now)

        if now_m - self._last_telemetry_persist >= self.opt.persist_telemetry_seconds:
            self._last_telemetry_persist = now_m
            self._persist_telemetry(snapshots, now)

    # ------------------------------------------------------------------ 飛行推進

    def _advance_flight(self, s: SimDroneState, dt: float) -> bool:
        """回傳 True 表示本次 tick 完成整條航線 (含返航降落)。"""
        if len(s.waypoints) < 2:
            return True

        if s.hover_remain_seconds > 0:
            s.hover_remain_seconds -= dt
            s.speed_mps = 0
            s.power_w = 300 + self._rnd.random() * 20
            self._drain_battery(s, dt)
            return False

        frm = s.waypoints[s.leg_index]
        to = s.waypoints[s.leg_index + 1]
        leg_length = geo.distance_m(frm.lat, frm.lng, to.lat, to.lng)
        total_legs = len(s.waypoints) - 1

        speed = self.opt.cruise_speed_mps * (0.9 + self._rnd.random() * 0.2)
        s.leg_progress_m += speed * dt
        s.speed_mps = round(speed, 2)
        s.heading_deg = round(geo.bearing_deg(frm.lat, frm.lng, to.lat, to.lng), 1)

        if leg_length < 1 or s.leg_progress_m >= leg_length:
            s.lat, s.lng, s.altitude_m = to.lat, to.lng, to.altitude_m
            s.leg_progress_m = 0
            s.leg_index += 1
            s.hover_remain_seconds = to.hover_seconds
            s.progress_percent = round(100.0 * s.leg_index / total_legs)
            if s.leg_index >= total_legs:
                s.speed_mps = 0
                s.altitude_m = 0
                s.progress_percent = 100
                return True
        else:
            ratio = s.leg_progress_m / leg_length
            s.lat, s.lng = geo.interpolate(frm.lat, frm.lng, to.lat, to.lng, ratio)
            s.altitude_m = round(frm.altitude_m + (to.altitude_m - frm.altitude_m) * ratio, 1)
            s.progress_percent = round(100.0 * (s.leg_index + ratio) / total_legs)

        # 耗電模型:懸停基載 + 空氣阻力 (~v²) + 隨機擾動
        s.power_w = round(280 + 0.9 * speed * speed + self._rnd.random() * 30, 1)
        self._drain_battery(s, dt)
        s.satellites = 11 + self._rnd.randint(0, 5)
        s.signal_percent = 80 + self._rnd.randint(0, 19)

        # 低電量提前返航:把剩餘航點換成「直接回 Home」
        if s.status == DroneStatus.Flying and s.battery_percent <= self.opt.return_battery_percent:
            self._return_home(s)
        return False

    @staticmethod
    def _return_home(s: SimDroneState) -> None:
        """中止目前航段,改為從現在位置直線飛回 Home 降落。"""
        s.status = DroneStatus.Returning
        s.waypoints = [
            SimWaypoint(s.lat, s.lng, s.altitude_m, WaypointAction.FlyThrough, 0, 0),
            SimWaypoint(s.home_lat, s.home_lng, 0, WaypointAction.Land, 0, 1),
        ]
        s.leg_index = 0
        s.leg_progress_m = 0
        s.hover_remain_seconds = 0

    @staticmethod
    def _drain_battery(s: SimDroneState, dt: float) -> None:
        wh = s.power_w * dt / 3600.0
        s.energy_used_wh += wh
        s.accumulated_flight_seconds += dt
        s.battery_percent = max(0.0, round(s.battery_percent - wh / s.battery_capacity_wh * 100.0, 3))

    def _advance_charging(self, s: SimDroneState, dt: float) -> None:
        s.speed_mps = 0
        s.altitude_m = 0
        s.power_w = 0
        s.battery_percent = min(100.0, s.battery_percent + self.opt.charge_rate_percent_per_second * dt)

    # ------------------------------------------------------------------ 任務生命週期

    def _dispatch(self) -> None:
        """自動把已排程工單派給待命無人機。"""
        with session_scope() as db:
            orders = db.scalars(
                select(WorkOrder)
                .where(WorkOrder.status == WorkOrderStatus.Scheduled,
                       WorkOrder.route_id.is_not(None), WorkOrder.drone_id.is_not(None))
                .order_by(WorkOrder.scheduled_at).limit(3)).unique().all()

            for order in orders:
                state = self._states.get(order.drone_id)
                if state is None or state.status != DroneStatus.Idle or state.battery_percent < 50:
                    continue
                route = order.route
                # 與 /workorders/{id}/schedule 一致:只飛已發布、至少 2 航點的航線
                if route is None or len(route.waypoints) < 2 or route.status != RouteStatus.Published:
                    continue

                self._start_mission(state, order, route)
                now = utcnow()
                order.status = int(WorkOrderStatus.InProgress)
                order.started_at = now
                order.progress_percent = 0
                order.updated_at = now
                db.add(MissionLog(work_order_id=order.id, drone_id=order.drone_id,
                                  event_type=int(MissionEventType.Takeoff),
                                  message=f"{order.order_no} 起飛,航線「{route.name}」已載入", occurred_at=now))
                db.commit()

                hub.publish("WorkOrderChanged", {"workOrderId": order.id, "orderNo": order.order_no,
                                                 "status": int(order.status), "progressPercent": 0})
                push_notification(db, NotificationLevel.Info, "workorder", f"{order.order_no} 已起飛",
                                  f"{state.name} 開始執行「{order.title}」", "/workorder/current")

    def _start_mission(self, s: SimDroneState, order: WorkOrder, route: FlightRoute) -> None:
        wps = _route_waypoints(route)
        wps.insert(0, SimWaypoint(s.lat, s.lng, 0, WaypointAction.FlyThrough, 0, 0))  # 從目前位置切入航線
        self._reset_flight(s, wps)
        s.work_order_id = order.id
        s.work_order_no = order.order_no

    def _reset_flight(self, s: SimDroneState, wps: list[SimWaypoint]) -> None:
        s.waypoints = wps
        s.leg_index = 0
        s.leg_progress_m = 0
        s.hover_remain_seconds = 0
        s.progress_percent = 0
        s.energy_used_wh = 0
        s.accumulated_flight_seconds = 0
        s.flight_started_at = utcnow()
        s.status = DroneStatus.Flying
        s.charge_session_id = None
        s.charge_started_at = None

    # ------------------------------------------------------------------ 巡航 (不掛工單的模擬飛行)

    def start_patrol(self, drone_id: int, route: FlightRoute, loop: bool) -> bool:
        """讓模擬機沿指定航線持續飛行。不建立工單、不影響統計口徑。"""
        if not self.opt.enabled:
            return False
        with self.lock:
            s = self._states.get(drone_id)
            if s is None or s.work_order_id is not None:  # 執行工單中的機不搶飛
                return False
            wps = _route_waypoints(route)
            if len(wps) < 2:
                return False
            if s.status == DroneStatus.Charging:
                self._stop_charging(s)
            s.patrol_route_id = route.id
            s.patrol_route_name = route.name
            s.patrol_waypoints = wps
            s.patrol_loop = loop
            s.is_patrol = True
            self._launch_patrol(s)
            log.info("%s 開始模擬巡航「%s」(循環=%s)", s.name, route.name, loop)
            return True

    def stop_patrol(self, drone_id: int) -> bool:
        """停止巡航。飛行中會先返航降落,落地後才真正解除。"""
        with self.lock:
            s = self._states.get(drone_id)
            if s is None or not s.is_patrol:
                return False
            s.patrol_loop = False
            if s.status == DroneStatus.Flying:
                self._return_home(s)
            elif s.status != DroneStatus.Returning:
                self._clear_patrol(s)
            return True

    def _launch_patrol(self, s: SimDroneState) -> None:
        # 從目前位置切入航線,最後回 Home 降落,湊成可重複的一輪
        wps = list(s.patrol_waypoints)
        wps.insert(0, SimWaypoint(s.lat, s.lng, 0, WaypointAction.FlyThrough, 0, 0))
        wps.append(SimWaypoint(s.home_lat, s.home_lng, 0, WaypointAction.Land, 0, len(wps)))
        self._reset_flight(s, wps)

    @staticmethod
    def _clear_patrol(s: SimDroneState) -> None:
        s.is_patrol = False
        s.patrol_loop = False
        s.patrol_waypoints = []
        s.patrol_route_id = None
        s.patrol_route_name = None

    def _finish_patrol(self, s: SimDroneState, completed: bool, energy: float, seconds: int) -> None:
        """巡航一輪結束:累計里程耗電、寫任務紀錄,電量還夠就直接再飛一輪。"""
        with session_scope() as db:
            drone = db.get(Drone, s.drone_id)
            if drone:
                drone.total_flight_seconds += seconds
                drone.total_energy_wh = float(drone.total_energy_wh) + energy
            msg = (f"模擬巡航「{s.patrol_route_name}」完成一輪,耗時 {seconds // 60} 分 {seconds % 60} 秒,耗電 {energy} Wh"
                   if completed else
                   f"模擬巡航「{s.patrol_route_name}」因低電量返航,完成度 {s.progress_percent}%")
            db.add(MissionLog(drone_id=s.drone_id,
                              event_type=int(MissionEventType.Landing if completed else MissionEventType.Warning),
                              message=msg, occurred_at=utcnow()))

        if not s.patrol_loop:
            self._clear_patrol(s)
            return
        # 電量還夠就馬上再飛;不夠則交給 Idle 分支充電,充飽後自動續飛
        if s.battery_percent > self.opt.return_battery_percent + 10:
            self._launch_patrol(s)

    def apply_command(self, drone_id: int, command: str) -> SimCommandResult:
        """把操作員指令套進模擬狀態;只改 DB 的話會被下一次落盤覆蓋。"""
        if not self.opt.enabled:
            return SimCommandResult.NOT_SIMULATED
        with self.lock:
            s = self._states.get(drone_id)
            if s is None:
                return SimCommandResult.NOT_SIMULATED

            if command == "Return":
                s.patrol_loop = False
                if s.status in (DroneStatus.Flying, DroneStatus.Returning):
                    self._return_home(s)
                else:
                    self._clear_patrol(s)
                    s.status = DroneStatus.Idle
                return SimCommandResult.APPLIED

            if command in ("Land", "Standby"):
                if s.work_order_id is not None:
                    return SimCommandResult.BUSY
                self._clear_patrol(s)
                if s.status == DroneStatus.Charging:
                    self._stop_charging(s)
                s.waypoints = []
                s.leg_index = 0
                s.leg_progress_m = 0
                s.hover_remain_seconds = 0
                s.speed_mps = 0
                s.altitude_m = 0
                s.status = DroneStatus.Idle
                return SimCommandResult.APPLIED

            if command == "Charge":
                if s.work_order_id is not None:
                    return SimCommandResult.BUSY
                self._clear_patrol(s)
                # 空中的先返航,落地後 Idle 分支會自動接上充電
                if s.status in (DroneStatus.Flying, DroneStatus.Returning):
                    self._return_home(s)
                elif s.status != DroneStatus.Charging:
                    self._start_charging(s)
                return SimCommandResult.APPLIED

            return SimCommandResult.UNSUPPORTED

    def _finish_mission(self, s: SimDroneState, success: bool) -> None:
        work_order_id = s.work_order_id
        energy = round(s.energy_used_wh, 2)
        seconds = int(s.accumulated_flight_seconds)

        s.status = DroneStatus.Idle
        s.waypoints = []
        s.leg_index = 0
        s.leg_progress_m = 0
        s.speed_mps = 0
        s.altitude_m = 0
        s.work_order_id = None
        s.work_order_no = None
        s.lat, s.lng = s.home_lat, s.home_lng

        if work_order_id is None:
            if s.is_patrol:
                self._finish_patrol(s, success, energy, seconds)
            return

        with session_scope() as db:
            order = db.get(WorkOrder, work_order_id)
            if order is None:
                return
            now = utcnow()
            order.status = int(WorkOrderStatus.Completed if success else WorkOrderStatus.Failed)
            order.completed_at = now
            order.duration_seconds = seconds
            order.energy_used_wh = energy
            order.progress_percent = 100 if success else s.progress_percent
            order.updated_at = now
            if not success:
                order.remark = "電量不足提前返航,任務未完成"

            db.add(MissionLog(
                work_order_id=order.id, drone_id=s.drone_id,
                event_type=int(MissionEventType.Landing if success else MissionEventType.Warning),
                message=(f"{order.order_no} 降落完成,耗時 {seconds // 60} 分 {seconds % 60} 秒,耗電 {energy} Wh"
                         if success else f"{order.order_no} 因低電量返航,完成度 {s.progress_percent}%"),
                occurred_at=now))

            drone = db.get(Drone, s.drone_id)
            if drone:
                drone.total_flight_seconds += seconds
                drone.total_energy_wh = float(drone.total_energy_wh) + energy
            db.commit()

            hub.publish("WorkOrderChanged", {"workOrderId": order.id, "orderNo": order.order_no,
                                             "status": int(order.status),
                                             "progressPercent": order.progress_percent})
            push_notification(
                db, NotificationLevel.Success if success else NotificationLevel.Warning, "workorder",
                f"{order.order_no} 已完成" if success else f"{order.order_no} 提前返航",
                f"{s.name}:耗時 {seconds // 60} 分,耗電 {energy} Wh", "/workorder/history")

    # ------------------------------------------------------------------ 充電

    def _start_charging(self, s: SimDroneState) -> None:
        with session_scope() as db:
            session = ChargeSession(drone_id=s.drone_id, started_at=utcnow(), start_percent=s.battery_percent,
                                    station_name="Station-B" if s.drone_id % 2 == 0 else "Station-A")
            db.add(session)
            db.flush()
            s.status = DroneStatus.Charging
            s.charge_session_id = session.id
            s.charge_start_percent = s.battery_percent
            s.charge_started_at = session.started_at

    def _stop_charging(self, s: SimDroneState) -> None:
        """中途離開充電 (起飛或改狀態),把充電紀錄收尾避免留下未結束的 session。"""
        with session_scope() as db:
            self._complete_charging(s, db)

    def _complete_charging(self, s: SimDroneState, db) -> None:
        if s.charge_session_id is not None:
            session = db.get(ChargeSession, s.charge_session_id)
            if session:
                session.ended_at = utcnow()
                session.end_percent = round(s.battery_percent, 2)
                session.duration_seconds = int((session.ended_at - session.started_at).total_seconds())
                session.energy_wh = round(
                    s.battery_capacity_wh * (session.end_percent - float(session.start_percent)) / 100.0 * 1.08, 2)
        s.charge_session_id = None
        s.charge_started_at = None
        s.status = DroneStatus.Idle

    # ------------------------------------------------------------------ 落盤

    def _persist_drones(self, now: datetime) -> None:
        with session_scope() as db:
            drones = db.scalars(select(Drone).where(Drone.id.in_(list(self._states)))).all()
            for d in drones:
                s = self._states.get(d.id)
                if s is None:
                    continue
                # 充電完成 (≥100%) 在此收尾,順便寫回 charge_sessions
                if s.status == DroneStatus.Charging and s.battery_percent >= 100:
                    self._complete_charging(s, db)
                d.status = int(s.status)
                d.battery_percent = round(s.battery_percent, 2)
                d.latitude = s.lat
                d.longitude = s.lng
                d.altitude_m = s.altitude_m
                d.speed_mps = s.speed_mps
                d.heading_deg = s.heading_deg
                d.last_heartbeat_at = now
                d.updated_at = now

            # 執行中工單同步進度
            running = {s.work_order_id: s for s in self._states.values() if s.work_order_id is not None}
            if running:
                for o in db.scalars(select(WorkOrder).where(WorkOrder.id.in_(list(running)))).unique():
                    o.progress_percent = running[o.id].progress_percent
                    o.updated_at = now

    def _persist_telemetry(self, snapshots: list[TelemetrySnapshot], now: datetime) -> None:
        # 只記錄有意義的狀態,避免離線/維護機灌爆時序表
        keep = (DroneStatus.Flying, DroneStatus.Returning, DroneStatus.Charging)
        rows = [DroneTelemetry(
            drone_id=s.drone_id, recorded_at=now, latitude=s.latitude, longitude=s.longitude,
            altitude_m=s.altitude_m, speed_mps=s.speed_mps, heading_deg=s.heading_deg,
            battery_percent=round(s.battery_percent, 2), voltage_v=s.voltage_v, current_a=s.current_a,
            power_w=s.power_w, satellites=s.satellites, signal_percent=s.signal_percent, status=s.status,
            work_order_id=s.work_order_id) for s in snapshots if s.status in keep]
        if rows:
            with session_scope() as db:
                db.add_all(rows)

    # ------------------------------------------------------------------ 轉換

    @staticmethod
    def _to_snapshot(s: SimDroneState, now: datetime) -> TelemetrySnapshot:
        # 6S 鋰電:滿電 25.2V,空電 19.8V,依電量線性內插
        voltage = round(19.8 + (25.2 - 19.8) * s.battery_percent / 100.0, 2)
        current = round(s.power_w / voltage, 2) if voltage > 0 else 0.0
        return TelemetrySnapshot(
            drone_id=s.drone_id, serial_number=s.serial_number, name=s.name,
            status=int(s.status), status_text=text_of(DroneStatus, s.status),
            latitude=round(s.lat, 7), longitude=round(s.lng, 7), altitude_m=round(s.altitude_m, 1),
            speed_mps=round(s.speed_mps, 2), heading_deg=round(s.heading_deg, 1),
            battery_percent=round(s.battery_percent, 1), voltage_v=voltage, current_a=current,
            power_w=round(s.power_w, 1), satellites=s.satellites, signal_percent=s.signal_percent,
            work_order_id=s.work_order_id, work_order_no=s.work_order_no,
            patrol_route_name=s.patrol_route_name if s.is_patrol else None,
            progress_percent=s.progress_percent, recorded_at=now)


simulator = DroneSimulator(settings.simulator)
