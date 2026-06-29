"""Audit CLI — per-organization export and integrity verification.

    python -m touchstone_audit.cli export --org <uuid>   # full chain as JSON
    python -m touchstone_audit.cli verify --org <uuid>   # recompute + check chain

Export emits the org's complete, ordered audit chain as JSON (suitable for
handing to a customer or auditor). Verify recomputes the hash chain and reports
whether it is intact, exiting non-zero if tampering is detected.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import json
import sys
import uuid

from sqlalchemy.ext.asyncio import create_async_engine

from .chain import verify_chain
from .config import get_settings
from .repository import Repository


def _json_default(o: object) -> str:
    if isinstance(o, _dt.datetime):
        return o.astimezone(_dt.UTC).isoformat()
    return str(o)


async def _export(org: uuid.UUID) -> int:
    engine = create_async_engine(str(get_settings().database_url))
    repo = Repository(engine)
    records = await repo.export_org(org)
    await engine.dispose()
    print(json.dumps(records, indent=2, default=_json_default))
    return 0


async def _verify(org: uuid.UUID) -> int:
    engine = create_async_engine(str(get_settings().database_url))
    repo = Repository(engine)
    records = await repo.export_org(org)
    await engine.dispose()
    result = verify_chain(records)
    if result.ok:
        print(f"OK: chain intact ({result.length} records) for org {org}")
        return 0
    print(
        f"BROKEN: chain failed at index {result.broken_at_index} "
        f"({result.reason}) for org {org}",
        file=sys.stderr,
    )
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="touchstone-audit")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("export", "verify"):
        sp = sub.add_parser(name)
        sp.add_argument("--org", required=True, type=uuid.UUID, help="organization UUID")
    args = parser.parse_args(argv)
    if args.cmd == "export":
        return asyncio.run(_export(args.org))
    return asyncio.run(_verify(args.org))


if __name__ == "__main__":
    raise SystemExit(main())
