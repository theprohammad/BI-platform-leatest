# Claim Lifecycle — State Machine (LAW; tests enforce)

States: `active` · `unsupported` · `superseded`.
Invariant: `superseded_by` is a MUTABLE current-successor cache — non-null ⇔ status=superseded.
Lineage of record: append-only `claim_transitions` (retention-exempt), one row per transition, run-stamped.

Identity (CLAIM_IDENTITY_VERSION=2): predicated claims with NON-NULL value →
hash(ws | subject | predicate | normalize_value(value)); all other claims
(prose, or predicate with null value — D2) → hash(ws | subject | topic | statement).

Transitions:
1. (new) → active — insert.
2. active → active — identity merge: evidence union, trust recompute.
3. active → unsupported — verification failure (`set_claim_status`).
4. active → superseded — functional-predicate conflict lost (`supersede_claim`;
   counterpart = successor). Auto-resolves open disputes citing the claim.
5. unsupported → active (REACTIVATION) — identity merge whose evidence adds a
   DOMAIN not already linked (D3 bound); flows into the run's verification set.
   Same-domain re-assertions merge evidence without reactivating.
6. superseded → stale-attach (no transition) — identity merge whose incoming
   recency (as_of, else max evidence published_date, else UNKNOWN) is ≤ the
   successor's recency OR unknown: evidence attaches for lineage; row stays
   dead; id excluded from run outputs; diff never runs on it. Unknown-dated
   re-assertions are treated as stale (asymmetric: wrongly attaching to a dead
   row loses less than wrongly flipping current state).
7. superseded → active (RESURRECTION) — identity merge whose incoming recency
   is strictly NEWER than the successor's: status→active, superseded_by→NULL,
   diff runs and supersedes the displaced incumbent. Oscillating values
   (12 → 15 → 12) are first-class.
Diff engine preconditions: evaluated claim must be `active`; functional
predicates only; one open dispute per claim pair; disputes auto-resolve when
either claim leaves `active`.
