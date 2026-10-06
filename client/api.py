"""
REST 用戶端。access token 過期 (401) 時自動以 refresh token 換新並重送一次。
所有方法皆為同步呼叫,GUI 端請透過 client.tasks.run_async 在背景執行。
"""
from __future__ import annotations

import threading
from typing import Any

import requests

from .config import settings


class ApiError(Exception):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.message = message
        self.status = status


def error_message(exc: BaseException, fallback: str = "操作失敗") -> str:
    if isinstance(exc, ApiError):
        return exc.message or fallback
    if isinstance(exc, requests.ConnectionError):
        return f"{fallback}:無法連線到伺服器 {settings.server_url}"
    if isinstance(exc, requests.Timeout):
        return f"{fallback}:伺服器回應逾時"
    return f"{fallback}:{exc}"


def _clean(params: dict | None) -> dict | None:
    if not params:
        return None
    return {k: v for k, v in params.items() if v is not None and v != ""}


class ApiClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "DroneClient/1.0 (PyQt5)"
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.user: dict | None = None
        self._refresh_lock = threading.Lock()
        self.on_session_expired = None  # callable,refresh 也失敗時呼叫 (回登入頁)

    # ------------------------------------------------------------------ 核心

    def _request(self, method: str, path: str, *, params=None, json=None, auth=True, retry=True) -> Any:
        headers = {}
        token = self.access_token
        if auth and token:
            headers["Authorization"] = f"Bearer {token}"
        resp = self.session.request(method, self.base_url + path, params=_clean(params), json=json,
                                    headers=headers, timeout=settings.request_timeout)

        if resp.status_code == 401 and auth and retry and self.refresh_token:
            if self._try_refresh(token):
                return self._request(method, path, params=params, json=json, auth=auth, retry=False)
            if self.on_session_expired:
                self.on_session_expired()

        if resp.status_code >= 400:
            try:
                body = resp.json()
                message = body.get("message") or resp.reason
            except ValueError:
                message = resp.text[:200] or resp.reason
            if resp.status_code == 403:
                message = message or "權限不足"
            raise ApiError(message, resp.status_code)

        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    def _try_refresh(self, failed_token: str | None) -> bool:
        with self._refresh_lock:
            if self.access_token and self.access_token != failed_token:
                return True  # 其他執行緒已換好新 token
            try:
                data = self._request("POST", "/api/auth/refresh", json={"refreshToken": self.refresh_token},
                                     auth=False, retry=False)
            except (ApiError, requests.RequestException):
                return False
            self._apply_login(data)
            return True

    def _apply_login(self, data: dict) -> None:
        self.access_token = data["accessToken"]
        self.refresh_token = data["refreshToken"]
        self.user = data["user"]

    def get(self, path, **params):
        return self._request("GET", path, params=params)

    def post(self, path, body=None, **params):
        return self._request("POST", path, json=body if body is not None else {}, params=params)

    def put(self, path, body=None):
        return self._request("PUT", path, json=body or {})

    def delete(self, path):
        return self._request("DELETE", path)

    # ------------------------------------------------------------------ Auth

    def login(self, username: str, password: str) -> dict:
        data = self._request("POST", "/api/auth/login", json={"username": username, "password": password},
                             auth=False, retry=False)
        self._apply_login(data)
        return data["user"]

    def logout(self) -> None:
        try:
            if self.refresh_token:
                self._request("POST", "/api/auth/logout", json={"refreshToken": self.refresh_token}, retry=False)
        finally:
            self.access_token = self.refresh_token = None
            self.user = None

    def can(self, code: str) -> bool:
        return bool(self.user and code in self.user.get("permissions", []))

    def health(self) -> dict:
        return self._request("GET", "/health", auth=False, retry=False)

    def menu(self) -> list[dict]:
        return self.get("/api/menu")

    def change_password(self, old: str, new: str):
        return self.post("/api/auth/change-password", {"oldPassword": old, "newPassword": new})

    # ------------------------------------------------------------------ 無人機

    def drones(self, **q) -> dict:
        return self.get("/api/drones", **q)

    def drones_live(self) -> list[dict]:
        return self.get("/api/drones/live")

    def drone_create(self, body):
        return self.post("/api/drones", body)

    def drone_update(self, drone_id, body):
        return self.put(f"/api/drones/{drone_id}", body)

    def drone_disable(self, drone_id):
        return self.delete(f"/api/drones/{drone_id}")

    def drone_telemetry(self, drone_id, **q):
        return self.get(f"/api/drones/{drone_id}/telemetry", **q)

    def drone_charge_sessions(self, drone_id, **q):
        return self.get(f"/api/drones/{drone_id}/charge-sessions", **q)

    def drone_command(self, drone_id, command: str):
        return self.post(f"/api/drones/{drone_id}/command", {"command": command})

    def drone_simulated(self, body):
        return self.post("/api/drones/simulated", body)

    def drone_start_patrol(self, drone_id, route_id=None, loop=True):
        return self.post(f"/api/drones/{drone_id}/patrol", {"routeId": route_id, "loop": loop})

    def drone_stop_patrol(self, drone_id):
        return self.delete(f"/api/drones/{drone_id}/patrol")

    # ------------------------------------------------------------------ 攝影機

    def cameras(self, **q):
        return self.get("/api/cameras", **q)

    def camera_create(self, body):
        return self.post("/api/cameras", body)

    def camera_update(self, camera_id, body):
        return self.put(f"/api/cameras/{camera_id}", body)

    def camera_delete(self, camera_id):
        return self.delete(f"/api/cameras/{camera_id}")

    # ------------------------------------------------------------------ 地圖

    def map_points(self):
        return self.get("/api/map/points")

    def map_point_create(self, body):
        return self.post("/api/map/points", body)

    def map_point_update(self, point_id, body):
        return self.put(f"/api/map/points/{point_id}", body)

    def map_point_delete(self, point_id):
        return self.delete(f"/api/map/points/{point_id}")

    def routes(self, **q):
        return self.get("/api/map/routes", **q)

    def route(self, route_id):
        return self.get(f"/api/map/routes/{route_id}")

    def route_create(self, body):
        return self.post("/api/map/routes", body)

    def route_update(self, route_id, body):
        return self.put(f"/api/map/routes/{route_id}", body)

    def route_publish(self, route_id):
        return self.post(f"/api/map/routes/{route_id}/publish")

    def route_archive(self, route_id):
        return self.post(f"/api/map/routes/{route_id}/archive")

    def route_delete(self, route_id):
        return self.delete(f"/api/map/routes/{route_id}")

    def route_revisions(self, route_id):
        return self.get(f"/api/map/routes/{route_id}/revisions")

    def all_revisions(self, limit=200):
        return self.get("/api/map/revisions", limit=limit)

    def route_revision(self, route_id, version):
        return self.get(f"/api/map/routes/{route_id}/revisions/{version}")

    # ------------------------------------------------------------------ 工單

    def work_orders(self, **q):
        return self.get("/api/workorders", **q)

    def work_order(self, order_id):
        return self.get(f"/api/workorders/{order_id}")

    def work_order_create(self, body):
        return self.post("/api/workorders", body)

    def work_order_update(self, order_id, body):
        return self.put(f"/api/workorders/{order_id}", body)

    def work_order_schedule(self, order_id, drone_id, route_id, scheduled_at=None):
        return self.post(f"/api/workorders/{order_id}/schedule",
                         {"droneId": drone_id, "routeId": route_id, "scheduledAt": scheduled_at})

    def work_order_start(self, order_id):
        return self.post(f"/api/workorders/{order_id}/start")

    def work_order_cancel(self, order_id, reason):
        return self.post(f"/api/workorders/{order_id}/cancel", {"reason": reason})

    def work_order_complete(self, order_id):
        return self.post(f"/api/workorders/{order_id}/complete")

    def templates(self):
        return self.get("/api/workorders/templates")

    def template_create(self, body):
        return self.post("/api/workorders/templates", body)

    def template_update(self, template_id, body):
        return self.put(f"/api/workorders/templates/{template_id}", body)

    def template_delete(self, template_id):
        return self.delete(f"/api/workorders/templates/{template_id}")

    # ------------------------------------------------------------------ 統計

    def stats_overview(self):
        return self.get("/api/statistics/overview")

    def stats(self, kind: str, **q):
        """kind: mission-count / work-orders / work-order-duration / charging"""
        return self.get(f"/api/statistics/{kind}", **q)

    # ------------------------------------------------------------------ 記錄

    def mission_logs(self, **q):
        return self.get("/api/logs/missions", **q)

    def login_logs(self, **q):
        return self.get("/api/logs/logins", **q)

    def notifications(self, **q):
        return self.get("/api/notifications", **q)

    def unread_count(self) -> int:
        return self.get("/api/notifications/unread-count")["count"]

    def notification_read(self, notification_id):
        return self.post(f"/api/notifications/{notification_id}/read")

    def notification_read_all(self):
        return self.post("/api/notifications/read-all")

    # ------------------------------------------------------------------ 系統

    def users(self, **q):
        return self.get("/api/users", **q)

    def user_create(self, body):
        return self.post("/api/users", body)

    def user_update(self, user_id, body):
        return self.put(f"/api/users/{user_id}", body)

    def user_reset_password(self, user_id, password):
        return self.post(f"/api/users/{user_id}/reset-password", {"newPassword": password})

    def user_toggle_active(self, user_id):
        return self.post(f"/api/users/{user_id}/toggle-active")

    def user_delete(self, user_id):
        return self.delete(f"/api/users/{user_id}")

    def roles(self):
        return self.get("/api/roles")

    def permissions(self):
        return self.get("/api/roles/permissions")

    def role_menus(self):
        return self.get("/api/roles/menus")

    def role_create(self, body):
        return self.post("/api/roles", body)

    def role_update(self, role_id, body):
        return self.put(f"/api/roles/{role_id}", body)

    def role_delete(self, role_id):
        return self.delete(f"/api/roles/{role_id}")


api = ApiClient(settings.server_url)
