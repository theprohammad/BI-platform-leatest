"""Mandated tests: graph persistence, evidence storage/dedup, retrieval."""
import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Base
from app.graph.ontology import (Claim, Entity, EntityType, Evidence, Insight,
                                TrustVector)
from app.graph.store import IntelligenceGraph, content_hash


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


def ev(content: str, url="https://x.edu/a") -> Evidence:
    return Evidence(id="", url=url, canonical_url=url, domain="x.edu",
                    title="t", content=content)


async def test_evidence_dedup_is_identity(store):
    id1, created1 = await store.ingest_evidence(ev("Acme was founded in 2004."))
    id2, created2 = await store.ingest_evidence(ev("Acme  was founded   in 2004.",
                                                   url="https://mirror.com/b"))
    assert created1 is True and created2 is False
    assert id1 == id2 == content_hash("Acme was founded in 2004.")
    fetched = await store.get_evidence([id1])
    assert fetched[0].url == "https://x.edu/a"  # first provenance preserved


async def test_graph_persistence_roundtrip(store):
    entity = await store.resolve_entity("ws", "Acme University", EntityType.ORGANIZATION)
    again = await store.resolve_entity("ws", "acme  university")
    assert again.id == entity.id  # name-key resolution

    ev_id, _ = await store.ingest_evidence(ev("Acme enrolls 25000 students."))
    claim_id = await store.add_claim(Claim(
        id="", workspace_id="ws", subject_entity_id=entity.id,
        statement="Acme enrolls 25,000 students.", topic="profile",
        evidence_ids=[ev_id], trust=TrustVector(confidence=0.7)))
    fetched = await store.claims("ws", subject_entity_id=entity.id)
    assert fetched[0].id == claim_id and fetched[0].evidence_ids == [ev_id]

    with pytest.raises(Exception):  # claim without evidence is impossible
        await store.add_claim(Claim(id="", workspace_id="ws",
                                    subject_entity_id=entity.id,
                                    statement="unevidenced", evidence_ids=[]))

    with pytest.raises(ValueError):  # insight citing unknown claims is rejected
        await store.add_insight(Insight(id="", workspace_id="ws",
                                        organization_id="o", title="x", body="y",
                                        claim_ids=["missing"], authored_by="t"))

    ins_id = await store.add_insight(Insight(id="", workspace_id="ws",
                                             organization_id="o", title="x", body="y",
                                             claim_ids=[claim_id], authored_by="t"))
    assert (await store.insights("ws", "o"))[0].id == ins_id


async def test_coverage_and_retrieval(store):
    entity = await store.resolve_entity("ws", "Acme University", EntityType.ORGANIZATION)
    ev_id, _ = await store.ingest_evidence(ev("Tuition is 450k PKR per year."))
    await store.add_claim(Claim(id="", workspace_id="ws", subject_entity_id=entity.id,
                                statement="Acme tuition is 450,000 PKR per year.",
                                topic="pricing", evidence_ids=[ev_id],
                                trust=TrustVector(confidence=0.8)))
    cov = await store.coverage("ws", entity.id)
    assert cov["pricing"]["claims"] == 1

    hits = await store.search_claims("ws", "what is the tuition price")
    assert hits and "tuition" in hits[0].statement.lower()


async def test_competitor_edges_resilient_lookup(store):
    """competitor_edges_for_org returns the root's competitor edges, matches by
    the org's name/alias, and de-dupes by target. This is the resilient path the
    competitors page uses so competitor_of edges reliably surface."""
    from app.graph.ontology import Edge

    root = await store.resolve_entity("ws", "Acme University", EntityType.ORGANIZATION)
    rival = await store.resolve_entity("ws", "Beta College", EntityType.ORGANIZATION)
    rival2 = await store.resolve_entity("ws", "Gamma Institute", EntityType.ORGANIZATION)
    eid, _ = await store.ingest_evidence(ev("Acme competes with Beta College."))

    # two competitor edges on the canonical root
    await store.add_edge(Edge(id="", workspace_id="ws", source_entity_id=root.id,
                              relation="competitor_of", target_entity_id=rival.id,
                              evidence_ids=[eid]))
    await store.add_edge(Edge(id="", workspace_id="ws", source_entity_id=root.id,
                              relation="competitor_of", target_entity_id=rival2.id,
                              evidence_ids=[eid]))

    resilient = await store.competitor_edges_for_org("ws", root.id, "Acme University")
    targets = {e.target_entity_id for e in resilient}
    assert rival.id in targets and rival2.id in targets
    assert len(resilient) == 2

    # name lookup is case/whitespace-insensitive (matches _name_key normalization)
    resilient2 = await store.competitor_edges_for_org("ws", root.id, "  ACME   University ")
    assert len(resilient2) == 2

    # de-dupe by target: a duplicate edge to the same rival is collapsed
    await store.add_edge(Edge(id="", workspace_id="ws", source_entity_id=root.id,
                              relation="competitor_of", target_entity_id=rival.id,
                              evidence_ids=[eid]))
    resilient3 = await store.competitor_edges_for_org("ws", root.id, "Acme University")
    assert len(resilient3) == 2  # still two distinct competitors


def test_source_classification_is_deterministic():
    """Source transparency: domains map to executive-friendly categories +
    authentication scores deterministically (no fabrication)."""
    from app.api.v2 import _classify_source, _reliability_stars
    assert _classify_source("harvard.edu", "web")["category"] == "Academic"
    assert _classify_source("whitehouse.gov", "web")["category"] == "Government"
    assert _classify_source("reuters.com", "web")["category"] == "News"
    assert _classify_source("github.com", "web")["category"] == "Official Repository"
    assert _classify_source("acme.com", "web")["category"] == "Commercial"
    assert _classify_source("x.com", "web")["category"] == "Social / Community"
    assert _classify_source("", "measurement")["category"] == "Direct Measurement"
    # government scores higher authentication than social
    assert (_classify_source("nasa.gov", "web")["authentication_score"]
            > _classify_source("reddit.com", "web")["authentication_score"])
    # reliability stars are bounded 1..5
    assert 1 <= _reliability_stars(0.98, 0.8) <= 5
    assert _reliability_stars(0.98, 1.0) >= _reliability_stars(0.5, 0.0)


def test_validation_note_never_leaks_into_body():
    """Internal reviewer wording must never appear inline in a finding body.
    Both the current marker and the legacy '[critic]' form already persisted in
    existing databases are split out, so old intelligence is cleaned on read."""
    from app.graph.store import split_validation_note, VALIDATION_MARKER

    # current marker
    body, note = split_validation_note(
        f"Market grows 7.8% annually.{VALIDATION_MARKER}Supported by cited sources.")
    assert body == "Market grows 7.8% annually."
    assert note == "Supported by cited sources."
    assert "validation" not in body.lower()

    # legacy marker already in existing DBs
    body2, note2 = split_validation_note(
        "Demand is rising.\n\n[critic] The insight's assertions are supported.")
    assert body2 == "Demand is rising."
    assert "supported" in note2
    assert "[critic]" not in body2

    # bare inline form (defensive)
    body3, note3 = split_validation_note("Revenue up. [critic] verified.")
    assert "[critic]" not in body3 and "verified" in note3

    # no marker → unchanged, empty note
    body4, note4 = split_validation_note("Plain finding with no review.")
    assert body4 == "Plain finding with no review." and note4 == ""

    # empty input is safe
    assert split_validation_note("") == ("", "")
