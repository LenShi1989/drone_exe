from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from .. import permissions as P
from .. import schemas as s
from ..db import as_utc, get_db
from ..deps import CurrentUser, get_current_user, not_found, require
from ..models import Drone, LoginLog, MissionLog, Notification, WorkOrder
from ..services import mission_log_dto, notification_dto

router = APIRouter(prefix="/api", tags=["Logs"])


def _page(page: int, page_size: int) -> tuple[int, int]:
    return max(1, page), page_size if 1 <= page_size <= 200 else 20


@router.get("/logs/missions", response_model=s.Paged[s.MissionLogDto])
def missions(
    drone_id: int | None = Query(None, alias="droneId"), work_order_id: int | None = Query(None, alias="workOrderId"),
    event_type: int | None = Query(None, alias="eventType"),
    from_: datetime | None = Query(None, alias="from"), to: datetime | None = None,
    page: int = 1, page_size: int = Query(20, alias="pageSize"),
    db: Session = Depends(get_db), _: CurrentUser = Depends(require(P.LOG_MISSION)),
):
    """任務紀錄。"""
    page, page_size = _page(page, page_size)
    conds = []
    if drone_id is not None:
        conds.append(MissionLog.drone_id == drone_id)
    if work_order_id is not None:
        conds.append(MissionLog.work_order_id == work_order_id)
    if event_type is not None:
        conds.append(MissionLog.event_type == event_type)
    if from_ is not None:
        conds.append(MissionLog.occurred_at >= as_utc(from_))
    if to is not None:
        conds.append(MissionLog.occurred_at <= as_utc(to))

    total = db.scalar(select(func.count()).select_from(MissionLog).where(*conds))
    rows = db.execute(
        select(MissionLog, WorkOrder.order_no, Drone.name)
        .outerjoin(WorkOrder, WorkOrder.id == MissionLog.work_order_id)
        .outerjoin(Drone, Drone.id == MissionLog.drone_id)
        .where(*conds).order_by(MissionLog.occurred_at.desc())
        .offset((page - 1) * page_size).limit(page_size)).all()
    return s.Paged[s.MissionLogDto](items=[mission_log_dto(log, no, name) for log, no, name in rows],
                                    total=total, page=page, page_size=page_size)


@router.get("/logs/logins", response_model=s.Paged[s.LoginLogDto])
def logins(
    username: str | None = None, is_success: bool | None = Query(None, alias="isSuccess"),
    from_: datetime | None = Query(None, alias="from"), to: datetime | None = None,
    page: int = 1, page_size: int = Query(20, alias="pageSize"),
    db: Session = Depends(get_db), _: CurrentUser = Depends(require(P.LOG_LOGIN)),
):
    """登入紀錄 (使用者帳號紀錄)。"""
    page, page_size = _page(page, page_size)
    conds = []
    if username and username.strip():
        conds.append(LoginLog.username.ilike(f"%{username.strip()}%"))
    if is_success is not None:
        conds.append(LoginLog.is_success.is_(is_success))
    if from_ is not None:
        conds.append(LoginLog.logged_at >= as_utc(from_))
    if to is not None:
        conds.append(LoginLog.logged_at <= as_utc(to))

    total = db.scalar(select(func.count()).select_from(LoginLog).where(*conds))
    rows = db.scalars(select(LoginLog).where(*conds).order_by(LoginLog.logged_at.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    items = [s.LoginLogDto(id=r.id, user_id=r.user_id, username=r.username, ip_address=r.ip_address,
                           user_agent=r.user_agent, is_success=r.is_success, fail_reason=r.fail_reason,
                           logged_at=r.logged_at) for r in rows]
    return s.Paged[s.LoginLogDto](items=items, total=total, page=page, page_size=page_size)


def _visible(user_id: int):
    return or_(Notification.user_id.is_(None), Notification.user_id == user_id)


@router.get("/notifications", response_model=s.Paged[s.NotificationDto], tags=["Notifications"])
def notifications(
    is_read: bool | None = Query(None, alias="isRead"), category: str | None = None,
    page: int = 1, page_size: int = Query(20, alias="pageSize"),
    db: Session = Depends(get_db), user: CurrentUser = Depends(require(P.LOG_NOTIFICATION)),
):
    page, page_size = _page(page, page_size)
    conds = [_visible(user.id)]
    if is_read is not None:
        conds.append(Notification.is_read.is_(is_read))
    if category and category.strip():
        conds.append(Notification.category == category.strip())
    total = db.scalar(select(func.count()).select_from(Notification).where(*conds))
    rows = db.scalars(select(Notification).where(*conds).order_by(Notification.created_at.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return s.Paged[s.NotificationDto](items=[notification_dto(n) for n in rows], total=total, page=page,
                                      page_size=page_size)


@router.get("/notifications/unread-count", tags=["Notifications"])
def unread_count(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    count = db.scalar(select(func.count()).select_from(Notification)
                      .where(Notification.is_read.is_(False), _visible(user.id)))
    return {"count": count}


@router.post("/notifications/read-all", status_code=204, tags=["Notifications"])
def mark_all_read(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    db.execute(update(Notification).where(Notification.is_read.is_(False), _visible(user.id)).values(is_read=True))
    db.commit()
    return Response(status_code=204)


@router.post("/notifications/{notification_id}/read", status_code=204, tags=["Notifications"])
def mark_read(notification_id: int, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    n = db.scalar(select(Notification).where(Notification.id == notification_id, _visible(user.id)))
    if n is None:
        raise not_found("通知不存在")
    n.is_read = True
    db.commit()
    return Response(status_code=204)
