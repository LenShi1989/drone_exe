"""
伺服器設定。

讀取順序 (後者覆蓋前者):
  1. 程式內預設值
  2. 執行檔 (或專案根目錄) 旁的 server.ini
  3. 環境變數,格式 DRONE_<區段>__<鍵>,例:DRONE_DATABASE__PASSWORD
"""
from __future__ import annotations

import configparser
import os
import sys
from dataclasses import dataclass, field, fields
from pathlib import Path


def app_dir() -> Path:
    """打包成 exe 時取執行檔所在資料夾,開發時取專案根目錄。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


@dataclass
class DatabaseSettings:
    host: str = "localhost"
    port: int = 5432
    name: str = "drone_system"
    user: str = "drone"
    password: str = "drone_pass"
    pool_size: int = 10

    @property
    def url(self) -> str:
        from urllib.parse import quote_plus
        return (f"postgresql+psycopg2://{quote_plus(self.user)}:{quote_plus(self.password)}"
                f"@{self.host}:{self.port}/{self.name}")


@dataclass
class ServerSettings:
    host: str = "0.0.0.0"
    port: int = 5080
    log_level: str = "info"


@dataclass
class JwtSettings:
    issuer: str = "drone-system"
    audience: str = "drone-system-client"
    secret_key: str = "CHANGE_ME_dev_only_secret_key_at_least_32_chars_long"
    access_token_minutes: int = 120
    refresh_token_days: int = 7


@dataclass
class SimulatorSettings:
    enabled: bool = True
    tick_seconds: float = 1.0
    persist_telemetry_seconds: int = 10
    persist_drone_seconds: int = 5
    auto_dispatch: bool = True
    dispatch_interval_seconds: int = 15
    cruise_speed_mps: float = 9.0
    return_battery_percent: float = 25.0
    charge_rate_percent_per_second: float = 0.2
    sync_interval_seconds: int = 30
    patrol_resume_battery_percent: float = 80.0


@dataclass
class Settings:
    database: DatabaseSettings = field(default_factory=DatabaseSettings)
    server: ServerSettings = field(default_factory=ServerSettings)
    jwt: JwtSettings = field(default_factory=JwtSettings)
    simulator: SimulatorSettings = field(default_factory=SimulatorSettings)
    source: str = "defaults"


def _coerce(value: str, target_type):
    if target_type is bool or target_type == "bool":
        return value.strip().lower() in ("1", "true", "yes", "on")
    if target_type is int or target_type == "int":
        return int(value)
    if target_type is float or target_type == "float":
        return float(value)
    return value


def _apply(section_obj, values: dict[str, str]) -> None:
    for f in fields(section_obj):
        if f.name in values:
            setattr(section_obj, f.name, _coerce(values[f.name], f.type))


def load_settings(path: Path | None = None) -> Settings:
    settings = Settings()
    ini = path or app_dir() / "server.ini"

    if ini.exists():
        parser = configparser.ConfigParser()
        parser.read(ini, encoding="utf-8")
        for name in ("database", "server", "jwt", "simulator"):
            if parser.has_section(name):
                _apply(getattr(settings, name), dict(parser.items(name)))
        settings.source = str(ini)

    for name in ("database", "server", "jwt", "simulator"):
        prefix = f"DRONE_{name.upper()}__"
        env_values = {k[len(prefix):].lower(): v for k, v in os.environ.items() if k.upper().startswith(prefix)}
        if env_values:
            _apply(getattr(settings, name), env_values)

    if len(settings.jwt.secret_key) < 32:
        raise RuntimeError("jwt.secret_key 長度不足 32 字元,請於 server.ini 或環境變數 DRONE_JWT__SECRET_KEY 設定。")
    return settings


settings = load_settings()
