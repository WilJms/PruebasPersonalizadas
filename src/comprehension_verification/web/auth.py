"""Invite-only application sessions and Supabase JWT verification adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import secrets

import jwt
from fastapi import HTTPException, Request, Response, status

from ..canonical import stable_id
from .repository import Repository
from .settings import Settings


@dataclass(frozen=True, slots=True)
class Actor:
    user_id: str
    email: str
    workspace_id: str
    role: str
    can_approve_assessments: bool
    csrf_token: str


class AuthService:
    def __init__(self, settings: Settings, repository: Repository) -> None:
        self.settings = settings
        self.repository = repository
        self._jwks_client: jwt.PyJWKClient | None = None

    def seed_local_users(self) -> None:
        if self.settings.environment == "cloud":
            return
        users: list[tuple[str, str, str]] = []
        for email in sorted(self.settings.invited_emails):
            role = "ASSISTANT" if email.startswith("assistant") else "TEACHER"
            users.append((stable_id("usr", email), email, role))
        self.repository.seed_workspace(self.settings.local_workspace_id, users)

    def authenticate(self, request: Request) -> Actor:
        token = request.cookies.get(self.settings.session_cookie_name)
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "SESSION_REQUIRED", "message": "Authentication is required."},
            )
        try:
            claims = jwt.decode(
                token,
                self.settings.session_secret,
                algorithms=["HS256"],
                audience="cva-web",
                issuer="cva-web",
                options={"require": ["exp", "iat", "sub", "workspace_id", "csrf"]},
            )
        except jwt.PyJWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "SESSION_INVALID", "message": "The session is invalid or expired."},
            ) from exc
        membership = self.repository.membership_for_user(str(claims["sub"]))
        if membership is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "WORKSPACE_ACCESS_DENIED", "message": "No workspace membership."},
            )
        user, role = membership
        if role.workspace_id != claims["workspace_id"]:
            raise HTTPException(status_code=403, detail={"code": "WORKSPACE_ACCESS_DENIED"})
        return Actor(
            user_id=user.id,
            email=user.email,
            workspace_id=role.workspace_id,
            role=role.role,
            can_approve_assessments=role.can_approve_assessments,
            csrf_token=str(claims["csrf"]),
        )

    def require_csrf(self, request: Request, actor: Actor) -> None:
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return
        header = request.headers.get("X-CSRF-Token")
        cookie = request.cookies.get(self.settings.csrf_cookie_name)
        if not header or not cookie or not secrets.compare_digest(header, cookie):
            raise HTTPException(status_code=403, detail={"code": "CSRF_FAILED"})
        if not secrets.compare_digest(header, actor.csrf_token):
            raise HTTPException(status_code=403, detail={"code": "CSRF_FAILED"})

    def local_login(self, email: str, response: Response) -> Actor:
        if self.settings.environment == "cloud" or self.settings.auth_mode != "local":
            raise HTTPException(status_code=404, detail={"code": "LOCAL_LOGIN_DISABLED"})
        if email.lower() not in self.settings.invited_emails:
            raise HTTPException(status_code=403, detail={"code": "INVITATION_REQUIRED"})
        membership = self.repository.membership_for_email(email)
        if membership is None:
            raise HTTPException(status_code=403, detail={"code": "INVITATION_REQUIRED"})
        user, role = membership
        csrf = secrets.token_urlsafe(24)
        self._set_session(response, user.id, role.workspace_id, csrf)
        return Actor(
            user_id=user.id,
            email=user.email,
            workspace_id=role.workspace_id,
            role=role.role,
            can_approve_assessments=role.can_approve_assessments,
            csrf_token=csrf,
        )

    def exchange_supabase_token(self, access_token: str, response: Response) -> Actor:
        if self.settings.auth_mode != "supabase":
            raise HTTPException(status_code=404, detail={"code": "SUPABASE_AUTH_DISABLED"})
        try:
            if self._jwks_client is None:
                assert self.settings.supabase_jwks_url is not None
                self._jwks_client = jwt.PyJWKClient(self.settings.supabase_jwks_url, cache_keys=True)
            key = self._jwks_client.get_signing_key_from_jwt(access_token)
            claims = jwt.decode(
                access_token,
                key.key,
                algorithms=["RS256", "ES256"],
                audience=self.settings.supabase_jwt_audience,
                issuer=self.settings.supabase_jwt_issuer,
                options={"require": ["exp", "iat", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise HTTPException(status_code=401, detail={"code": "SUPABASE_TOKEN_INVALID"}) from exc
        membership = self.repository.membership_for_user(str(claims["sub"]))
        if membership is None:
            raise HTTPException(status_code=403, detail={"code": "INVITATION_REQUIRED"})
        user, role = membership
        csrf = secrets.token_urlsafe(24)
        self._set_session(response, user.id, role.workspace_id, csrf)
        return Actor(
            user_id=user.id,
            email=user.email,
            workspace_id=role.workspace_id,
            role=role.role,
            can_approve_assessments=role.can_approve_assessments,
            csrf_token=csrf,
        )

    def logout(self, response: Response) -> None:
        response.delete_cookie(self.settings.session_cookie_name, path="/")
        response.delete_cookie(self.settings.csrf_cookie_name, path="/")

    def _set_session(self, response: Response, user_id: str, workspace_id: str, csrf: str) -> None:
        now = datetime.now(UTC)
        token = jwt.encode(
            {
                "iss": "cva-web",
                "aud": "cva-web",
                "sub": user_id,
                "workspace_id": workspace_id,
                "csrf": csrf,
                "iat": now,
                "exp": now + timedelta(seconds=self.settings.session_ttl_seconds),
            },
            self.settings.session_secret,
            algorithm="HS256",
        )
        secure = self.settings.environment == "cloud"
        response.set_cookie(
            self.settings.session_cookie_name,
            token,
            max_age=self.settings.session_ttl_seconds,
            httponly=True,
            secure=secure,
            samesite="lax",
            path="/",
        )
        response.set_cookie(
            self.settings.csrf_cookie_name,
            csrf,
            max_age=self.settings.session_ttl_seconds,
            httponly=False,
            secure=secure,
            samesite="lax",
            path="/",
        )

