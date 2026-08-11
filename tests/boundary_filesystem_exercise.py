"""Bounded cross-process SQLite integrity exercise for a shared root."""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))

from operational_memory import SQLiteOperationalMemory


def initialize(db: Path) -> dict[str, object]:
    with SQLiteOperationalMemory(db) as memory:
        with memory.write_transaction() as writer:
            writer.target({"id": "tgt:boundary", "name": "Boundary exercise"})
    return {"initialized": str(db)}


def write(db: Path, writer_name: str, count: int, hold_ms: int) -> dict[str, object]:
    started = time.monotonic()
    with SQLiteOperationalMemory(db, create=False) as memory:
        for sequence in range(count):
            with memory.write_transaction() as transaction:
                transaction.evidence(
                    {"id": f"ev:{writer_name}:{sequence:04d}", "writer": writer_name}
                )
                time.sleep(hold_ms / 1000)
    return {
        "writer": writer_name,
        "writes": count,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def verify(db: Path, expected: int) -> dict[str, object]:
    with SQLiteOperationalMemory(db, create=False) as memory:
        integrity = memory._conn.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = list(memory._conn.execute("PRAGMA foreign_key_check"))
        rows = memory._conn.execute("SELECT payload_json FROM evidence").fetchall()
        total = memory._conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
    writers: dict[str, int] = {}
    for row in rows:
        name = json.loads(row[0])["writer"]
        writers[name] = writers.get(name, 0) + 1
    result = {
        "integrity_check": integrity,
        "foreign_key_violations": len(foreign_keys),
        "total_writes": total,
        "writers": dict(sorted(writers.items())),
        "expected_writes": expected,
    }
    if integrity != "ok" or foreign_keys or total != expected:
        raise AssertionError(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("initialize", "write", "verify"))
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--writer")
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--hold-ms", type=int, default=2)
    parser.add_argument("--expected", type=int, default=200)
    args = parser.parse_args()
    if args.command == "initialize":
        result = initialize(args.db)
    elif args.command == "write":
        if not args.writer:
            parser.error("write requires --writer")
        result = write(args.db, args.writer, args.count, args.hold_ms)
    else:
        result = verify(args.db, args.expected)
    print(
        json.dumps(
            {
                "platform": sys.platform,
                "python": platform.python_version(),
                **result,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
