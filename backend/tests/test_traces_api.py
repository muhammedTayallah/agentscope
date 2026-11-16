import uuid

from tests.test_ingest_api import iso, new_key, span, trace


async def seed(db_client, key, traces=(), spans=()):
    resp = await db_client.post(
        "/v1/ingest", json={"traces": list(traces), "spans": list(spans)}, headers=key
    )
    assert resp.status_code == 202, resp.text


async def test_requires_admin(db_client):
    resp = await db_client.get(f"/projects/{uuid.uuid4()}/traces")
    assert resp.status_code == 401


async def test_list_newest_first_with_counts_and_tokens(db_client, admin):
    pid, key = await new_key(db_client, admin)
    old, new = uuid.uuid4(), uuid.uuid4()
    await seed(
        db_client,
        key,
        traces=[
            trace(old, name="old run", start_time=iso(0)),
            trace(new, name="new run", start_time=iso(60), status="error", error="boom"),
        ],
        spans=[
            span(uuid.uuid4(), new, kind="llm", input_tokens=10, output_tokens=4),
            span(uuid.uuid4(), new, kind="llm", input_tokens=5),
            span(uuid.uuid4(), new),
        ],
    )
    page = (await db_client.get(f"/projects/{pid}/traces", headers=admin)).json()
    assert page["total"] == 2
    first, second = page["items"]
    assert (first["name"], first["status"], first["error"]) == ("new run", "error", "boom")
    assert (first["span_count"], first["input_tokens"], first["output_tokens"]) == (3, 15, 4)
    assert (second["name"], second["span_count"], second["input_tokens"]) == ("old run", 0, 0)


async def test_filters_and_paging(db_client, admin):
    pid, key = await new_key(db_client, admin)
    names = ["Support bot", "support_v2", "Billing agent", "100% done"]
    await seed(
        db_client,
        key,
        traces=[
            trace(uuid.uuid4(), name=n, start_time=iso(i), status="error" if i == 2 else "ok")
            for i, n in enumerate(names)
        ],
    )

    async def names_for(**params):
        page = (await db_client.get(f"/projects/{pid}/traces", params=params, headers=admin)).json()
        return [t["name"] for t in page["items"]], page["total"]

    assert await names_for(q="SUPPORT") == (["support_v2", "Support bot"], 2)
    assert await names_for(q="_") == (["support_v2"], 1)  # literal, not a wildcard
    assert await names_for(q="%") == (["100% done"], 1)
    assert await names_for(status="error") == (["Billing agent"], 1)
    assert await names_for(limit=2, offset=1) == (["Billing agent", "support_v2"], 4)
    bad = await db_client.get(f"/projects/{pid}/traces?status=bogus", headers=admin)
    assert bad.status_code == 422


async def test_detail_returns_spans_in_start_order(db_client, admin):
    pid, key = await new_key(db_client, admin)
    tid, root, child = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await seed(
        db_client,
        key,
        traces=[trace(tid, input={"q": "hi"}, output="bye", metadata={"v": 2})],
        spans=[
            span(child, tid, parent=root, name="llm", start_time=iso(2), metadata={"t": 1}),
            span(root, tid, name="agent", start_time=iso(1), end_time=iso(3)),
        ],
    )
    detail = (await db_client.get(f"/projects/{pid}/traces/{tid}", headers=admin)).json()
    assert (detail["input"], detail["output"], detail["metadata"]) == ({"q": "hi"}, "bye", {"v": 2})
    assert [s["name"] for s in detail["spans"]] == ["agent", "llm"]
    assert detail["spans"][1]["parent_id"] == str(root)
    assert detail["spans"][1]["metadata"] == {"t": 1}


async def test_projects_are_isolated(db_client, admin):
    pid_a, key_a = await new_key(db_client, admin, "A")
    pid_b, _ = await new_key(db_client, admin, "B")
    tid = uuid.uuid4()
    await seed(db_client, key_a, traces=[trace(tid)])
    assert (await db_client.get(f"/projects/{pid_b}/traces", headers=admin)).json()["total"] == 0
    resp = await db_client.get(f"/projects/{pid_b}/traces/{tid}", headers=admin)
    assert resp.status_code == 404
    assert (
        await db_client.get(f"/projects/{pid_a}/traces/{tid}", headers=admin)
    ).status_code == 200


async def test_unknown_project_and_trace_404(db_client, admin):
    pid, _ = await new_key(db_client, admin)
    resp = await db_client.get(f"/projects/{uuid.uuid4()}/traces", headers=admin)
    assert resp.status_code == 404
    resp = await db_client.get(f"/projects/{pid}/traces/{uuid.uuid4()}", headers=admin)
    assert resp.status_code == 404
