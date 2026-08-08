"""Phase 1.5 hardening tests: identity/dedup, status semantics, reverse
queries, concurrency safety, read-path purity, tool-layer conformance."""
import asyncio
import pathlib
import re

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base
from app.graph.ontology import Claim, EntityType, Evidence, Insight
from app.graph.store import IntelligenceGraph


@pytest.fixture
async def store(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/graph.db")
    @event.listens_for(engine.sync_engine, "connect")
    def _fk(conn, _): conn.execute("PRAGMA foreign_keys=ON")
    import app.graph.models  # noqa
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield IntelligenceGraph(async_sessionmaker(engine, expire_on_commit=False))
    await engine.dispose()


def ev(content, url="https://x.edu/a", domain="x.edu"):
    return Evidence(id="", url=url, canonical_url=url, domain=domain,
                    title="t", content=content)


async def seed(store):
    ent = await store.resolve_entity("ws", "Acme", EntityType.ORGANIZATION)
    e1, _ = await store.ingest_evidence(ev("acme was founded in 2004 first source"))
    e2, _ = await store.ingest_evidence(ev("acme founded 2004 corroborating",
                                           url="https://y.gov/b", domain="y.gov"))
    return ent, e1, e2


async def test_claim_identity_merges_instead_of_duplicating(store):
    ent, e1, e2 = await seed(store)

    def claim(evidence_ids):
        return Claim(id="", workspace_id="ws", subject_entity_id=ent.id,
                     statement="Acme was founded in 2004.", topic="profile",
                     evidence_ids=evidence_ids)

    id1 = await store.add_claim(claim([e1]))
    id2 = await store.add_claim(claim([e2]))           # same identity, new evidence
    assert id1 == id2                                   # C4: no duplicate row
    merged = (await store.get_claims([id1]))[0]
    assert set(merged.evidence_ids) == {e1, e2}
    assert merged.trust.evidence_count == 2             # trust recomputed on merge
    assert merged.trust.corroboration > 0               # two domains
    cov = await store.coverage("ws", ent.id)
    assert cov["profile"]["claims"] == 1                # coverage stays honest


async def test_status_transitions_and_supersession(store):
    ent, e1, e2 = await seed(store)
    old = await store.add_claim(Claim(id="", workspace_id="ws", subject_entity_id=ent.id,
                                      statement="Enrollment is 20,000.",
                                      topic="profile", evidence_ids=[e1]))
    new = await store.add_claim(Claim(id="", workspace_id="ws", subject_entity_id=ent.id,
                                      statement="Enrollment is 25,000.",
                                      topic="profile", evidence_ids=[e2]))
    await store.supersede_claim(old, new)
    rows = await store.get_claims([old])
    assert rows[0].status == "superseded" and rows[0].superseded_by == new
    active = await store.claims("ws", subject_entity_id=ent.id)
    assert {c.id for c in active} == {new}              # superseded excluded

    await store.set_claim_status([new], "unsupported")
    assert not await store.claims("ws", subject_entity_id=ent.id)
    with pytest.raises(ValueError):
        await store.set_claim_status([new], "bogus_status")


async def test_reverse_queries(store):
    ent, e1, _ = await seed(store)
    cid = await store.add_claim(Claim(id="", workspace_id="ws", subject_entity_id=ent.id,
                                      statement="Acme is in Lahore.", topic="profile",
                                      evidence_ids=[e1]))
    ins = await store.add_insight(Insight(id="", workspace_id="ws", organization_id="o",
                                          title="T", body="B", claim_ids=[cid],
                                          authored_by="test"))
    citing = await store.claims_citing_evidence(e1)
    assert [c.id for c in citing] == [cid]              # monitoring primitive
    dependents = await store.insights_citing_claim(cid)
    assert [i.id for i in dependents] == [ins]          # staleness primitive


async def test_fk_rejects_ghost_evidence(store):
    ent, *_ = await seed(store)
    with pytest.raises(ValueError):
        await store.add_claim(Claim(id="", workspace_id="ws", subject_entity_id=ent.id,
                                    statement="Ghost.", topic="profile",
                                    evidence_ids=["deadbeef"]))


async def test_concurrent_resolve_entity_single_row(store):
    results = await asyncio.gather(*(
        store.resolve_entity("ws", "Beta University", EntityType.ORGANIZATION)
        for _ in range(10)))
    assert len({r.id for r in results}) == 1            # C2: no duplicate entities
    from app.graph.models import EntityRow
    async with store._sm() as s:
        count = (await s.execute(select(func.count()).select_from(EntityRow))).scalar()
    assert count == 1


async def test_concurrent_same_claim_single_row(store):
    ent, e1, e2 = await seed(store)
    ids = await asyncio.gather(*(
        store.add_claim(Claim(id="", workspace_id="ws", subject_entity_id=ent.id,
                              statement="Acme is private.", topic="profile",
                              evidence_ids=[e]))
        for e in (e1, e2, e1, e2, e1)))
    assert len(set(ids)) == 1                            # C2+C4 under concurrency


def test_no_graph_writes_outside_tool_layer():
    """C1 conformance: graph write methods may be called only from
    app/tools/ (handlers), app/graph/ (the store itself). Everything else
    must go through registry.invoke."""
    write_pattern = re.compile(
        r"\.(add_claim|add_edge|add_insight|ingest_evidence|resolve_entity|"
        r"set_claim_status|supersede_claim)\(|graph\._sm\(")
    app_root = pathlib.Path(__file__).resolve().parents[1] / "app"
    allowed = {app_root / "tools", app_root / "graph"}
    violations = []
    for path in app_root.rglob("*.py"):
        if any(str(path).startswith(str(a)) for a in allowed):
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if write_pattern.search(line) and not line.strip().startswith("#"):
                violations.append(f"{path.relative_to(app_root)}:{lineno}: {line.strip()}")
    assert not violations, "Graph writes bypass the Tool Layer:\n" + "\n".join(violations)


def test_tools_have_single_claim_door():
    """Phase 2.5: inside app/tools, only _write_claim may call add_claim —
    the backing-claim path must compose the tool (closes the A1-bis bypass)."""
    import pathlib, re
    tools_dir = pathlib.Path(__file__).resolve().parents[1] / "app" / "tools"
    calls = []
    for path in tools_dir.rglob("*.py"):
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if re.search(r"\.add_claim(_full)?\(", line) and not line.strip().startswith("#"):
                calls.append((path.name, lineno, line.strip()))
    assert len(calls) == 1 and "add_claim_full" in calls[0][2], (
        f"claims must enter through _write_claim only: {calls}")
