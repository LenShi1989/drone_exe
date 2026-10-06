from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import permissions as P
from .. import schemas as s
from ..db import as_utc, get_db, utcnow
from ..deps import CurrentUser, bad_request, not_found, require
from ..enums import (
    CURRENT_STATUSES, TERMINAL_STATUSES, MissionEventType, NotificationLevel, RouteStatus, WorkOrderPriority,
    WorkOrderStatus, text_of,
)
from ..models import Drone, FlightRoute, MissionLog, WorkOrder, WorkOrderTemplate
from ..services import mission_log_dto, push_notification, template_dto, user_names, waypoint_dtos, work_order_dto

router = APIRouter(prefix="/api/workorders", tags=["WorkOrders"])


# ---------------------------------------------------------------- 模板

@router.get("/templates", response_model=list[s.WorkOrderTemplateDto])
def get_templates(db: Session = Depends(get_db), _: CurrentUser = Depends(require(P.WORKORDER_VIEW))):
    return [template_dto(t) for t in db.scalars(select(WorkOrderTemplate).order_by(WorkOrderTemplate.id)).unique()]


def _fill_template(t: WorkOrderTemplate, body: s.WorkOrderTemplateUpsertRequest) -> None:
    t.name = body.name
    t.description = body.description
    t.default_route_id = body.default_route_id
    t.default_priority = body.default_priority
    t.estimated_minutes = body.estimated_minutes
    t.checklist_json = [c.strip() for c in body.checklist if c and c.strip()]
    t.is_active = body.is_active


@router.post("/templates", response_model=s.WorkOrderTemplateDto)
def create_template(body: s.WorkOrderTemplateUpsertRequest, db: Session = Depends(get_db),
                    _: CurrentUser = Depends(require(P.WORKORDER_TEMPLATE))):
    t = WorkOrderTemplate()
    _fill_template(t, body)
    db.add(t)
    db.commit()
    db.refresh(t)
    return template_dto(t)


@router.put("/templates/{template_id}", response_model=s.WorkOrderTemplateDto)
def update_template(template_id: int, body: s.WorkOrderTemplateUpsertRequest, db: Session = Depends(get_db),
                    _: CurrentUser = Depends(require(P.WORKORDER_TEMPLATE))):
    t = db.get(WorkOrderTemplate, template_id)
    if t is None:
        raise not_found("模板不存在")
    _fill_template(t, body)
    db.commit()
    db.refresh(t)
    return template_dto(t)


@router.delete("/templates/{template_id}", status_code=204)
def delete_template(template_id: int, db: Session = Depends(get_db),
                    _: CurrentUser = Depends(require(P.WORKORDER_TEMPLATE))):
    t = db.get(WorkOrderTemplate, template_id)
    if t is None:
        raise not_found("模板不存在")
    db.delete(t)
    db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------- 工單

@router.get("", response_model=s.Paged[s.WorkOrderDto])
def list_work_orders(
    status: int | None = None, scope: str | None = None, keyword: str | None = None,
    drone_id: int | None = Query(None, alias="droneId"),
    from_: datetime | None = Query(None, alias="from"), to: datetime | None = None,
    page: int = 1, page_size: int = Query(20, alias="pageSize"),
    db: Session = Depends(get_db), _: CurrentUser = Depends(require(P.WORKORDER_VIEW)),
):
    page, page_size = max(1, page), page_size if 1 <= page_size <= 200 else 20
    q = select(WorkOrder)
    if status is not None:
        q = q.where(WorkOrder.status == status)
    if drone_id is not None:
        q = q.where(WorkOrder.drone_id == drone_id)
    if from_ is not None:
        q = q.where(WorkOrder.created_at >= as_utc(from_))
    if to is not None:
        q = q.where(WorkOrder.created_at <= as_utc(to))
    if (scope or "").lower() == "current":
        q = q.where(WorkOrder.status.in_([int(x) for x in CURRENT_STATUSES]))
    elif (scope or "").lower() == "history":
        q = q.where(WorkOrder.status.in_([int(x) for x in TERMINAL_STATUSES]))
    if keyword and keyword.strip():
        kw = f"%{keyword.strip()}%"
        q = q.where(or_(WorkOrder.order_no.ilike(kw), WorkOrder.title.ilike(kw)))

    total = db.scalar(select(func.count()).select_from(q.with_only_columns(WorkOrder.id).subquery()))
    rows = db.scalars(q.order_by(WorkOrder.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).unique().all()
    names = user_names(db, (w.created_by for w in rows))
    return s.Paged[s.WorkOrderDto](items=[work_order_dto(w, names.get(w.created_by)) for w in rows],
                                   total=total, page=page, page_size=page_size)


@router.get("/{order_id}", response_model=s.WorkOrderDetailDto)
def get_work_order(order_id: int, db: Session = Depends(get_db), _: CurrentUser = Depends(require(P.WORKORDER_VIEW))):
    order = db.get(WorkOrder, order_id)
    if order is None:
        raise not_found("工單不存在")
    logs = db.scalars(select(MissionLog).where(MissionLog.work_order_id == order_id)
                      .order_by(MissionLog.occurred_at)).all()
    basic = work_order_dto(order, user_names(db, [order.created_by]).get(order.created_by))
    return s.WorkOrderDetailDto(**basic.model_dump(), waypoints=waypoint_dtos(order.route),
                                mission_logs=[mission_log_dto(log) for log in logs])


def _next_order_no(db: Session) -> str:
    prefix = f"WO-{utcnow():%Y%m%d}-"
    existing = db.scalars(select(WorkOrder.order_no).where(WorkOrder.order_no.like(f"{prefix}%"))).all()
    numbers = [int(x[len(prefix):]) for x in existing if x[len(prefix):].isdigit()]
    return f"{prefix}{max(numbers, default=0) + 1:04d}"


@router.post("", response_model=s.WorkOrderDto)
def create_work_order(body: s.WorkOrderUpsertRequest, db: Session = Depends(get_db),
                      user: CurrentUser = Depends(require(P.WORKORDER_MANAGE))):
    order = WorkOrder(
        order_no=_next_order_no(db), title=body.title, description=body.description, template_id=body.template_id,
        route_id=body.route_id, drone_id=body.drone_id, priority=body.priority, scheduled_at=body.scheduled_at,
        assignee_user_id=body.assignee_user_id, remark=body.remark, created_by=user.id,
        status=int(WorkOrderStatus.Pending))

    # 套用模板預設值 (未指定時)
    if body.template_id is not None:
        tpl = db.get(WorkOrderTemplate, body.template_id)
        if tpl is not None:
            if order.route_id is None:
                order.route_id = tpl.default_route_id
            if body.priority == WorkOrderPriority.Normal:
                order.priority = tpl.default_priority
            if order.description is None:
                order.description = tpl.description

    db.add(order)
    db.commit()
    db.refresh(order)
    return work_order_dto(order, user.display_name)


@router.put("/{order_id}", response_model=s.WorkOrderDto)
def update_work_order(order_id: int, body: s.WorkOrderUpsertRequest, db: Session = Depends(get_db),
                      _: CurrentUser = Depends(require(P.WORKORDER_MANAGE))):
    order = db.get(WorkOrder, order_id)
    if order is None:
        raise not_found("工單不存在")
    if order.is_terminal:
        raise bad_request("已結案的工單不可修改")
    order.title = body.title
    order.description = body.description
    order.template_id = body.template_id
    order.route_id = body.route_id
    order.drone_id = body.drone_id
    order.priority = body.priority
    order.scheduled_at = body.scheduled_at
    order.assignee_user_id = body.assignee_user_id
    order.remark = body.remark
    order.updated_at = utcnow()
    db.commit()
    db.refresh(order)
    return work_order_dto(order)


@router.post("/{order_id}/schedule", status_code=204)
def schedule(order_id: int, body: s.WorkOrderScheduleRequest, db: Session = Depends(get_db),
             _: CurrentUser = Depends(require(P.WORKORDER_MANAGE))):
    """排程:指定無人機 + 航線,狀態轉為 Scheduled,模擬器會自動接手起飛。"""
    order = db.get(WorkOrder, order_id)
    if order is None:
        raise not_found("工單不存在")
    if order.status not in (WorkOrderStatus.Pending, WorkOrderStatus.Scheduled):
        raise bad_request(f"目前狀態「{text_of(WorkOrderStatus, order.status)}」不可排程")

    drone = db.scalar(select(Drone).where(Drone.id == body.drone_id, Drone.is_active.is_(True)))
    if drone is None:
        raise bad_request("無人機不存在或已停用")
    route = db.get(FlightRoute, body.route_id)
    if route is None:
        raise bad_request("航線不存在")
    if route.status != RouteStatus.Published:
        raise bad_request("只能指派已發布的航線")
    if len(route.waypoints) < 2:
        raise bad_request("航線航點不足")

    # 電量需覆蓋預估耗電 × 1.3 的安全係數
    required = float(route.estimated_energy_wh) * 1.3 / float(drone.battery_capacity_wh) * 100
    if float(drone.battery_percent) < required:
        raise bad_request(f"{drone.name} 電量 {drone.battery_percent:.1f}% 不足,此航線需要約 {required:.0f}%")

    now = utcnow()
    order.drone_id = drone.id
    order.route_id = route.id
    order.scheduled_at = body.scheduled_at or now
    order.status = int(WorkOrderStatus.Scheduled)
    order.updated_at = now
    db.add(MissionLog(work_order_id=order.id, drone_id=drone.id, event_type=int(MissionEventType.Info),
                      message=f"{order.order_no} 已排程給 {drone.name},航線「{route.name}」"))
    db.commit()
    return Response(status_code=204)


@router.post("/{order_id}/start", status_code=204)
def start(order_id: int, db: Session = Depends(get_db), _: CurrentUser = Depends(require(P.WORKORDER_MANAGE))):
    """立即起飛。實際飛行推進由模擬器負責。"""
    order = db.get(WorkOrder, order_id)
    if order is None:
        raise not_found("工單不存在")
    if order.status != WorkOrderStatus.Scheduled:
        raise bad_request("只有已排程的工單可以起飛")
    order.scheduled_at = utcnow()
    order.updated_at = utcnow()
    db.commit()
    return Response(status_code=204)


@router.post("/{order_id}/cancel", status_code=204)
def cancel(order_id: int, body: s.WorkOrderCancelRequest | None = None, db: Session = Depends(get_db),
           _: CurrentUser = Depends(require(P.WORKORDER_MANAGE))):
    order = db.get(WorkOrder, order_id)
    if order is None:
        raise not_found("工單不存在")
    if order.is_terminal:
        raise bad_request("工單已結案")
    now = utcnow()
    order.status = int(WorkOrderStatus.Cancelled)
    order.completed_at = now
    order.remark = (body.reason if body and body.reason else None) or "人工取消"
    order.updated_at = now
    db.add(MissionLog(work_order_id=order.id, drone_id=order.drone_id, event_type=int(MissionEventType.Warning),
                      message=f"{order.order_no} 已取消:{order.remark}"))
    db.commit()
    push_notification(db, NotificationLevel.Warning, "workorder", f"{order.order_no} 已取消", order.remark,
                      "/workorder/history")
    return Response(status_code=204)


@router.post("/{order_id}/complete", status_code=204)
def complete(order_id: int, db: Session = Depends(get_db), _: CurrentUser = Depends(require(P.WORKORDER_MANAGE))):
    order = db.get(WorkOrder, order_id)
    if order is None:
        raise not_found("工單不存在")
    if order.is_terminal:
        raise bad_request("工單已結案")
    now = utcnow()
    order.status = int(WorkOrderStatus.Completed)
    order.completed_at = now
    order.started_at = order.started_at or order.scheduled_at or order.created_at
    if order.duration_seconds is None:
        order.duration_seconds = max(0, int((now - order.started_at).total_seconds()))
    order.progress_percent = 100
    order.updated_at = now
    db.add(MissionLog(work_order_id=order.id, drone_id=order.drone_id, event_type=int(MissionEventType.Landing),
                      message=f"{order.order_no} 人工結案"))
    db.commit()
    return Response(status_code=204)
