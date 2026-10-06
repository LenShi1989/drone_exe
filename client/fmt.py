"""顯示格式、列舉文字與配色 (與原 Vue 版 utils/format.ts 對應)。"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from enum import IntEnum


class DroneStatus(IntEnum):
    Offline = 0
    Idle = 1
    Flying = 2
    Returning = 3
    Charging = 4
    Maintenance = 5
    Error = 6


class WorkOrderStatus(IntEnum):
    Pending = 0
    Scheduled = 1
    InProgress = 2
    Completed = 3
    Cancelled = 4
    Failed = 5


class RouteStatus(IntEnum):
    Draft = 0
    Published = 1
    Archived = 2


class MapPointType(IntEnum):
    Waypoint = 0
    Takeoff = 1
    Landing = 2
    ChargingStation = 3
    Poi = 4
    NoFlyMarker = 5


class WaypointAction(IntEnum):
    FlyThrough = 0
    Hover = 1
    Photo = 2
    Scan = 3
    Land = 4


# ---------------------------------------------------------------- 色票

ACCENT = "#00e5ff"
ACCENT_2 = "#7c5cff"
OK = "#22e39b"
WARN = "#ffb43a"
DANGER = "#ff4d6d"
INFO = "#4da3ff"
TEXT = "#dceaf7"
TEXT_DIM = "#8ba3c0"
TEXT_FAINT = "#5d738f"

# tag 類別 → (文字色, 背景 rgba, 邊框 rgba)
TAG_STYLES = {
    "accent": (ACCENT, "rgba(0,229,255,0.12)", "rgba(0,229,255,0.45)"),
    "ok": (OK, "rgba(34,227,155,0.12)", "rgba(34,227,155,0.45)"),
    "warn": (WARN, "rgba(255,180,58,0.12)", "rgba(255,180,58,0.45)"),
    "danger": (DANGER, "rgba(255,77,109,0.12)", "rgba(255,77,109,0.45)"),
    "info": (INFO, "rgba(77,163,255,0.12)", "rgba(77,163,255,0.45)"),
    "dim": (TEXT_DIM, "rgba(139,163,192,0.10)", "rgba(139,163,192,0.35)"),
    "violet": (ACCENT_2, "rgba(124,92,255,0.14)", "rgba(124,92,255,0.5)"),
}

# ---------------------------------------------------------------- 列舉文字 / tag

DRONE_STATUS_TEXT = {0: "離線", 1: "待命", 2: "飛行中", 3: "返航中", 4: "充電中", 5: "維護中", 6: "異常"}
DRONE_STATUS_TAG = {0: "dim", 1: "info", 2: "accent", 3: "warn", 4: "ok", 5: "warn", 6: "danger"}
DRONE_STATUS_COLOR = {0: "#5d738f", 1: INFO, 2: ACCENT, 3: WARN, 4: OK, 5: WARN, 6: DANGER}

WORK_ORDER_STATUS_TEXT = {0: "待處理", 1: "已排程", 2: "執行中", 3: "已完成", 4: "已取消", 5: "失敗"}
WORK_ORDER_STATUS_TAG = {0: "dim", 1: "info", 2: "accent", 3: "ok", 4: "dim", 5: "danger"}

PRIORITY_TEXT = {0: "低", 1: "一般", 2: "高", 3: "緊急"}
PRIORITY_TAG = {0: "dim", 1: "info", 2: "warn", 3: "danger"}

ROUTE_STATUS_TEXT = {0: "草稿", 1: "已發布", 2: "已封存"}
ROUTE_STATUS_TAG = {0: "dim", 1: "ok", 2: "warn"}

POINT_TYPE_TEXT = {0: "航點", 1: "起飛點", 2: "降落點", 3: "充電站", 4: "興趣點", 5: "禁飛標記"}
POINT_TYPE_COLOR = {0: ACCENT, 1: OK, 2: INFO, 3: WARN, 4: ACCENT_2, 5: DANGER}

WAYPOINT_ACTION_TEXT = {0: "通過", 1: "懸停", 2: "拍照", 3: "掃描", 4: "降落"}
WAYPOINT_ACTION_BY_NAME = {"FlyThrough": "通過", "Hover": "懸停", "Photo": "拍照", "Scan": "掃描", "Land": "降落"}

MISSION_EVENT_TEXT = {0: "訊息", 1: "起飛", 2: "航點", 3: "降落", 4: "警告", 5: "錯誤"}
MISSION_EVENT_TAG = {0: "dim", 1: "accent", 2: "info", 3: "ok", 4: "warn", 5: "danger"}

NOTIFICATION_LEVEL_TEXT = {0: "資訊", 1: "成功", 2: "警告", 3: "錯誤"}
NOTIFICATION_LEVEL_TAG = {0: "info", 1: "ok", 2: "warn", 3: "danger"}

NOTIFICATION_CATEGORY_TEXT = {"drone": "無人機", "workorder": "工單", "system": "系統"}

CAMERA_PROTOCOL_TEXT = {0: "HTTP", 1: "RTSP"}


# ---------------------------------------------------------------- 時間

def parse_dt(value) -> datetime | None:
    """伺服器回傳的 UTC ISO 字串 → 本地時區 datetime。"""
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            # Python 3.10 的 fromisoformat 不接受 7 位以上小數秒
            head, _, tail = text.partition(".")
            frac = "".join(ch for ch in tail if ch.isdigit())[:6]
            zone = tail[len("".join(ch for ch in tail if ch.isdigit())):]
            dt = datetime.fromisoformat(f"{head}.{frac.ljust(6, '0')}{zone}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone()


def fmt_datetime(value, with_seconds: bool = False) -> str:
    dt = parse_dt(value)
    if dt is None:
        return "—"
    return dt.strftime("%Y-%m-%d %H:%M:%S" if with_seconds else "%Y-%m-%d %H:%M")


def fmt_date(value) -> str:
    dt = parse_dt(value)
    return dt.strftime("%Y-%m-%d") if dt else "—"


def fmt_time(value) -> str:
    dt = parse_dt(value) if not isinstance(value, datetime) else value
    return dt.strftime("%H:%M:%S") if dt else "—"


def fmt_ago(value) -> str:
    dt = parse_dt(value)
    if dt is None:
        return "—"
    sec = int((datetime.now(timezone.utc) - dt).total_seconds())
    if sec < 10:
        return "剛剛"
    if sec < 60:
        return f"{sec} 秒前"
    minutes = sec // 60
    if minutes < 60:
        return f"{minutes} 分鐘前"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} 小時前"
    return f"{hours // 24} 天前"


def fmt_duration(seconds) -> str:
    if seconds is None:
        return "—"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} 秒"
    h, m, s = seconds // 3600, (seconds % 3600) // 60, seconds % 60
    return f"{h} 時 {m} 分" if h > 0 else f"{m} 分 {s} 秒"


def fmt_num(value, digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{float(value):.{digits}f}"


def fmt_distance(meters) -> str:
    if meters is None:
        return "—"
    meters = float(meters)
    return f"{meters / 1000:.2f} km" if meters >= 1000 else f"{meters:.0f} m"


def day_offset(days: int) -> date:
    return date.today() + timedelta(days=days)


def local_day_start_utc(d: date) -> str:
    """本地日期 00:00:00 → UTC ISO 字串 (查詢參數用)。"""
    return datetime(d.year, d.month, d.day).astimezone().astimezone(timezone.utc).isoformat()


def local_day_end_utc(d: date) -> str:
    return datetime(d.year, d.month, d.day, 23, 59, 59).astimezone().astimezone(timezone.utc).isoformat()


def local_to_utc_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.astimezone(timezone.utc).isoformat()
