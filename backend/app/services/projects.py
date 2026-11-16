import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import display_prefix, generate_api_key, hash_api_key
from app.db.models import ApiKey, Project


async def create_project(session: AsyncSession, name: str) -> tuple[Project, ApiKey, str]:
    """New project with its first API key. Returns (project, key row, plaintext key)."""
    project = Project(name=name)
    session.add(project)
    await session.flush()
    key, plaintext = _new_key(project.id)
    session.add(key)
    await session.commit()
    await session.refresh(project)
    await session.refresh(key)
    return project, key, plaintext


async def list_projects(session: AsyncSession) -> Sequence[Project]:
    result = await session.execute(select(Project).order_by(Project.created_at.desc()))
    return result.scalars().all()


async def get_project(session: AsyncSession, project_id: uuid.UUID) -> Project | None:
    return await session.get(Project, project_id)


async def create_api_key(session: AsyncSession, project_id: uuid.UUID) -> tuple[ApiKey, str]:
    key, plaintext = _new_key(project_id)
    session.add(key)
    await session.commit()
    await session.refresh(key)
    return key, plaintext


async def list_api_keys(session: AsyncSession, project_id: uuid.UUID) -> Sequence[ApiKey]:
    result = await session.execute(
        select(ApiKey).where(ApiKey.project_id == project_id).order_by(ApiKey.created_at.desc())
    )
    return result.scalars().all()


async def revoke_api_key(session: AsyncSession, project_id: uuid.UUID, key_id: uuid.UUID) -> bool:
    """Revoke a key of this project. False if no such key. Revoking twice is a no-op."""
    key = await session.get(ApiKey, key_id)
    if key is None or key.project_id != project_id:
        return False
    if key.revoked_at is None:
        key.revoked_at = func.now()
        await session.commit()
    return True


async def project_for_key(session: AsyncSession, plaintext: str) -> Project | None:
    """The project an active (not revoked) key belongs to, or None."""
    result = await session.execute(
        select(Project)
        .join(ApiKey, ApiKey.project_id == Project.id)
        .where(ApiKey.key_hash == hash_api_key(plaintext), ApiKey.revoked_at.is_(None))
    )
    return result.scalar_one_or_none()


def _new_key(project_id: uuid.UUID) -> tuple[ApiKey, str]:
    plaintext = generate_api_key()
    row = ApiKey(
        project_id=project_id, prefix=display_prefix(plaintext), key_hash=hash_api_key(plaintext)
    )
    return row, plaintext
