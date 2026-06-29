"""Hash-chain primitives for the tamper-evident audit log (ADR-011).

Each audit record commits to the entire history before it: its ``record_hash`` is
the SHA-256 of the record's canonical content **plus the previous record's hash**.
This forms a per-organization hash chain (a degenerate Merkle/blockchain): editing,
deleting, or reordering any past record changes its hash, which breaks every hash
after it, and the tampering is detected by recomputing the chain.

This module is pure (no I/O) so the integrity logic is trivially testable and so
the exact same hashing runs at write time (engine) and verify time (export/CLI).
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import hashlib
import json

# The chain root. The first record in every org's chain has this as prev_hash.
GENESIS_HASH = "0" * 64


@dataclasses.dataclass(frozen=True, slots=True)
class AuditContent:
    """The hashable content of one audit record (everything except its own hash)."""

    organization_id: str
    chain_index: int
    source_event_id: str
    event_type: str
    actor_type: str
    actor_id: str | None
    resource_type: str | None
    resource_id: str | None
    metadata: dict
    occurred_at: _dt.datetime
    prev_hash: str

    def canonical_bytes(self) -> bytes:
        """Deterministic serialization. Key order and separators are fixed so the
        same content always hashes identically across machines and languages."""
        payload = {
            "organization_id": self.organization_id,
            "chain_index": self.chain_index,
            "source_event_id": self.source_event_id,
            "event_type": self.event_type,
            "actor_type": self.actor_type,
            "actor_id": self.actor_id,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "metadata": self.metadata,
            "occurred_at": self.occurred_at.astimezone(_dt.UTC).isoformat(),
            "prev_hash": self.prev_hash,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def compute_hash(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


@dataclasses.dataclass(frozen=True, slots=True)
class ChainVerification:
    ok: bool
    length: int
    broken_at_index: int | None = None
    reason: str | None = None


def verify_chain(records: list[dict]) -> ChainVerification:
    """Recompute a per-org chain and confirm integrity.

    ``records`` must be ordered by ``chain_index`` ascending. Each item is a dict
    with the audit content fields plus the stored ``record_hash``.
    """
    prev = GENESIS_HASH
    for expected_index, rec in enumerate(records):
        if rec["chain_index"] != expected_index:
            return ChainVerification(False, len(records), expected_index,
                                     f"chain_index gap: expected {expected_index}")
        if rec["prev_hash"] != prev:
            return ChainVerification(False, len(records), expected_index,
                                     "prev_hash does not match previous record_hash")
        content = AuditContent(
            organization_id=rec["organization_id"],
            chain_index=rec["chain_index"],
            source_event_id=rec["source_event_id"],
            event_type=rec["event_type"],
            actor_type=rec["actor_type"],
            actor_id=rec["actor_id"],
            resource_type=rec["resource_type"],
            resource_id=rec["resource_id"],
            metadata=rec["metadata"],
            occurred_at=rec["occurred_at"],
            prev_hash=rec["prev_hash"],
        )
        if content.compute_hash() != rec["record_hash"]:
            return ChainVerification(False, len(records), expected_index,
                                     "record_hash does not match recomputed content")
        prev = rec["record_hash"]
    return ChainVerification(True, len(records))
