"""Hash-chain unit tests — deterministic hashing and tamper detection."""

import datetime as dt

from touchstone_audit.chain import GENESIS_HASH, AuditContent, verify_chain

T0 = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)


def _content(index, prev, *, event="user.login", meta=None):
    return AuditContent(
        organization_id="org-1", chain_index=index, source_event_id=f"evt-{index}",
        event_type=event, actor_type="user", actor_id="u1",
        resource_type="organization", resource_id="org-1",
        metadata=meta or {}, occurred_at=T0, prev_hash=prev,
    )


def _record(content):
    d = {
        "organization_id": content.organization_id, "chain_index": content.chain_index,
        "source_event_id": content.source_event_id, "event_type": content.event_type,
        "actor_type": content.actor_type, "actor_id": content.actor_id,
        "resource_type": content.resource_type, "resource_id": content.resource_id,
        "metadata": content.metadata, "occurred_at": content.occurred_at,
        "prev_hash": content.prev_hash,
    }
    d["record_hash"] = content.compute_hash()
    return d


def _build_chain(n):
    records, prev = [], GENESIS_HASH
    for i in range(n):
        c = _content(i, prev)
        r = _record(c)
        records.append(r)
        prev = r["record_hash"]
    return records


def test_hashing_is_deterministic():
    a = _content(0, GENESIS_HASH).compute_hash()
    b = _content(0, GENESIS_HASH).compute_hash()
    assert a == b
    assert len(a) == 64


def test_hash_depends_on_prev_hash():
    h1 = _content(1, "a" * 64).compute_hash()
    h2 = _content(1, "b" * 64).compute_hash()
    assert h1 != h2


def test_valid_chain_verifies():
    result = verify_chain(_build_chain(5))
    assert result.ok
    assert result.length == 5


def test_genesis_prev_hash_required():
    chain = _build_chain(3)
    chain[0]["prev_hash"] = "f" * 64  # not genesis
    chain[0]["record_hash"] = "x"     # would also mismatch
    result = verify_chain(chain)
    assert not result.ok
    assert result.broken_at_index == 0


def test_tampered_metadata_breaks_chain():
    chain = _build_chain(4)
    # Mutate a past record's metadata WITHOUT recomputing hashes (an attacker edit).
    chain[1]["metadata"] = {"tampered": True}
    result = verify_chain(chain)
    assert not result.ok
    assert result.broken_at_index == 1
    assert "record_hash" in result.reason


def test_reordering_breaks_chain():
    chain = _build_chain(4)
    chain[2], chain[3] = chain[3], chain[2]  # swap order
    result = verify_chain(chain)
    assert not result.ok


def test_empty_chain_is_ok():
    assert verify_chain([]).ok
