"""Management API for projects and their API keys (admin token required)."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.deps import ApiKeyProjectDep, SessionDep, require_admin
from app.services import projects as projects_service

router = APIRouter(prefix="/projects", tags=["projects"], dependencies=[Depends(require_admin)])
sdk_router = APIRouter(prefix="/v1", tags=["sdk"])


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name must not be blank")
        return v.strip()


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    created_at: datetime


class ApiKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    prefix: str
    created_at: datetime
    revoked_at: datetime | None


class NewApiKeyOut(ApiKeyOut):
    # The full key. Returned once, at creation; only its hash is stored.
    key: str


class NewProjectOut(BaseModel):
    project: ProjectOut
    api_key: NewApiKeyOut


def _new_key_out(row, plaintext: str) -> NewApiKeyOut:
    return NewApiKeyOut(**ApiKeyOut.model_validate(row).model_dump(), key=plaintext)


async def _project_or_404(session, project_id: uuid.UUID):
    project = await projects_service.get_project(session, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return project


@router.post("", response_model=NewProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(body: ProjectIn, session: SessionDep) -> NewProjectOut:
    project, key, plaintext = await projects_service.create_project(session, body.name)
    return NewProjectOut(
        project=ProjectOut.model_validate(project), api_key=_new_key_out(key, plaintext)
    )


@router.get("", response_model=list[ProjectOut])
async def list_projects(session: SessionDep) -> list[ProjectOut]:
    return [ProjectOut.model_validate(p) for p in await projects_service.list_projects(session)]


@router.post(
    "/{project_id}/api-keys", response_model=NewApiKeyOut, status_code=status.HTTP_201_CREATED
)
async def create_api_key(project_id: uuid.UUID, session: SessionDep) -> NewApiKeyOut:
    await _project_or_404(session, project_id)
    key, plaintext = await projects_service.create_api_key(session, project_id)
    return _new_key_out(key, plaintext)


@router.get("/{project_id}/api-keys", response_model=list[ApiKeyOut])
async def list_api_keys(project_id: uuid.UUID, session: SessionDep) -> list[ApiKeyOut]:
    await _project_or_404(session, project_id)
    keys = await projects_service.list_api_keys(session, project_id)
    return [ApiKeyOut.model_validate(k) for k in keys]


@router.delete("/{project_id}/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(project_id: uuid.UUID, key_id: uuid.UUID, session: SessionDep) -> Response:
    if not await projects_service.revoke_api_key(session, project_id, key_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@sdk_router.get("/project", response_model=ProjectOut)
async def current_project(project: ApiKeyProjectDep) -> ProjectOut:
    """The project an API key belongs to. The SDK calls this to verify its config."""
    return ProjectOut.model_validate(project)
