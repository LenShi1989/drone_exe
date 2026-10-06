"""權限碼常數。新增功能頁時,在此加碼 + seeder 加一筆 Permission/MenuItem。"""

MONITOR_VIEW = "monitor.view"

MAP_VIEW = "map.view"
MAP_EDIT = "map.edit"
MAP_HISTORY = "map.history"

DRONE_VIEW = "drone.view"
DRONE_CONFIG = "drone.config"

CAMERA_VIEW = "camera.view"
CAMERA_MANAGE = "camera.manage"

WORKORDER_VIEW = "workorder.view"
WORKORDER_MANAGE = "workorder.manage"
WORKORDER_TEMPLATE = "workorder.template"

STATS_VIEW = "stats.view"

LOG_MISSION = "log.mission"
LOG_LOGIN = "log.login"
LOG_NOTIFICATION = "log.notification"

SYSTEM_USER = "system.user"
SYSTEM_ROLE = "system.role"

# (代碼, 名稱, 群組)
ALL = [
    (MONITOR_VIEW, "即時監控", "即時監控"),
    (MAP_VIEW, "地圖檢視", "地圖管理"),
    (MAP_EDIT, "地圖編輯", "地圖管理"),
    (MAP_HISTORY, "歷史地圖", "地圖管理"),
    (DRONE_VIEW, "無人機狀態", "無人機管理"),
    (DRONE_CONFIG, "無人機設定", "無人機管理"),
    (CAMERA_VIEW, "攝影機檢視", "攝影機管理"),
    (CAMERA_MANAGE, "攝影機管理", "攝影機管理"),
    (WORKORDER_VIEW, "工單檢視", "工單管理"),
    (WORKORDER_MANAGE, "工單派工", "工單管理"),
    (WORKORDER_TEMPLATE, "工單模板", "工單管理"),
    (STATS_VIEW, "統計圖表", "統計圖表"),
    (LOG_MISSION, "任務紀錄", "記錄管理"),
    (LOG_LOGIN, "登入紀錄", "記錄管理"),
    (LOG_NOTIFICATION, "通知中心", "記錄管理"),
    (SYSTEM_USER, "帳號管理", "系統管理"),
    (SYSTEM_ROLE, "角色管理", "系統管理"),
]
