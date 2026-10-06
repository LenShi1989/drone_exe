"""認證 / 授權依賴與統一錯誤。"""
from __future__ import annotations

from dataclasses import dataclass, field

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .security import decode_access_token

_bearer = HTTPBearer(auto_error=False)


class ApiError(HTTPException):
    """回應格式 {"message": "..."},與原 API 相同。"""

    def __init__(self, status_code: int, message: str):
        super().__init__(status_code=status_code, detail=message)


def bad_request(message: str) -> ApiError:
    return ApiError(status.HTTP_400_BAD_REQUEST, message)


def not_found(message: str) -> ApiError:
    return ApiError(status.HTTP_404_NOT_FOUND, message)


def conflict(message: str) -> ApiError:
    return ApiError(status.HTTP_409_CONFLICT, message)


@dataclass
class CurrentUser:
    id: int
    username: str
    display_name: str
    role_code: str
    permissions: list[str] = field(default_factory=list)
    ip_address: str = "unknown"
    user_agent: str | None = None

    def has(self, code: str) -> bool:
        return code in self.permissions


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def principal_from_token(token: str) -> CurrentUser:
    claims = decode_access_token(token)
    return CurrentUser(
        id=int(claims["sub"]),
        username=claims.get("name", ""),
        display_name=claims.get("display_name", ""),
        role_code=claims.get("role_code", ""),
        permissions=list(claims.get("perm", [])),
    )


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    if credentials is None or not credentials.credentials:
        raise ApiError(status.HTTP_401_UNAUTHORIZED, "未登入或憑證已失效")
    try:
        user = principal_from_token(credentials.credentials)
    except jwt.InvalidTokenError:
        raise ApiError(status.HTTP_401_UNAUTHORIZED, "未登入或憑證已失效") from None
    user.ip_address = client_ip(request)
    user.user_agent = request.headers.get("user-agent")
    return user


def require(permission_code: str):
    """宣告端點所需權限碼,例:Depends(require(perms.MAP_EDIT))。"""

    def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not user.has(permission_code):
            raise ApiError(status.HTTP_403_FORBIDDEN, "權限不足")
        return user

    return checker
