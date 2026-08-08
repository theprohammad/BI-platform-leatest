"""phase2_5_lifecycle: claim_transitions + claim identity v2

Revision ID: 0002
Revises: 0001

Deterministic data step: recompute identity for predicated claims with
non-null values (CLAIM_IDENTITY_VERSION=2); collision groups (paraphrase
duplicates) are merged into the earliest-created row with evidence union and
supersession lineage. Ordering is deterministic (created_at, id).
Downgrade drops claim_transitions and restores v1 hashes on unmerged rows;
merged rows remain merged (documented one-way data step).
"""
import hashlib

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _norm_value(value: str) -> str:
    # mirror of app.graph.predicates.normalize_value v1 (frozen for this revision)
    import re
    v = " ".join(str(value).strip().split())
    v = re.sub(r"^(approximately|approx\.?|about|around|roughly|~|estimated|est\.?)\s+",
               "", v, flags=re.IGNORECASE)
    v = re.sub(r"(?<=\d),(?=\d{3}\b)", "", v)
    return v.casefold().rstrip(".")


def _identity_v2(ws: str, subject: str, predicate: str, value: str) -> str:
    return hashlib.sha256(f"{ws}|{subject}|{predicate}|{_norm_value(value)}".encode()).hexdigest()


def _identity_v1(ws: str, subject: str, topic: str, statement: str) -> str:
    key = f"{ws}|{subject}|{topic}|{' '.join(statement.split()).lower()}"
    return hashlib.sha256(key.encode()).hexdigest()


def upgrade() -> None:
    op.create_table(
        "claim_transitions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("claim_id", sa.String(length=32), nullable=False),
        sa.Column("from_status", sa.String(length=20), nullable=False),
        sa.Column("to_status", sa.String(length=20), nullable=False),
        sa.Column("counterpart_id", sa.String(length=32), nullable=True),
        sa.Column("reason", sa.String(length=40), nullable=False),
        sa.Column("run_id", sa.String(length=40), nullable=True),
        sa.Column("at", sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_claim_transitions_claim_id"), "claim_transitions",
                    ["claim_id"], unique=False)

    # ---- identity v2 recompute + deterministic collision merge --------------
    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT id, workspace_id, subject_entity_id, predicate, value, "
        "created_at, evidence_ids FROM claims "
        "WHERE predicate IS NOT NULL AND value IS NOT NULL AND value != '' "
        "ORDER BY created_at, id")).mappings().all()

    groups: dict[str, list] = {}
    for r in rows:
        h = _identity_v2(r["workspace_id"], r["subject_entity_id"],
                         r["predicate"], r["value"])
        groups.setdefault(h, []).append(r)

    now = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc).isoformat()
    merged = 0
    for new_hash, members in groups.items():
        winner = members[0]                      # earliest (created_at, id)
        for loser in members[1:]:
            ev = conn.execute(sa.text(
                "SELECT evidence_id FROM claim_evidence WHERE claim_id = :c"),
                {"c": loser["id"]}).scalars().all()
            have = set(conn.execute(sa.text(
                "SELECT evidence_id FROM claim_evidence WHERE claim_id = :c"),
                {"c": winner["id"]}).scalars().all())
            for e in ev:
                if e not in have:
                    conn.execute(sa.text(
                        "INSERT INTO claim_evidence (claim_id, evidence_id) "
                        "VALUES (:c, :e)"), {"c": winner["id"], "e": e})
                    have.add(e)
            conn.execute(sa.text(
                "UPDATE claims SET status='superseded', superseded_by=:w "
                "WHERE id=:l"), {"w": winner["id"], "l": loser["id"]})
            conn.execute(sa.text(
                "INSERT INTO claim_transitions (claim_id, from_status, to_status, "
                "counterpart_id, reason, run_id, at) VALUES "
                "(:c, 'active', 'superseded', :w, 'identity_v2_migration', NULL, :at)"),
                {"c": loser["id"], "w": winner["id"], "at": now})
            merged += 1
        if len(members) > 1:   # sync the evidence_ids JSON read-cache (C3:
            import json         # junction is truth; the cache must match it)
            union = conn.execute(sa.text(
                "SELECT evidence_id FROM claim_evidence WHERE claim_id = :c"),
                {"c": winner["id"]}).scalars().all()
            conn.execute(sa.text("UPDATE claims SET evidence_ids=:e WHERE id=:i"),
                         {"e": json.dumps(list(union)), "i": winner["id"]})
        conn.execute(sa.text("UPDATE claims SET identity_hash=:h WHERE id=:i"),
                     {"h": new_hash, "i": winner["id"]})
    # deterministic sanity: every group left exactly one row on the new hash
    dupes = conn.execute(sa.text(
        "SELECT identity_hash, COUNT(*) FROM claims GROUP BY identity_hash "
        "HAVING COUNT(*) > 1")).all()
    assert not dupes, f"identity v2 migration left duplicate hashes: {dupes}"


def downgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT id, workspace_id, subject_entity_id, topic, statement FROM claims "
        "WHERE predicate IS NOT NULL AND value IS NOT NULL AND value != ''"
    )).mappings().all()
    for r in rows:
        conn.execute(sa.text("UPDATE claims SET identity_hash=:h WHERE id=:i"),
                     {"h": _identity_v1(r["workspace_id"], r["subject_entity_id"],
                                        r["topic"], r["statement"]),
                      "i": r["id"]})
    op.drop_index(op.f("ix_claim_transitions_claim_id"), table_name="claim_transitions")
    op.drop_table("claim_transitions")
