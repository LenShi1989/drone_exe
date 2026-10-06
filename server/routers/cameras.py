from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import permissions as P
from .. import schemas as s
from ..db import get_db, utcnow
from ..deps import CurrentUser, bad_request, not_found, require
from ..enums import CameraProtocol
from ..models import Camera, Drone
from ..services import camera_dto

router = APIRouter(prefix="/api/cameras", tags=["Cameras"])


def _validate_url(protocol: int, url: str) -> None:
    """協定與網址前綴需一致,避免存進去卻播不出來。"""
    u = (url or "").strip().lower()
    if not u:
        raise bad_request("串流網址不可為空")
    if protocol == CameraProtocol.Http and not u.startswith(("http://", "https://")):
        raise bad_request("HTTP 攝影機的網址需以 http:// 或 https:// 開頭")
    if protocol == CameraProtocol.Rtsp and not u.startswith("rtsp://"):
        raise bad_request("RTSP 攝影機的網址需以 rtsp:// 開頭")


@router.get("", response_model=list[s.CameraDto])
def list_cameras(drone_id: int | None = Query(None, alias="droneId"), is_active: bool | None = Query(None, alias="isActive"),
                 db: Session = Depends(get_db), _: CurrentUser = Depends(require(P.CAMERA_VIEW))):
    q = select(Camera)
    if drone_id is not None:
        q = q.where(Camera.drone_id == drone_id)
    if is_active is not None:
        q = q.where(Camera.is_active.is_(is_active))
    rows = db.scalars(q.order_by(Camera.drone_id, Camera.sort_order, Camera.id)).all()
    return [camera_dto(c) for c in rows]


@router.get("/{camera_id}", response_model=s.CameraDto)
def get_camera(camera_id: int, db: Session = Depends(get_db), _: CurrentUser = Depends(require(P.CAMERA_VIEW))):
    camera = db.get(Camera, camera_id)
    if camera is None:
        raise not_found("攝影機不存在")
    return camera_dto(camera)


@router.post("", response_model=s.CameraDto, status_code=201)
def create_camera(body: s.CameraUpsertRequest, db: Session = Depends(get_db),
                  _: CurrentUser = Depends(require(P.CAMERA_MANAGE))):
    _validate_url(body.protocol, body.stream_url)
    if db.get(Drone, body.drone_id) is None:
        raise bad_request("所屬無人機不存在")
    sort_order = body.sort_order
    if sort_order <= 0:  # 未指定排序時,接續該無人機現有攝影機的最大值
        sort_order = (db.scalar(select(func.max(Camera.sort_order)).where(Camera.drone_id == body.drone_id)) or 0) + 1
    camera = Camera(drone_id=body.drone_id, name=body.name.strip(), protocol=body.protocol,
                    stream_url=body.stream_url.strip(), description=(body.description or "").strip() or None,
                    sort_order=sort_order, is_active=body.is_active)
    db.add(camera)
    db.commit()
    db.refresh(camera)
    return camera_dto(camera)


@router.put("/{camera_id}", response_model=s.CameraDto)
def update_camera(camera_id: int, body: s.CameraUpsertRequest, db: Session = Depends(get_db),
                  _: CurrentUser = Depends(require(P.CAMERA_MANAGE))):
    _validate_url(body.protocol, body.stream_url)
    camera = db.get(Camera, camera_id)
    if camera is None:
        raise not_found("攝影機不存在")
    if body.drone_id != camera.drone_id:
        if db.get(Drone, body.drone_id) is None:
            raise bad_request("所屬無人機不存在")
        camera.drone_id = body.drone_id
    camera.name = body.name.strip()
    camera.protocol = body.protocol
    camera.stream_url = body.stream_url.strip()
    camera.description = (body.description or "").strip() or None
    if body.sort_order > 0:
        camera.sort_order = body.sort_order
    camera.is_active = body.is_active
    camera.updated_at = utcnow()
    db.commit()
    db.refresh(camera)
    return camera_dto(camera)


@router.delete("/{camera_id}", status_code=204)
def delete_camera(camera_id: int, db: Session = Depends(get_db), _: CurrentUser = Depends(require(P.CAMERA_MANAGE))):
    camera = db.get(Camera, camera_id)
    if camera is None:
        raise not_found("攝影機不存在")
    db.delete(camera)
    db.commit()
    return Response(status_code=204)
