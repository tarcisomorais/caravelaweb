"""Real network end-to-end exercise for native Windows.

Not a unittest: a standalone CLI, run once by CI on a real windows-latest
runner. It covers a known Operation plus a bounded Discovery that finalizes,
using the real public CLI entry points against example.com.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
FINALIZER = SKILL / "scripts" / "discovery-finalize"
LOOKUP = SKILL / "scripts" / "knowledge-lookup"
sys.path.insert(0, str(SKILL))

from operational_memory import SQLiteOperationalMemory
from write_authority import MIGRATED_WRITE_AUTHORITY_KIND

TARGET_URL = "https://example.com/"
RECORDED = "2026-08-08T00:00:00Z"


def _lookup(root: Path, target: str, capability: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(LOOKUP), "--knowledge-root", str(root), "--target", target, "--capability", capability],
        text=True, capture_output=True, encoding="utf-8",
    )
    if result.returncode != 0:
        raise AssertionError(f"knowledge-lookup failed: {result.stderr}")
    return json.loads(result.stdout)


def _fetch(url: str) -> tuple[int, str]:
    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 - fixed https URL, evidence exercise only
        body = response.read().decode("utf-8", errors="replace")
        return response.status, body


def setup(root: Path) -> dict:
    (root / ".caravelaweb-knowledge-root").touch()
    (root / "targets").mkdir(parents=True)
    caravela = root / ".caravelaweb"
    caravela.mkdir()
    (caravela / "write-authority.json").write_text(json.dumps({
        "kind": MIGRATED_WRITE_AUTHORITY_KIND, "status": "ACTIVE",
        "previous_write_authority": "LEGACY", "write_authority": "OPERATIONAL_MEMORY",
        "om_authoritative_writes": 0, "first_om_write": "NOT_PERFORMED",
    }), encoding="utf-8")
    (caravela / "read-authority-operational-memory").write_text("active", encoding="utf-8")
    db = caravela / "operational_memory.db"
    with SQLiteOperationalMemory(db, knowledge_root=root) as memory:
        with memory.write_transaction() as writer:
            writer.target({"id": "tgt:example"})
            writer.capability({"id": "cap:example:domain-homepage", "target_id": "tgt:example", "key": "domain-homepage"})
            writer.claim({
                "id": "clm:example:domain-homepage:accepted", "target_id": "tgt:example",
                "capability_id": "cap:example:domain-homepage", "family": "transport",
                "epistemic": "OBSERVED", "value": {"transport": "DIRECT_READ", "outcome": "FUNCTIONAL"},
                "recorded_at": RECORDED,
            })
            writer.decision({
                "id": "dec:example:domain-homepage:accepted", "target_id": "tgt:example",
                "capability_id": "cap:example:domain-homepage", "action": "ACCEPT",
                "claim_ids": ["clm:example:domain-homepage:accepted"], "effective_at": RECORDED,
                "recorded_at": RECORDED, "validity": {"valid_from": RECORDED, "valid_to": None},
            })
    return {"stage": "setup", "root": str(root), "db": str(db)}


def operate(root: Path) -> dict:
    lookup = _lookup(root, "example", "domain-homepage")
    if lookup.get("status") != "found":
        raise AssertionError(f"expected found, got {lookup}")
    started = time.monotonic()
    status, body = _fetch(TARGET_URL)
    elapsed = round(time.monotonic() - started, 3)
    if status != 200 or "Example Domain" not in body:
        raise AssertionError(f"DIRECT_READ Operation did not validate: status={status}")
    return {
        "stage": "operate", "lookup_status": lookup["status"],
        "recorded_transport": lookup["operational_context"]["current"],
        "http_status": status, "content_matched": "Example Domain" in body,
        "elapsed_seconds": elapsed,
    }


def discover(root: Path, payload_path: Path) -> dict:
    before = _lookup(root, "example", "reserved-notice")
    if before.get("status") != "not_found":
        raise AssertionError(f"expected not_found before Discovery, got {before}")
    status, body = _fetch(TARGET_URL)
    if status != 200 or "documentation examples" not in body.lower():
        raise AssertionError(f"real observation did not hold: status={status}")
    observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    payload = {
        "target": "example", "capability": "reserved-notice", "recorded_at": observed_at,
        "provenance": {"run_id": "run:windows-evidence:001", "observed_at": observed_at},
        "evidence": [{"kind": "direct-read-validation", "locator": TARGET_URL}],
        "observations": [{"family": "transport", "value": {"transport": "DIRECT_READ", "outcome": "FUNCTIONAL"}}],
    }
    payload_path.write_text(json.dumps(payload), encoding="utf-8")

    def finalize() -> dict:
        result = subprocess.run(
            [sys.executable, str(FINALIZER), "--knowledge-root", str(root), "--input", str(payload_path)],
            text=True, capture_output=True, encoding="utf-8",
        )
        stream = result.stdout if result.returncode == 0 else result.stderr
        return json.loads(stream)

    first = finalize()
    second = finalize()
    after = _lookup(root, "example", "reserved-notice")
    return {
        "stage": "discover",
        "before_lookup_status": before["status"],
        "first_finalize_status": first["status"],
        "second_finalize_status": second["status"],
        "after_lookup_status": after["status"],
    }


def verify(root: Path) -> dict:
    db = root / ".caravelaweb" / "operational_memory.db"
    with SQLiteOperationalMemory(db, create=False) as memory:
        integrity = memory._conn.execute("PRAGMA integrity_check").fetchone()[0]
        violations = list(memory._conn.execute("PRAGMA foreign_key_check"))
    return {"stage": "verify", "integrity_check": integrity, "foreign_key_violations": len(violations)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("setup", "operate", "discover", "verify"))
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "setup":
        result = setup(args.root)
    elif args.command == "operate":
        result = operate(args.root)
    elif args.command == "discover":
        result = discover(args.root, args.root / "discovery.json")
    else:
        result = verify(args.root)
    print(json.dumps({"platform": sys.platform, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
