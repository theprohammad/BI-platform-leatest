"""Phase 2.5 — Lifecycle Correctness regression matrix.
Every adversarial scenario from the verification report + final review becomes
a permanent test: predicate classes, identity v2 (proposition-based), status-
aware merge, resurrection/reactivation, dispute idempotency + auto-resolve,
tenancy validation, ingestion-order invariance, migration data step."""
import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.ledger import CostLedger
from app.db.models import Base
from app.graph.ontology import EntityType
from app.graph.store import IntelligenceGraph
from app.providers.llm.router import LLMRouter
from app.tools.registry import Budget, ToolContext, registry
import app.tools.graph_tools  # noqa: F401
import app.tools.web_tools    # noqa: F401
from tests.fakes_v2 import FakeSearchV2, ScriptedLLM


@pytest.fixture
async def graph(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/g.db")
    @event.listens_for(engine.sync_engine, "connect")
    def _fk(conn, _): conn.execute("PRAGMA foreign_keys=ON")
    import app.graph.models  # noqa
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield IntelligenceGraph(async_sessionmaker(engine, expire_on_commit=False))
    await engine.dispose()


def make_ctx(graph, ws="ws") -> ToolContext:
    return ToolContext(workspace_id=ws, run_id="t", graph=graph,
                       search=FakeSearchV2(),
                       llm=LLMRouter(ScriptedLLM(), ledger=CostLedger(), run_id="t"),
                       budget=Budget(max_searches=99), organization_id="org1")


async def ev(ctx, url, content):
    r = await registry.invoke(ctx, "graph.ingest_evidence", url=url, title="t",
                              content=content)
    return r["evidence_id"]


async def write(ctx, root, *, statement, predicate=None, value=None, topic="profile",
                as_of=None, evidence):
    return await registry.invoke(ctx, "graph.write_claim", subject_entity_id=root.id,
                                 statement=statement, predicate=predicate, value=value,
                                 topic=topic, as_of=as_of, evidence_ids=[evidence])


# ================= D1 replacement: multi-valued predicates ===================

async def test_multi_valued_predicates_accumulate(graph):
    ctx = make_ctx(graph)
    root = await graph.resolve_entity("ws", "Acme", EntityType.ORGANIZATION)
    e1 = await ev(ctx, "https://a.com/1", "beta competitor content")
    e2 = await ev(ctx, "https://b.com/2", "gamma competitor content")
    c1 = await write(ctx, root, statement="Acme competes with Beta.",
                     predicate="competitor_of", value="Beta University",
                     topic="competitors", evidence=e1)
    c2 = await write(ctx, root, statement="Acme competes with Gamma.",
                     predicate="competitor_of", value="Gamma Institute",
                     topic="competitors", evidence=e2)
    rows = await graph.get_claims([c1, c2])
    assert all(r.status == "active" for r in rows)     # NO destruction

    o1 = await write(ctx, root, statement="Acme offers BS CS.", predicate="offers",
                     value="BS Computer Science", evidence=e1)
    o2 = await write(ctx, root, statement="Acme offers MBA.", predicate="offers",
                     value="MBA", evidence=e2)
    rows = await graph.get_claims([o1, o2])
    assert all(r.status == "active" for r in rows)     # programs accumulate

    u1 = await write(ctx, root, statement="Weird one.", predicate="totally_unknown_pred",
                     value="x", evidence=e1)
    u2 = await write(ctx, root, statement="Weird two.", predicate="totally_unknown_pred",
                     value="y", evidence=e2)
    rows = await graph.get_claims([u1, u2])
    assert all(r.status == "active" for r in rows)     # unknown → destruction-proof


async def test_two_competitor_edges_persist_via_write_edge(graph):
    ctx = make_ctx(graph)
    acme = await graph.resolve_entity("ws", "Acme", EntityType.ORGANIZATION)
    beta = await graph.resolve_entity("ws", "Beta", EntityType.ORGANIZATION)
    gamma = await graph.resolve_entity("ws", "Gamma", EntityType.ORGANIZATION)
    e1 = await ev(ctx, "https://a.com/1", "beta edge content")
    e2 = await ev(ctx, "https://b.com/2", "gamma edge content")
    await registry.invoke(ctx, "graph.write_edge", source_entity_id=acme.id,
                          relation="competitor_of", target_entity_id=beta.id,
                          evidence_ids=[e1])
    await registry.invoke(ctx, "graph.write_edge", source_entity_id=acme.id,
                          relation="competitor_of", target_entity_id=gamma.id,
                          evidence_ids=[e2])
    edges = await graph.edges_from(acme.id, relation="competitor_of")
    assert len(edges) == 2                              # both visible
    backing = await graph.get_claims([e.claim_id for e in edges])
    assert all(b.status == "active" for b in backing)
    # backing claims went through the ONE claim door → diff-covered lifecycle


# ================= Identity v2: propositions =================================

async def test_paraphrase_and_value_normalization_merge(graph):
    ctx = make_ctx(graph)
    root = await graph.resolve_entity("ws", "Acme", EntityType.ORGANIZATION)
    e1 = await ev(ctx, "https://s1.edu/x", "enrollment src one content")
    e2 = await ev(ctx, "https://s2.gov/y", "enrollment src two content")
    c1 = await write(ctx, root, statement="Enrollment is 25,000.",
                     predicate="enrollment", value="25,000", evidence=e1)
    c2 = await write(ctx, root, statement="Acme enrolls approximately 25000 students.",
                     predicate="enrollment", value="approximately 25000",
                     topic="market", evidence=e2)          # different topic too
    assert c1 == c2                                    # one proposition, one row
    row = (await graph.get_claims([c1]))[0]
    assert row.trust.evidence_count == 2               # corroboration restored
    assert row.trust.corroboration > 0                 # two domains
    # different values stay distinct
    c3 = await write(ctx, root, statement="Enrollment is 24,800.",
                     predicate="enrollment", value="24,800", as_of="2026-01-01",
                     evidence=e1)
    assert c3 != c1


async def test_null_value_predicated_claims_stay_distinct(graph):
    """D2: valueless predicated claims use statement identity — never collapse."""
    ctx = make_ctx(graph)
    root = await graph.resolve_entity("ws", "Acme", EntityType.ORGANIZATION)
    e1 = await ev(ctx, "https://a.com/1", "online programs content")
    a = await write(ctx, root, statement="Acme offers online programs.",
                    predicate="offers", value=None, evidence=e1)
    b = await write(ctx, root, statement="Acme offers evening classes.",
                    predicate="offers", value=None, evidence=e1)
    assert a != b
    rows = await graph.get_claims([a, b])
    assert all(r.status == "active" for r in rows)


# ================= Oscillation + order invariance ============================

async def test_oscillation_resurrection(graph):
    """ranking 12 → 15 → 12: the proposition returns; final active = 12."""
    ctx = make_ctx(graph)
    root = await graph.resolve_entity("ws", "Acme", EntityType.ORGANIZATION)
    e = [await ev(ctx, f"https://r{i}.edu/x", f"ranking content {i}") for i in range(3)]
    c12 = await write(ctx, root, statement="Ranked 12th.", predicate="ranking",
                      value="12", as_of="2024-01-01", topic="market", evidence=e[0])
    c15 = await write(ctx, root, statement="Ranked 15th.", predicate="ranking",
                      value="15", as_of="2025-01-01", topic="market", evidence=e[1])
    assert (await graph.get_claims([c12]))[0].status == "superseded"
    back = await write(ctx, root, statement="Ranked 12th again.", predicate="ranking",
                       value="12", as_of="2026-01-01", topic="market", evidence=e[2])
    assert back == c12                                  # SAME proposition row
    final12 = (await graph.get_claims([c12]))[0]
    final15 = (await graph.get_claims([c15]))[0]
    assert final12.status == "active" and final12.superseded_by is None
    assert final15.status == "superseded" and final15.superseded_by == c12
    trans = await graph.transitions_for(c12)
    assert [t["to"] for t in trans] == ["superseded", "active"]   # full lineage
    assert trans[-1]["reason"] == "resurrected"


async def test_stale_undated_reassertion_stays_dead(graph):
    """Rule 6: unknown-dated re-assertion of a superseded value attaches for
    lineage but never flips current state (asymmetric default)."""
    ctx = make_ctx(graph)
    root = await graph.resolve_entity("ws", "Acme", EntityType.ORGANIZATION)
    e1 = await ev(ctx, "https://a.edu/old", "old enrollment content")
    e2 = await ev(ctx, "https://a.edu/new", "new enrollment content")
    e3 = await ev(ctx, "https://mirror.com/c", "cached mirror content")
    old = await write(ctx, root, statement="Enrollment 20,000.", predicate="enrollment",
                      value="20000", as_of="2024-01-01", evidence=e1)
    new = await write(ctx, root, statement="Enrollment 25,000.", predicate="enrollment",
                      value="25000", as_of="2026-01-01", evidence=e2)
    back = await write(ctx, root, statement="Enrollment 20,000.", predicate="enrollment",
                       value="20000", evidence=e3)      # NO as_of, no pub date
    assert back == old
    row = (await graph.get_claims([old]))[0]
    assert row.status == "superseded"                   # stayed dead
    assert row.trust.evidence_count == 2                # lineage attached
    active = await graph.claims("ws", subject_entity_id=root.id)
    assert {c.id for c in active if c.predicate == "enrollment"} == {new}
    # no phantom dispute between the corpse and its successor
    disputes = [i for i in await graph.insights("ws", "org1") if i.kind.value == "dispute"]
    assert not disputes


async def test_ingestion_order_row_topology_invariance(graph, tmp_path):
    """Final-review requirement: same facts, different arrival orders →
    identical row topology (one row per proposition). v2-G could not pass this."""
    import itertools
    facts = [("20000", "2020-06-01"), ("25000", "2022-06-01"), ("20000", "2024-06-01")]
    topologies = []
    for perm_i, perm in enumerate(itertools.permutations(facts)):
        ws = f"ws{perm_i}"
        ctx = make_ctx(graph, ws=ws)
        root = await graph.resolve_entity(ws, "Acme", EntityType.ORGANIZATION)
        for j, (value, as_of) in enumerate(perm):
            e = await ev(ctx, f"https://p{perm_i}s{j}.edu/x",
                         f"perm {perm_i} src {j} enrollment content")
            await write(ctx, root, statement=f"Enrollment {value} ({as_of}).",
                        predicate="enrollment", value=value, as_of=as_of, evidence=e)
        rows = await graph.claims(ws, subject_entity_id=root.id, status="any")
        topologies.append(sorted((r.predicate, r.value) for r in rows))
    assert all(t == topologies[0] for t in topologies), topologies
    assert topologies[0] == [("enrollment", "20000"), ("enrollment", "25000")]


# ================= Reactivation (D3 bound) ====================================

async def test_unsupported_reactivates_only_on_new_domain(graph):
    ctx = make_ctx(graph)
    root = await graph.resolve_entity("ws", "Acme", EntityType.ORGANIZATION)
    e1 = await ev(ctx, "https://blogspot.com/a", "forty programs blog content")
    claim = await write(ctx, root, statement="Acme has 40 programs.", evidence=e1)
    await graph.set_claim_status([claim], "unsupported")

    e_same = await ev(ctx, "https://blogspot.com/b", "same blog again forty programs")
    r = await registry.invoke(ctx, "graph.write_claim", subject_entity_id=root.id,
                              statement="Acme has 40 programs.", topic="profile",
                              evidence_ids=[e_same])
    assert (await graph.get_claims([r]))[0].status == "unsupported"  # same domain: dead

    e_new = await ev(ctx, "https://acme.edu/catalog", "official catalog forty programs")
    r = await registry.invoke(ctx, "graph.write_claim", subject_entity_id=root.id,
                              statement="Acme has 40 programs.", topic="profile",
                              evidence_ids=[e_new])
    row = (await graph.get_claims([r]))[0]
    assert row.status == "active"                       # new domain: reactivated
    trans = await graph.transitions_for(claim)
    assert trans[-1]["reason"] == "reactivated_new_domain"


# ================= Disputes: idempotent + auto-resolving =====================

async def test_dispute_idempotent_and_autoresolves(graph):
    ctx = make_ctx(graph)
    root = await graph.resolve_entity("ws", "Acme", EntityType.ORGANIZATION)
    e_edu = await ev(ctx, "https://acme.edu/r", "ranked 12 content")
    strong = await write(ctx, root, statement="Ranked 12th.", predicate="ranking",
                         value="12", as_of="2026-01-01", topic="market", evidence=e_edu)
    weak = None
    for i in range(2):                                  # repeated re-encounters
        e_blog = await ev(ctx, f"https://blogspot.com/r{i}", f"ranked 30 take {i}")
        weak = await write(ctx, root, statement="Ranked 30th.", predicate="ranking",
                           value="30", as_of="2026-06-01", topic="market",
                           evidence=e_blog)
    disputes = [i for i in await graph.insights("ws", "org1") if i.kind.value == "dispute"]
    open_d = [d for d in disputes if d.debate_status != "resolved"]
    assert len(open_d) == 1                             # idempotent
    assert (await graph.get_claims([strong]))[0].status == "active"  # gate held

    await graph.set_claim_status([weak], "unsupported")  # conflict ends
    disputes = [i for i in await graph.insights("ws", "org1") if i.kind.value == "dispute"]
    assert all(d.debate_status == "resolved" for d in disputes)   # auto-resolved


# ================= Tenancy (A5) ================================================

async def test_cross_tenant_writes_rejected(graph):
    ctx = make_ctx(graph, ws="ws")
    victim = await graph.resolve_entity("WS_OTHER", "Victim Corp", EntityType.ORGANIZATION)
    mine = await graph.resolve_entity("ws", "Acme", EntityType.ORGANIZATION)
    e1 = await ev(ctx, "https://a.com/1", "tenancy test content")
    with pytest.raises(Exception):
        await registry.invoke(ctx, "graph.write_claim", subject_entity_id=victim.id,
                              statement="x", topic="profile", evidence_ids=[e1])
    with pytest.raises(Exception):
        await registry.invoke(ctx, "graph.write_edge", source_entity_id=mine.id,
                              relation="partners_with", target_entity_id=victim.id,
                              evidence_ids=[e1])
    ok = await registry.invoke(ctx, "graph.write_claim", subject_entity_id=mine.id,
                               statement="fine", topic="profile", evidence_ids=[e1])
    with pytest.raises(Exception):                      # other-ws ctx can't touch it
        await registry.invoke(make_ctx(graph, ws="WS_OTHER"), "graph.set_claim_status",
                              claim_ids=[ok], status="unsupported")
    with pytest.raises(ValueError):                     # merge guard
        await graph.merge_entities("ws", loser_id=victim.id, winner_id=mine.id,
                                   score=0.9, method="manual")


# ================= Migration 0002 data step ===================================

def test_migration_merges_paraphrase_duplicates(tmp_path):
    import pathlib
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    root = pathlib.Path(__file__).resolve().parents[1]
    url = f"sqlite:///{tmp_path}/mig25.db"
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0001")

    eng = create_engine(url)
    with eng.begin() as c:
        c.execute(text("INSERT INTO workspaces (id, name, created_at) VALUES ('ws','w','2026-01-01')"))
        c.execute(text("INSERT INTO entities (id, workspace_id, type, name, name_key, aliases, attributes) "
                       "VALUES ('ent1','ws','organization','Acme','acme','[]','{}')"))
        c.execute(text("INSERT INTO evidence (id, url, canonical_url, domain, title, content, "
                       "source_type, retrieved_at, quality_score, visibility) VALUES "
                       "('ev1','https://a.edu/1','https://a.edu/1','a.edu','t','c1','web','2026-01-01',0.5,'workspace'),"
                       "('ev2','https://b.gov/2','https://b.gov/2','b.gov','t','c2','web','2026-01-01',0.5,'workspace')"))
        for cid, stmt, val, ev_id, created in (
                ("cl1", "Enrollment is 25,000.", "25,000", "ev1", "2026-01-01T00"),
                ("cl2", "Acme enrolls 25000 students.", "25000", "ev2", "2026-01-02T00")):
            c.execute(text(
                "INSERT INTO claims (id, workspace_id, subject_entity_id, kind, statement, "
                "value, predicate, topic, identity_hash, status, evidence_ids, trust, "
                "source_type, created_at) VALUES "
                f"('{cid}','ws','ent1','metric','{stmt}','{val}','enrollment','profile',"
                f"'v1hash_{cid}','active','[\"{ev_id}\"]','{{}}','web','{created}')"))
            c.execute(text(f"INSERT INTO claim_evidence (claim_id, evidence_id) VALUES ('{cid}','{ev_id}')"))

    command.upgrade(cfg, "0002")
    with eng.connect() as c:
        cl1 = c.execute(text("SELECT status, superseded_by FROM claims WHERE id='cl1'")).one()
        cl2 = c.execute(text("SELECT status, superseded_by FROM claims WHERE id='cl2'")).one()
        assert cl1.status == "active" and cl1.superseded_by is None      # earliest wins
        assert cl2.status == "superseded" and cl2.superseded_by == "cl1"
        evs = c.execute(text("SELECT evidence_id FROM claim_evidence WHERE claim_id='cl1'")).scalars().all()
        assert set(evs) == {"ev1", "ev2"}                                # evidence union
        trans = c.execute(text("SELECT reason FROM claim_transitions WHERE claim_id='cl2'")).scalar()
        assert trans == "identity_v2_migration"
        import json
        cache = json.loads(c.execute(text("SELECT evidence_ids FROM claims WHERE id='cl1'")).scalar())
        assert set(cache) == {"ev1", "ev2"}                # read-cache synced to junction
    eng.dispose()


# ================= Implementation-review regressions =========================

async def test_chain_middle_reassertion_stays_dead(graph):
    """Review fix 1: re-assertion newer than a MIDDLE link but older than the
    terminal incumbent is stale — no resurrection, no bogus dispute."""
    ctx = make_ctx(graph)
    root = await graph.resolve_entity("ws", "Acme", EntityType.ORGANIZATION)
    e = [await ev(ctx, f"https://c{i}.edu/x", f"chain content {i}") for i in range(4)]
    c10 = await write(ctx, root, statement="E 10k.", predicate="enrollment",
                      value="10000", as_of="2020-01-01", evidence=e[0])
    await write(ctx, root, statement="E 15k.", predicate="enrollment",
                value="15000", as_of="2022-01-01", evidence=e[1])
    c20 = await write(ctx, root, statement="E 20k.", predicate="enrollment",
                      value="20000", as_of="2024-01-01", evidence=e[2])
    back = await write(ctx, root, statement="E 10k.", predicate="enrollment",
                       value="10000", as_of="2023-01-01", evidence=e[3])
    assert back == c10
    assert (await graph.get_claims([c10]))[0].status == "superseded"
    active = [c for c in await graph.claims("ws", subject_entity_id=root.id)
              if c.predicate == "enrollment"]
    assert {c.id for c in active} == {c20}
    assert not [i for i in await graph.insights("ws", "org1")
                if i.kind.value == "dispute"]


async def test_tombstone_ids_write_to_winner_and_merge_survives_shared_evidence(graph):
    """Review fixes 3+4: stale entity ids redirect to the merge winner; merges
    survive duplicate edges sharing evidence (edge-evidence union dedup)."""
    ctx = make_ctx(graph)
    a = await graph.resolve_entity("ws", "Acme University", EntityType.ORGANIZATION)
    b = await graph.resolve_entity("ws", "The Acme University", EntityType.ORGANIZATION)
    other = await graph.resolve_entity("ws", "Beta", EntityType.ORGANIZATION)
    e1 = await ev(ctx, "https://x.edu/1", "shared evidence content")
    await registry.invoke(ctx, "graph.write_edge", source_entity_id=a.id,
                          relation="competitor_of", target_entity_id=other.id,
                          evidence_ids=[e1])
    await registry.invoke(ctx, "graph.write_edge", source_entity_id=b.id,
                          relation="competitor_of", target_entity_id=other.id,
                          evidence_ids=[e1])
    result = await graph.merge_entities("ws", loser_id=b.id, winner_id=a.id,
                                        score=0.95, method="manual")
    assert result["merged"]                                # no PK crash
    edges = await graph.edges_from(a.id, relation="competitor_of")
    assert len(edges) == 1                                 # deduped triple
    cid = await registry.invoke(ctx, "graph.write_claim", subject_entity_id=b.id,
                                statement="Post-merge write.", topic="profile",
                                evidence_ids=[e1])
    row = (await graph.get_claims([cid]))[0]
    assert row.subject_entity_id == a.id                   # landed on the winner
