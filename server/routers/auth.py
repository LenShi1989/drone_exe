from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .. import schemas as s
from ..db import get_db, utcnow
from ..deps import ApiError, CurrentUser, bad_request, client_ip, get_current_user
from ..models import LoginLog, RefreshToken, User
from ..security import create_access_token, hash_password, new_refresh_token, verify_password
from ..services import build_menu, current_user_dto

router = APIRouter(prefix="/api", tags=["Auth"])

MAX_FAILED_ATTEMPTS = 5
LOCK_DURATION = timedelta(minutes=15)


def _log_login(db: Session, request: Request, user_id: int | None, username: str, success: bool,
               reason: str | None) -> None:
    db.add(LoginLog(user_id=user_id, username=username[:50], ip_address=client_ip(request),
                    user_agent=(request.headers.get("user-agent") or "")[:300] or None,
                    is_success=success, fail_reason=reason))
    db.commit()


def _issue_tokens(db: Session, user: User) -> s.LoginResponse:
    perms = [p.code for p in user.role.permissions]
    access, expires_in = create_access_token(user.id, user.username, user.display_name, user.role.code, perms)
    token, expires_at = new_refresh_token()
    db.add(RefreshToken(user_id=user.id, token=token, expires_at=expires_at))
    db.commit()
    return s.LoginResponse(access_token=access, refresh_token=token, expires_in=expires_in,
                           user=current_user_dto(user))


@router.post("/auth/login", response_model=s.LoginResponse)
def login(body: s.LoginRequest, request: Request, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username))
    if user is None:
        _log_login(db, request, None, body.username, False, "帳號不存在")
        raise ApiError(status.HTTP_401_UNAUTHORIZED, "帳號或密碼錯誤")

    now = utcnow()
    if user.locked_until is not None and user.locked_until > now:
        _log_login(db, request, user.id, user.username, False, "帳號鎖定中")
        local = user.locked_until.astimezone()
        raise ApiError(status.HTTP_423_LOCKED, f"帳號已鎖定,請於 {local:%H:%M} 後再試")

    if not user.is_active:
        _log_login(db, request, user.id, user.username, False, "帳號已停用")
        raise ApiError(status.HTTP_401_UNAUTHORIZED, "帳號已停用,請聯絡管理員")

    if not verify_password(body.password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= MAX_FAILED_ATTEMPTS:
            user.locked_until = now + LOCK_DURATION
            user.failed_login_count = 0
        db.commit()
        _log_login(db, request, user.id, user.username, False, "密碼錯誤")
        raise ApiError(status.HTTP_401_UNAUTHORIZED, "帳號或密碼錯誤")

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    response = _issue_tokens(db, user)
    _log_login(db, request, user.id, user.username, True, None)
    return response


@router.post("/auth/refresh", response_model=s.LoginResponse)
def refresh(body: s.RefreshRequest, db: Session = Depends(get_db)):
    token = db.scalar(select(RefreshToken).where(RefreshToken.token == body.refresh_token))
    if token is None or not token.is_active or not token.user.is_active:
        raise ApiError(status.HTTP_401_UNAUTHORIZED, "Refresh token 無效或已過期")
    token.revoked_at = utcnow()
    return _issue_tokens(db, token.user)


@router.post("/auth/logout", status_code=204)
def logout(body: s.RefreshRequest, db: Session = Depends(get_db), _: CurrentUser = Depends(get_current_user)):
    token = db.scalar(select(RefreshToken).where(RefreshToken.token == body.refresh_token))
    if token is not None:
        token.revoked_at = utcnow()
        db.commit()
    return Response(status_code=204)


@router.get("/auth/me", response_model=s.CurrentUserDto)
def me(db: Session = Depends(get_db), current: CurrentUser = Depends(get_current_user)):
    user = db.get(User, current.id)
    if user is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "帳號不存在")
    return current_user_dto(user)


@router.post("/auth/change-password", status_code=204)
def change_password(body: s.ChangePasswordRequest, db: Session = Depends(get_db),
                    current: CurrentUser = Depends(get_current_user)):
    user = db.get(User, current.id)
    if user is None:
        raise ApiError(status.HTTP_401_UNAUTHORIZED, "未登入或憑證已失效")
    if not verify_password(body.old_password, user.password_hash):
        raise bad_request("原密碼不正確")
    now = utcnow()
    user.password_hash = hash_password(body.new_password)
    user.updated_at = now
    # 密碼變更後撤銷所有 refresh token
    db.execute(update(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
               .values(revoked_at=now))
    db.commit()
    return Response(status_code=204)


@router.get("/menu", response_model=list[s.MenuNodeDto], tags=["Menu"])
def menu(db: Session = Depends(get_db), current: CurrentUser = Depends(get_current_user)):
    """側邊欄:僅回傳目前角色有權限的節點。"""
    return build_menu(db, current.permissions)
