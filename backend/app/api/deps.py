"""Shared FastAPI dependencies (overridable in tests via app.dependency_overrides)."""

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.models import Project
from app.db.session import get_session
from app.services import projects as projects_service

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
BearerDep = Annotated[HTTPAuthorizationCredentials | None, Depends(HTTPBearer(auto_error=False))]


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"}
    )


async def require_admin(settings: SettingsDep, credentials: BearerDep) -> None:
    """Management API: `Authorization: Bearer <ADMIN_TOKEN>`."""
    expected = settings.admin_token.get_secret_value()
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "ADMIN_TOKEN is not configured.")
    if credentials is None or not secrets.compare_digest(
        credentials.credentials.encode(), expected.encode()
    ):
        raise _unauthorized("Invalid admin token.")


async def get_api_key_project(session: SessionDep, credentials: BearerDep) -> Project:
    """SDK API: `Authorization: Bearer <project API key>` -> its project, else 401."""
    if credentials is None:
        raise _unauthorized("Missing API key.")
    project = await projects_service.project_for_key(session, credentials.credentials)
    if project is None:
        raise _unauthorized("Invalid or revoked API key.")
    return project


ApiKeyProjectDep = Annotated[Project, Depends(get_api_key_project)]
