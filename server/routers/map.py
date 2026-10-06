from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import permissions as P
from .. import schemas as s
from ..db import get_db, utcnow
from ..deps import CurrentUser, bad_request, not_found, require
from ..enums import TERMINAL_STATUSES, RouteStatus
from ..geo import recalculate_route, route_geojson
from ..models import FlightRoute, MapPoint, RouteRevision, RouteWaypoint, WorkOrder
from ..services import map_point_dto, route_dto, user_names

router = APIRouter(prefix="/api/map", tags=["Map"])


# ---------------------------------------------------------------- 點位

@router.get("/points", response_model=list[s.MapPointDto])
def get_points(db: Session = Depends(get_db), _: CurrentUser = Depends(require(P.MAP_VIEW))):
    return [map_point_dto(p) for p in db.scalars(select(MapPoint).order_by(MapPoint.id))]


@router.post("/points", response_model=s.MapPointDto)
def create_point(body: s.MapPointUpsertRequest, db: Session = Depends(get_db),
                 user: CurrentUser = Depends(require(P.MAP_EDIT))):
    point = MapPoint(name=body.name, point_type=body.point_type, latitude=body.latitude, longitude=body.longitude,
                     altitude_m=body.altitude_m, description=body.description, created_by=user.id)
    db.add(point)
    db.commit()
    return map_point_dto(point)


@router.put("/points/{point_id}", response_model=s.MapPointDto)
def update_point(point_id: int, body: s.MapPointUpsertRequest, db: Session = Depends(get_db),
                 _: CurrentUser = Depends(require(P.MAP_EDIT))):
    point = db.get(MapPoint, point_id)
    if point is None:
        raise not_found("點位不存在")
    point.name = body.name
    point.point_type = body.point_type
    point.latitude = body.latitude
    point.longitude = body.longitude
    point.altitude_m = body.altitude_m
    point.description = body.description
    db.commit()
    return map_point_dto(point)


@router.delete("/points/{point_id}", status_code=204)
def delete_point(point_id: int, db: Session = Depends(get_db), _: CurrentUser = Depends(require(P.MAP_EDIT))):
    point = db.get(MapPoint, point_id)
    if point is None:
        raise not_found("點位不存在")
    db.delete(point)
    db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------- 航線

@router.get("/routes", response_model=list[s.RouteDto])
def get_routes(status: int | None = None, keyword: str | None = None, db: Session = Depends(get_db),
               _: CurrentUser = Depends(require(P.MAP_VIEW))):
    q = select(FlightRoute)
    if status is not None:
        q = q.where(FlightRoute.status == status)
    if keyword and keyword.strip():
        q = q.where(FlightRoute.name.ilike(f"%{keyword.strip()}%"))
    return [route_dto(r, include_waypoints=False) for r in db.scalars(q.order_by(FlightRoute.updated_at.desc()))]


@router.get("/routes/{route_id}", response_model=s.RouteDto)
def get_route(route_id: int, db: Session = Depends(get_db), _: CurrentUser = Depends(require(P.MAP_VIEW))):
    route = db.get(FlightRoute, route_id)
    if route is None:
        raise not_found("航線不存在")
    return route_dto(route, include_waypoints=True)


def _apply_waypoints(route: FlightRoute, inputs: list[s.RouteWaypointInput]) -> None:
    for seq, w in enumerate(sorted(inputs, key=lambda x: x.sequence), start=1):
        route.waypoints.append(RouteWaypoint(
            map_point_id=w.map_point_id, sequence=seq, latitude=w.latitude, longitude=w.longitude,
            altitude_m=w.altitude_m, action=w.action, hover_seconds=w.hover_seconds))


@router.post("/routes", response_model=s.RouteDto)
def create_route(body: s.RouteSaveRequest, db: Session = Depends(get_db),
                 user: CurrentUser = Depends(require(P.MAP_EDIT))):
    """儲存路線 (新建)。同時寫入 v1 版本快照。"""
    if len(body.waypoints) < 2:
        raise bad_request("航線至少需要 2 個航點")
    route = FlightRoute(name=body.name, description=body.description, status=int(RouteStatus.Draft), version=1,
                        created_by=user.id)
    _apply_waypoints(route, body.waypoints)
    recalculate_route(route)
    db.add(route)
    db.flush()
    db.add(RouteRevision(route_id=route.id, version=1, change_note=body.change_note or "初版建立",
                         created_by=user.id, snapshot_json=route_geojson(route)))
    db.commit()
    return route_dto(route, include_waypoints=True)


@router.put("/routes/{route_id}", response_model=s.RouteDto)
def update_route(route_id: int, body: s.RouteSaveRequest, db: Session = Depends(get_db),
                 user: CurrentUser = Depends(require(P.MAP_EDIT))):
    """儲存路線 (更新)。版本號 +1 並寫入新的歷史快照。"""
    if len(body.waypoints) < 2:
        raise bad_request("航線至少需要 2 個航點")
    route = db.get(FlightRoute, route_id)
    if route is None:
        raise not_found("航線不存在")
    if route.status == RouteStatus.Archived:
        raise bad_request("已封存的航線不可編輯")

    # 先刪舊航點並 flush,避免 (route_id, sequence) 唯一鍵與新航點衝突
    route.waypoints.clear()
    db.flush()

    route.name = body.name
    route.description = body.description
    route.version += 1
    route.updated_at = utcnow()
    _apply_waypoints(route, body.waypoints)
    recalculate_route(route)
    db.flush()
    db.add(RouteRevision(route_id=route.id, version=route.version,
                         change_note=body.change_note or f"v{route.version} 更新", created_by=user.id,
                         snapshot_json=route_geojson(route)))
    db.commit()
    return route_dto(route, include_waypoints=True)


def _change_status(db: Session, route_id: int, status: RouteStatus) -> Response:
    route = db.get(FlightRoute, route_id)
    if route is None:
        raise not_found("航線不存在")
    route.status = int(status)
    route.updated_at = utcnow()
    db.commit()
    return Response(status_code=204)


@router.post("/routes/{route_id}/publish", status_code=204)
def publish(route_id: int, db: Session = Depends(get_db), _: CurrentUser = Depends(require(P.MAP_EDIT))):
    return _change_status(db, route_id, RouteStatus.Published)


@router.post("/routes/{route_id}/archive", status_code=204)
def archive(route_id: int, db: Session = Depends(get_db), _: CurrentUser = Depends(require(P.MAP_EDIT))):
    return _change_status(db, route_id, RouteStatus.Archived)


@router.delete("/routes/{route_id}", status_code=204)
def delete_route(route_id: int, db: Session = Depends(get_db), _: CurrentUser = Depends(require(P.MAP_EDIT))):
    route = db.get(FlightRoute, route_id)
    if route is None:
        raise not_found("航線不存在")
    if db.scalar(select(WorkOrder.id).where(WorkOrder.route_id == route_id,
                                            WorkOrder.status.not_in([int(x) for x in TERMINAL_STATUSES]))):
        raise bad_request("仍有未結案工單引用此航線")
    db.delete(route)
    db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------- 歷史地圖

def _snapshot_dict(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}


def _revision_dto(r: RouteRevision, names: dict[int, str]) -> s.RouteRevisionDto:
    snap = _snapshot_dict(r.snapshot_json)
    waypoint_count = sum(1 for f in snap.get("features", [])
                         if isinstance(f, dict) and (f.get("properties") or {}).get("kind") == "waypoint")
    distance = float((snap.get("properties") or {}).get("totalDistanceM") or 0)
    return s.RouteRevisionDto(
        id=r.id, route_id=r.route_id, route_name=r.route.name if r.route else "", version=r.version,
        change_note=r.change_note, created_at=r.created_at, created_by_name=names.get(r.created_by),
        waypoint_count=waypoint_count, total_distance_m=distance)


@router.get("/routes/{route_id}/revisions", response_model=list[s.RouteRevisionDto])
def get_revisions(route_id: int, db: Session = Depends(get_db), _: CurrentUser = Depends(require(P.MAP_HISTORY))):
    revisions = db.scalars(select(RouteRevision).where(RouteRevision.route_id == route_id)
                           .order_by(RouteRevision.version.desc())).all()
    names = user_names(db, (r.created_by for r in revisions))
    return [_revision_dto(r, names) for r in revisions]


@router.get("/revisions", response_model=list[s.RouteRevisionDto])
def get_all_revisions(limit: int = 100, db: Session = Depends(get_db),
                      _: CurrentUser = Depends(require(P.MAP_HISTORY))):
    """所有航線的版本紀錄 (歷史地圖總覽)。"""
    revisions = db.scalars(select(RouteRevision).order_by(RouteRevision.created_at.desc())
                           .limit(min(500, max(1, limit)))).all()
    names = user_names(db, (r.created_by for r in revisions))
    return [_revision_dto(r, names) for r in revisions]


@router.get("/routes/{route_id}/revisions/{version}", response_model=s.RouteRevisionDetailDto)
def get_revision(route_id: int, version: int, db: Session = Depends(get_db),
                 _: CurrentUser = Depends(require(P.MAP_HISTORY))):
    revision = db.scalar(select(RouteRevision).where(RouteRevision.route_id == route_id,
                                                     RouteRevision.version == version))
    if revision is None:
        raise not_found("版本不存在")
    basic = _revision_dto(revision, user_names(db, [revision.created_by]))
    snapshot = revision.snapshot_json
    return s.RouteRevisionDetailDto(**basic.model_dump(),
                                    snapshot_json=snapshot if isinstance(snapshot, str)
                                    else json.dumps(snapshot, ensure_ascii=False))
