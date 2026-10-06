"""
用戶端設定。讀取執行檔 (或專案根目錄) 旁的 client.ini,不存在時使用預設值。

[server]
url = http://localhost:5080

[map]
online = true
tile_url = https://tile.openstreetmap.org/{z}/{x}/{y}.png
center_lat = 25.0559
center_lng = 121.6156
"""
from __future__ import annotations

import configparser
import os
import sys
from dataclasses import dataclass
from pathlib import Path


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    """使用者資料 (圖磚快取、記住的帳號)。"""
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    path = base / "DroneOps"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class ClientSettings:
    server_url: str = "http://localhost:5080"
    request_timeout: float = 15.0
    map_online: bool = True
    tile_url: str = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    center_lat: float = 25.0559
    center_lng: float = 121.6156
    source: str = "defaults"

    @property
    def ws_url(self) -> str:
        base = self.server_url.rstrip("/")
        if base.startswith("https://"):
            return "wss://" + base[len("https://"):] + "/ws/telemetry"
        return "ws://" + base.removeprefix("http://") + "/ws/telemetry"


def load_settings() -> ClientSettings:
    s = ClientSettings()
    ini = app_dir() / "client.ini"
    if ini.exists():
        p = configparser.ConfigParser()
        p.read(ini, encoding="utf-8")
        s.server_url = p.get("server", "url", fallback=s.server_url).strip().rstrip("/")
        s.request_timeout = p.getfloat("server", "timeout", fallback=s.request_timeout)
        s.map_online = p.getboolean("map", "online", fallback=s.map_online)
        s.tile_url = p.get("map", "tile_url", fallback=s.tile_url).strip()
        s.center_lat = p.getfloat("map", "center_lat", fallback=s.center_lat)
        s.center_lng = p.getfloat("map", "center_lng", fallback=s.center_lng)
        s.source = str(ini)
    s.server_url = os.environ.get("DRONE_SERVER_URL", s.server_url).rstrip("/")
    return s


settings = load_settings()
