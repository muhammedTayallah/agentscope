import uuid
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.security import hash_api_key
from app.db.models import ApiKey
from app.db.session import get_session
from app.main import app

# ---------- Admin guard (no database needed) ----------


@pytest.fixture
def no_db():
    session = AsyncMock(spec=AsyncSession)

    async def _get_session():
        yield session

    app.dependency_overrides[get_session] = _get_session
    return session


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong-token"}])
async def test_management_requires_admin_token(client, no_db, headers):
    for method, path in [("get", "/projects"), ("post", "/projects")]:
        resp = await client.request(method, path, headers=headers, json={"name": "x"})
        assert resp.status_code == 401
        assert resp.headers["www-authenticate"] == "Bearer"
    no_db.add.assert_not_called()


async def test_management_disabled_without_admin_token(client, no_db):
    app.dependency_overrides[get_settings] = lambda: Settings(admin_token=SecretStr(""))
    resp = await client.get("/projects", headers={"Authorization": "Bearer "})
    assert resp.status_code == 503


@pytest.mark.parametrize("name", ["", "   ", "x" * 101])
async def test_project_name_validated(client, no_db, admin, name):
    assert (await client.post("/projects", json={"name": name}, headers=admin)).status_code == 422


async def test_sdk_endpoint_without_key_is_401(client, no_db):
    resp = await client.get("/v1/project")
    assert resp.status_code == 401


# ---------- Against the real database ----------


async def test_create_project_returns_key_once_and_stores_only_hash(
    db_client, admin, session_factory
):
    resp = await db_client.post("/projects", json={"name": "  Support bot  "}, headers=admin)
    assert resp.status_code == 201
    body = resp.json()
    assert body["project"]["name"] == "Support bot"
    key = body["api_key"]["key"]
    assert key.startswith("ask_") and len(key) > 40
    assert body["api_key"]["prefix"] == key[:12]

    async with session_factory() as s:
        row = (await s.execute(select(ApiKey))).scalar_one()
    assert row.key_hash == hash_api_key(key)
    assert key not in (row.key_hash, row.prefix)

    # Listing never shows the full key again.
    keys = (
        await db_client.get(f"/projects/{body['project']['id']}/api-keys", headers=admin)
    ).json()
    assert len(keys) == 1 and "key" not in keys[0]


async def test_valid_key_identifies_project_bad_key_401(db_client, admin):
    created = (await db_client.post("/projects", json={"name": "A"}, headers=admin)).json()
    key = created["api_key"]["key"]

    ok = await db_client.get("/v1/project", headers={"Authorization": f"Bearer {key}"})
    assert ok.status_code == 200
    assert ok.json()["id"] == created["project"]["id"]

    for bad in [key + "x", "ask_" + "a" * 43, ADMIN_HEADER_VALUE(admin)]:
        resp = await db_client.get("/v1/project", headers={"Authorization": f"Bearer {bad}"})
        assert resp.status_code == 401, bad


def ADMIN_HEADER_VALUE(admin: dict) -> str:  # noqa: N802
    # The admin token must not work as a project API key.
    return admin["Authorization"].removeprefix("Bearer ")


async def test_second_key_and_revocation(db_client, admin):
    created = (await db_client.post("/projects", json={"name": "A"}, headers=admin)).json()
    pid = created["project"]["id"]
    first = created["api_key"]
    second = (await db_client.post(f"/projects/{pid}/api-keys", headers=admin)).json()
    assert second["key"] != first["key"]

    resp = await db_client.delete(f"/projects/{pid}/api-keys/{first['id']}", headers=admin)
    assert resp.status_code == 204
    # Revoking again is a no-op; unknown keys are 404.
    assert (
        await db_client.delete(f"/projects/{pid}/api-keys/{first['id']}", headers=admin)
    ).status_code == 204
    assert (
        await db_client.delete(f"/projects/{pid}/api-keys/{uuid.uuid4()}", headers=admin)
    ).status_code == 404

    def auth(k):
        return {"Authorization": f"Bearer {k['key']}"}

    assert (await db_client.get("/v1/project", headers=auth(first))).status_code == 401
    assert (await db_client.get("/v1/project", headers=auth(second))).status_code == 200

    keys = (await db_client.get(f"/projects/{pid}/api-keys", headers=admin)).json()
    revoked = {k["id"]: k["revoked_at"] for k in keys}
    assert revoked[first["id"]] is not None and revoked[second["id"]] is None


async def test_key_of_other_project_cannot_be_revoked(db_client, admin):
    a = (await db_client.post("/projects", json={"name": "A"}, headers=admin)).json()
    b = (await db_client.post("/projects", json={"name": "B"}, headers=admin)).json()
    resp = await db_client.delete(
        f"/projects/{b['project']['id']}/api-keys/{a['api_key']['id']}", headers=admin
    )
    assert resp.status_code == 404


async def test_list_projects_and_404s(db_client, admin):
    for n in ["first", "second"]:
        await db_client.post("/projects", json={"name": n}, headers=admin)
    names = [p["name"] for p in (await db_client.get("/projects", headers=admin)).json()]
    assert names == ["second", "first"]
    missing = uuid.uuid4()
    assert (await db_client.get(f"/projects/{missing}/api-keys", headers=admin)).status_code == 404
    assert (await db_client.post(f"/projects/{missing}/api-keys", headers=admin)).status_code == 404
