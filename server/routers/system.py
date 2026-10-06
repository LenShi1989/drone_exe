"""系統管理:帳號與角色。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from .. import permissions as P
from .. import schemas as s
from ..db import get_db, utcnow
from ..deps import CurrentUser, bad_request, conflict, not_found, require
from ..models import Permission, RefreshToken, Role, RolePermission, User
from ..security import hash_password
from ..services import build_menu

router = APIRouter(prefix="/api", tags=["System"])


# ============================================================ 帳號

def _user_dto(u: User) -> s.UserDto:
    return s.UserDto(
        id=u.id, username=u.username, email=u.email, display_name=u.display_name, role_id=u.role_id,
        role_name=u.role.name if u.role else "", role_code=u.role.code if u.role else "", is_active=u.is_active,
        last_login_at=u.last_login_at, is_locked=u.locked_until is not None and u.locked_until > utcnow(),
        created_at=u.created_at)


@router.get("/users", response_model=s.Paged[s.UserDto])
def list_users(keyword: str | None = None, role_id: int | None = Query(None, alias="roleId"),
               is_active: bool | None = Query(None, alias="isActive"), page: int = 1,
               page_size: int = Query(20, alias="pageSize"), db: Session = Depends(get_db),
               _: CurrentUser = Depends(require(P.SYSTEM_USER))):
    page, page_size = max(1, page), page_size if 1 <= page_size <= 200 else 20
    conds = []
    if role_id is not None:
        conds.append(User.role_id == role_id)
    if is_active is not None:
        conds.append(User.is_active.is_(is_active))
    if keyword and keyword.strip():
        kw = f"%{keyword.strip()}%"
        conds.append(or_(User.username.ilike(kw), User.display_name.ilike(kw), User.email.ilike(kw)))
    total = db.scalar(select(func.count()).select_from(User).where(*conds))
    rows = db.scalars(select(User).where(*conds).order_by(User.id)
                      .offset((page - 1) * page_size).limit(page_size)).unique().all()
    return s.Paged[s.UserDto](items=[_user_dto(u) for u in rows], total=total, page=page, page_size=page_size)


@router.get("/users/{user_id}", response_model=s.UserDto)
def get_user(user_id: int, db: Session = Depends(get_db), _: CurrentUser = Depends(require(P.SYSTEM_USER))):
    user = db.get(User, user_id)
    if user is None:
        raise not_found("帳號不存在")
    return _user_dto(user)


@router.post("/users", response_model=s.UserDto)
def create_user(body: s.UserCreateRequest, db: Session = Depends(get_db),
                _: CurrentUser = Depends(require(P.SYSTEM_USER))):
    if db.scalar(select(User.id).where(User.username == body.username)):
        raise conflict("帳號已存在")
    if db.scalar(select(User.id).where(User.email == body.email)):
        raise conflict("Email 已被使用")
    if db.get(Role, body.role_id) is None:
        raise bad_request("角色不存在")
    user = User(username=body.username, email=body.email, display_name=body.display_name,
                password_hash=hash_password(body.password), role_id=body.role_id, is_active=body.is_active)
    db.add(user)
    db.commit()
    db.refresh(user)
    return _user_dto(user)


@router.put("/users/{user_id}", response_model=s.UserDto)
def update_user(user_id: int, body: s.UserUpdateRequest, db: Session = Depends(get_db),
                current: CurrentUser = Depends(require(P.SYSTEM_USER))):
    user = db.get(User, user_id)
    if user is None:
        raise not_found("帳號不存在")
    if db.scalar(select(User.id).where(User.email == body.email, User.id != user_id)):
        raise conflict("Email 已被使用")
    if db.get(Role, body.role_id) is None:
        raise bad_request("角色不存在")
    # 避免把自己降權後失去管理入口
    if user_id == current.id and user.role_id != body.role_id:
        raise bad_request("不可變更自己的角色")
    if user_id == current.id and not body.is_active:
        raise bad_request("不可停用自己的帳號")
    user.email = body.email
    user.display_name = body.display_name
    user.role_id = body.role_id
    user.is_active = body.is_active
    user.updated_at = utcnow()
    db.commit()
    db.refresh(user)
    return _user_dto(user)


@router.post("/users/{user_id}/reset-password", status_code=204)
def reset_password(user_id: int, body: s.ResetPasswordRequest, db: Session = Depends(get_db),
                   _: CurrentUser = Depends(require(P.SYSTEM_USER))):
    user = db.get(User, user_id)
    if user is None:
        raise not_found("帳號不存在")
    now = utcnow()
    user.password_hash = hash_password(body.new_password)
    user.failed_login_count = 0
    user.locked_until = None
    user.updated_at = now
    db.execute(update(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
               .values(revoked_at=now))
    db.commit()
    return Response(status_code=204)


@router.post("/users/{user_id}/toggle-active")
def toggle_active(user_id: int, db: Session = Depends(get_db), current: CurrentUser = Depends(require(P.SYSTEM_USER))):
    if user_id == current.id:
        raise bad_request("不可停用自己的帳號")
    user = db.get(User, user_id)
    if user is None:
        raise not_found("帳號不存在")
    user.is_active = not user.is_active
    user.updated_at = utcnow()
    db.commit()
    return {"isActive": user.is_active}


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: int, db: Session = Depends(get_db), current: CurrentUser = Depends(require(P.SYSTEM_USER))):
    if user_id == current.id:
        raise bad_request("不可刪除自己的帳號")
    user = db.get(User, user_id)
    if user is None:
        raise not_found("帳號不存在")
    db.delete(user)
    db.commit()
    return Response(status_code=204)


# ============================================================ 角色

def _role_dto(db: Session, r: Role) -> s.RoleDto:
    count = db.scalar(select(func.count()).select_from(User).where(User.role_id == r.id))
    perms = sorted(r.permissions, key=lambda p: p.id)
    return s.RoleDto(id=r.id, code=r.code, name=r.name, description=r.description, is_system=r.is_system,
                     user_count=count, permission_ids=[p.id for p in perms],
                     permission_codes=sorted(p.code for p in perms), created_at=r.created_at)


@router.get("/roles", response_model=list[s.RoleDto])
def list_roles(db: Session = Depends(get_db), _: CurrentUser = Depends(require(P.SYSTEM_ROLE))):
    return [_role_dto(db, r) for r in db.scalars(select(Role).order_by(Role.id))]


@router.get("/roles/permissions", response_model=list[s.PermissionDto])
def list_permissions(db: Session = Depends(get_db), _: CurrentUser = Depends(require(P.SYSTEM_ROLE))):
    """全部權限,供角色管理頁勾選。"""
    return [s.PermissionDto(id=p.id, code=p.code, name=p.name, group_name=p.group_name)
            for p in db.scalars(select(Permission).order_by(Permission.id))]


@router.get("/roles/menus", response_model=list[s.MenuNodeDto])
def list_menus(db: Session = Depends(get_db), _: CurrentUser = Depends(require(P.SYSTEM_ROLE))):
    """完整選單樹 (未過濾),用來對照「側邊欄依角色開放」設定。"""
    return build_menu(db, None)


def _replace_permissions(db: Session, role_id: int, permission_ids: list[int]) -> None:
    valid = db.scalars(select(Permission.id).where(Permission.id.in_(permission_ids or [-1]))).all()
    db.execute(delete(RolePermission).where(RolePermission.role_id == role_id))
    db.add_all(RolePermission(role_id=role_id, permission_id=pid) for pid in valid)
    db.commit()


@router.post("/roles", response_model=s.RoleDto)
def create_role(body: s.RoleUpsertRequest, db: Session = Depends(get_db),
                _: CurrentUser = Depends(require(P.SYSTEM_ROLE))):
    if db.scalar(select(Role.id).where(Role.code == body.code)):
        raise conflict("角色代碼已存在")
    role = Role(code=body.code, name=body.name, description=body.description, is_system=False)
    db.add(role)
    db.commit()
    _replace_permissions(db, role.id, body.permission_ids)
    db.refresh(role)
    return _role_dto(db, role)


@router.put("/roles/{role_id}", response_model=s.RoleDto)
def update_role(role_id: int, body: s.RoleUpsertRequest, db: Session = Depends(get_db),
                _: CurrentUser = Depends(require(P.SYSTEM_ROLE))):
    role = db.get(Role, role_id)
    if role is None:
        raise not_found("角色不存在")
    if db.scalar(select(Role.id).where(Role.code == body.code, Role.id != role_id)):
        raise conflict("角色代碼已存在")
    # 系統角色允許改名與權限,但不允許改代碼 (程式與 seed 依賴)
    if not role.is_system:
        role.code = body.code
    role.name = body.name
    role.description = body.description
    db.commit()
    _replace_permissions(db, role_id, body.permission_ids)
    db.refresh(role)
    return _role_dto(db, role)


@router.delete("/roles/{role_id}", status_code=204)
def delete_role(role_id: int, db: Session = Depends(get_db), _: CurrentUser = Depends(require(P.SYSTEM_ROLE))):
    role = db.get(Role, role_id)
    if role is None:
        raise not_found("角色不存在")
    if role.is_system:
        raise bad_request("系統內建角色不可刪除")
    if db.scalar(select(User.id).where(User.role_id == role_id).limit(1)):
        raise bad_request("仍有帳號使用此角色")
    db.delete(role)
    db.commit()
    return Response(status_code=204)
