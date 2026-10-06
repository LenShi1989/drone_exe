"""FastAPI 應用程式:資料庫初始化、種子資料、模擬器、即時推播。"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import jwt
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .config import settings
from .db import SessionLocal, engine, utcnow
from .deps import principal_from_token
from .models import Base
from .realtime import hub
from .routers import auth, cameras, drones, logs, map, statistics, system, workorders
from .seeder import seed
from .simulator import simulator

log = logging.getLogger("drone.app")


def init_database() -> None:
    """建立缺少的資料表 (既有表不動) 並寫入種子資料。"""
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        await asyncio.to_thread(init_database)
    except Exception:
        log.exception("資料庫初始化失敗。請確認 PostgreSQL 已啟動,且 server.ini 的 [database] 設定正確")
        raise
    hub.bind_loop(asyncio.get_running_loop())
    simulator.start()
    log.info("Drone System API 已啟動 (設定來源:%s)", settings.source)
    yield
    simulator.stop()


app = FastAPI(
    title="無人機操作系統 API",
    version=__version__,
    description="地面控制與任務管理平台。認證方式:Bearer JWT。即時推播:WebSocket /ws/telemetry。",
    lifespan=lifespan,
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ---------------------------------------------------------------- 統一錯誤格式 {"message": ...}

@app.exception_handler(StarletteHTTPException)
async def http_error(_: Request, exc: StarletteHTTPException):
    message = exc.detail if isinstance(exc.detail, str) else "請求失敗"
    return JSONResponse({"message": message}, status_code=exc.status_code, headers=getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    errors: dict[str, list[str]] = {}
    for e in exc.errors():
        field = ".".join(str(x) for x in e.get("loc", [])[1:]) or "body"
        errors.setdefault(field, []).append(e.get("msg", "格式錯誤"))
    first = next(iter(errors.items()), ("", ["格式錯誤"]))
    return JSONResponse({"message": f"欄位驗證失敗:{first[0]} {first[1][0]}".strip(), "errors": errors},
                        status_code=400)


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    log.exception("未處理的例外 %s %s", request.method, request.url.path)
    return JSONResponse({"message": "伺服器發生錯誤,請稍後再試"}, status_code=500)


# ---------------------------------------------------------------- 路由

for r in (auth, drones, cameras, map, workorders, statistics, logs, system):
    app.include_router(r.router)


@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok", "utc": utcnow(), "version": __version__, "simulator": simulator.enabled,
            "wsClients": hub.client_count}


@app.websocket("/ws/telemetry")
async def telemetry_ws(ws: WebSocket):
    """即時推播。JWT 以 query string access_token 傳遞。"""
    token = ws.query_params.get("access_token", "")
    try:
        principal_from_token(token)
    except (jwt.InvalidTokenError, KeyError, ValueError):
        await ws.close(code=4401)
        return
    await hub.connect(ws)
    try:
        while True:
            await ws.receive_text()  # 客戶端訊息 (ping) 僅用於維持連線
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(ws)
