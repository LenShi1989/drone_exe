"""列舉與中文顯示字串。數值與原 C# 版完全一致,資料庫可共用。"""
from enum import IntEnum


class DroneStatus(IntEnum):
    Offline = 0
    Idle = 1
    Flying = 2
    Returning = 3
    Charging = 4
    Maintenance = 5
    Error = 6


class MapPointType(IntEnum):
    Waypoint = 0
    Takeoff = 1
    Landing = 2
    ChargingStation = 3
    Poi = 4
    NoFlyMarker = 5


class RouteStatus(IntEnum):
    Draft = 0
    Published = 1
    Archived = 2


class WaypointAction(IntEnum):
    FlyThrough = 0
    Hover = 1
    Photo = 2
    Scan = 3
    Land = 4


class WorkOrderStatus(IntEnum):
    Pending = 0
    Scheduled = 1
    InProgress = 2
    Completed = 3
    Cancelled = 4
    Failed = 5


TERMINAL_STATUSES = (WorkOrderStatus.Completed, WorkOrderStatus.Cancelled, WorkOrderStatus.Failed)
CURRENT_STATUSES = (WorkOrderStatus.Pending, WorkOrderStatus.Scheduled, WorkOrderStatus.InProgress)


class WorkOrderPriority(IntEnum):
    Low = 0
    Normal = 1
    High = 2
    Urgent = 3


class MissionEventType(IntEnum):
    Info = 0
    Takeoff = 1
    Waypoint = 2
    Landing = 3
    Warning = 4
    Error = 5


class NotificationLevel(IntEnum):
    Info = 0
    Success = 1
    Warning = 2
    Error = 3


class CameraProtocol(IntEnum):
    Http = 0
    Rtsp = 1


_TEXT = {
    DroneStatus: {0: "離線", 1: "待命", 2: "飛行中", 3: "返航中", 4: "充電中", 5: "維護中", 6: "異常"},
    MapPointType: {0: "航點", 1: "起飛點", 2: "降落點", 3: "充電站", 4: "興趣點", 5: "禁飛標記"},
    RouteStatus: {0: "草稿", 1: "已發布", 2: "已封存"},
    WorkOrderStatus: {0: "待處理", 1: "已排程", 2: "執行中", 3: "已完成", 4: "已取消", 5: "失敗"},
    WorkOrderPriority: {0: "低", 1: "一般", 2: "高", 3: "緊急"},
    MissionEventType: {0: "訊息", 1: "起飛", 2: "航點", 3: "降落", 4: "警告", 5: "錯誤"},
    NotificationLevel: {0: "資訊", 1: "成功", 2: "警告", 3: "錯誤"},
    CameraProtocol: {0: "HTTP", 1: "RTSP"},
}


def text_of(enum_type: type[IntEnum], value: int) -> str:
    """列舉值的中文顯示字串,集中管理避免各處各自維護。"""
    try:
        return _TEXT[enum_type][int(value)]
    except KeyError:
        return str(value)
