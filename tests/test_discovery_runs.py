from __future__ import annotations

import json
import io
import os
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stderr
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
BEGIN = REPO / "scripts" / "discovery-begin"
FINALIZER = REPO / "scripts" / "discovery-finalize"
LOOKUP = REPO / "scripts" / "knowledge-lookup"
PREFLIGHT = REPO / "scripts" / "preflight"
sys.path.insert(0, str(REPO))

from discovery_runs import (
    DiscoveryRunError,
    _marker,
    begin_discovery,
    list_open_discoveries,
    require_open_discovery,
)
from operational_memory import SQLiteOperationalMemory
from write_authority import MIGRATED_WRITE_AUTHORITY_KIND

RECORDED = "2026-08-13T19:02:11Z"


class DiscoveryRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / ".caravelaweb-knowledge-root").write_text("\n", encoding="utf-8")
        (self.root / "targets").mkdir()
        state = self.root / ".caravelaweb"
        state.mkdir()
        with SQLiteOperationalMemory(state / "operational_memory.db"):
            pass
        (state / "read-authority-operational-memory").write_text("active\n", encoding="utf-8")
        (state / "write-authority.json").write_text(json.dumps({
            "kind": MIGRATED_WRITE_AUTHORITY_KIND, "status": "ACTIVE",
            "write_authority": "OPERATIONAL_MEMORY",
            "previous_write_authority": "LEGACY",
            "om_authoritative_writes": 0, "first_om_write": "NOT_PERFORMED",
        }), encoding="utf-8")

    def run_cli(self, script: Path, *args: str, input: str | None = None):
        return subprocess.run(
            [sys.executable, str(script), "--knowledge-root", str(self.root), *args],
            input=input, text=True, capture_output=True, encoding="utf-8",
        )

    def begin(self, target="example-news", capability="topic-search"):
        result = self.run_cli(BEGIN, "--target", target, "--capability", capability)
        self.assertEqual(0, result.returncode, result.stderr)
        return json.loads(result.stdout)

    def payload(self, opened, *, observations=None):
        return {
            "target": opened["target"], "capability": opened["capability"],
            "observations": observations if observations is not None else [{
                "family": "transport",
                "value": {"transport": "DIRECT_READ", "outcome": "FUNCTIONAL"},
            }],
            "evidence": [{"kind": "direct-read-validation", "locator": "https://example.com/"}],
            "provenance": {"run_id": opened["run_id"], "observed_at": RECORDED},
            "recorded_at": RECORDED,
        }

    def finalize(self, payload):
        return self.run_cli(FINALIZER, input=json.dumps(payload))

    def test_begin_creates_distinct_run_scoped_windows_safe_markers(self):
        first = self.begin()
        second = self.begin()
        self.assertNotEqual(first["run_id"], second["run_id"])
        self.assertEqual(2, len(list_open_discoveries(self.root)))
        names = [path.name for path in (self.root / ".caravelaweb/open-discovery").iterdir()]
        self.assertTrue(all(name.endswith(".json") and ":" not in name for name in names))

    def test_saved_and_honest_empty_results_close_only_their_run(self):
        saved = self.begin("saved-target")
        empty = self.begin("empty-target")
        other = self.begin("other-target")
        saved_result = self.finalize(self.payload(saved))
        self.assertEqual("SAVED", json.loads(saved_result.stdout)["status"])
        empty_result = self.finalize(self.payload(empty, observations=[]))
        self.assertEqual("NO_REUSABLE_KNOWLEDGE", json.loads(empty_result.stdout)["reason_code"])
        self.assertEqual([other["run_id"]], [item["run_id"] for item in list_open_discoveries(self.root)])

    def test_invalid_payload_remains_open_but_a_not_saved_verdict_closes(self):
        invalid = self.begin("invalid-target")
        invalid_payload = self.payload(invalid)
        invalid_payload["observations"] = [{"family": "prices", "value": {"state": "BAD"}}]
        refused = self.finalize(invalid_payload)
        self.assertEqual(2, refused.returncode)
        pending = self.begin("pending-target")
        pending_result = self.finalize(self.payload(pending, observations=[{
            "family": "extraction", "epistemic": "INFERRED",
            "value": {"structure": "JSON_LD"},
        }]))
        self.assertEqual(0, pending_result.returncode, pending_result.stderr)
        self.assertEqual("INFERENCE_ONLY", json.loads(pending_result.stdout)["reason_code"])
        self.assertEqual(
            {invalid["run_id"]},
            {item["run_id"] for item in list_open_discoveries(self.root)},
        )

    def test_hostname_finalization_matches_and_closes_the_canonical_run(self):
        with SQLiteOperationalMemory(
            self.root / ".caravelaweb/operational_memory.db", create=False
        ) as memory, memory.write_transaction() as writer:
            writer.target({"id": "tgt:hostname-target"})
            writer.host({
                "id": "host:hostname-target:www", "target_id": "tgt:hostname-target",
                "hostname": "www.example.com",
            })
        opened = self.begin("hostname-target", "article-read")
        payload = self.payload(opened, observations=[])
        payload["target"] = "https://www.example.com/articles"
        result = self.finalize(payload)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("hostname-target", json.loads(result.stdout)["target"])
        self.assertEqual([], list_open_discoveries(self.root))

    def test_missing_or_mismatched_run_is_rejected_before_memory_writes(self):
        opened = self.begin("first-target")
        missing = self.payload({**opened, "run_id": "run:missing"})
        mismatch = self.payload(opened)
        mismatch["target"] = "second-target"
        for payload in (missing, mismatch):
            with self.subTest(payload=payload):
                result = self.finalize(payload)
                self.assertEqual(2, result.returncode)
        with SQLiteOperationalMemory(
            self.root / ".caravelaweb/operational_memory.db", create=False
        ) as memory:
            self.assertEqual(0, memory._conn.execute("SELECT count(*) FROM proposals").fetchone()[0])

    def test_lookup_and_preflight_expose_open_runs_without_operation_debt(self):
        operation = self.run_cli(LOOKUP, "--target", "operation-target", "--capability", "read")
        self.assertEqual(0, operation.returncode, operation.stderr)
        self.assertNotIn("open_discovery", json.loads(operation.stdout))
        opened = self.begin("visible-target", "article-read")
        lookup = self.run_cli(LOOKUP, "--target", "visible-target", "--capability", "article-read")
        self.assertEqual([opened["run_id"]], [
            item["run_id"] for item in json.loads(lookup.stdout)["open_discovery"]
        ])
        preflight = self.run_cli(PREFLIGHT, "--json")
        self.assertEqual([opened["run_id"]], [
            item["run_id"] for item in json.loads(preflight.stdout)["open_discovery"]
        ])

    def test_begin_storage_failure_blocks_but_lookup_remains_read_only(self):
        marker_path = self.root / ".caravelaweb/open-discovery"
        marker_path.write_text("not a directory", encoding="utf-8")
        begun = self.run_cli(BEGIN, "--target", "blocked-target", "--capability", "read")
        self.assertEqual(2, begun.returncode)
        self.assertEqual("NOT_OPEN", json.loads(begun.stderr)["status"])
        lookup = self.run_cli(LOOKUP, "--target", "blocked-target", "--capability", "read")
        self.assertEqual(0, lookup.returncode, lookup.stderr)
        self.assertEqual("not_found", json.loads(lookup.stdout)["status"])

    def test_run_id_is_not_candidate_identity(self):
        first = begin_discovery(
            self.root, "candidate-target", "article-read",
            run_id="run:first", opened_at=RECORDED,
        )
        payload = self.payload(first, observations=[{
            "family": "extraction", "epistemic": "INFERRED",
            "value": {"structure": "JSON_LD"},
        }])
        initial = self.finalize(payload)
        self.assertEqual("INFERENCE_ONLY", json.loads(initial.stdout)["reason_code"])
        self.assertEqual([], list_open_discoveries(self.root))
        with SQLiteOperationalMemory(
            self.root / ".caravelaweb/operational_memory.db", create=False
        ) as memory:
            initial_proposal = memory._conn.execute("SELECT id FROM proposals").fetchone()[0]
        second = begin_discovery(
            self.root, "candidate-target", "article-read",
            run_id="run:second", opened_at=RECORDED,
        )
        payload["provenance"]["run_id"] = second["run_id"]
        payload["observations"][0]["validation"] = {
            "transport": "DIRECT_READ", "outcome": "OBSERVED",
            "engine": None, "javascript": False,
            "context": {"authentication": "PUBLIC", "environment": "PRODUCTION"},
            "evidence": ["https://example.com/"],
        }
        enriched = self.finalize(payload)
        self.assertEqual("INFERENCE_ONLY", json.loads(enriched.stdout)["reason_code"])
        self.assertEqual([], list_open_discoveries(self.root))
        with SQLiteOperationalMemory(
            self.root / ".caravelaweb/operational_memory.db", create=False
        ) as memory:
            self.assertEqual(1, memory._conn.execute("SELECT count(*) FROM proposals").fetchone()[0])
            self.assertEqual(initial_proposal, memory._conn.execute("SELECT id FROM proposals").fetchone()[0])
            self.assertEqual(1, memory._conn.execute("SELECT count(*) FROM evidence").fetchone()[0])

    def test_abandoned_retryable_run_stays_visible_to_lookup_and_preflight(self):
        # Documents current behavior: an abandoned retryable/invalid run's
        # marker is not expired or cleaned up automatically -- it remains
        # open and visible until a caller retries or explicitly abandons it.
        opened = self.begin("abandoned-target", "article-read")
        payload = self.payload(opened, observations=[{
            "family": "transport",
            "value": {"transport": "DIRECT_READ", "outcome": "FAILED"},
        }])
        payload["transport_trace"] = {
            "availability": {"LIGHTPANDA": "AVAILABLE", "CHROME": "AVAILABLE"},
            "attempts": [{
                "transport": "DIRECT_READ", "outcome": "FAILED",
                "evidence": ["https://example.com/"],
            }],
        }
        result = self.finalize(payload)
        self.assertEqual(0, result.returncode, result.stderr)
        body = json.loads(result.stdout)
        self.assertEqual("TRANSPORT_POLICY_UNPROVEN", body["reason_code"])
        self.assertEqual("OPEN", body["run_state"])
        self.assertEqual([opened["run_id"]], [
            item["run_id"] for item in list_open_discoveries(self.root)
        ])
        lookup = self.run_cli(LOOKUP, "--target", "abandoned-target", "--capability", "article-read")
        self.assertEqual([opened["run_id"]], [
            item["run_id"] for item in json.loads(lookup.stdout)["open_discovery"]
        ])
        preflight = self.run_cli(PREFLIGHT, "--json")
        self.assertIn(opened["run_id"], [
            item["run_id"] for item in json.loads(preflight.stdout)["open_discovery"]
        ])

    def test_close_failure_stays_open_and_already_exists_retry_closes_it(self):
        opened = self.begin("retry-target")
        payload = self.payload(opened)
        api = runpy.run_path(str(FINALIZER))
        stderr = io.StringIO()
        with patch.object(
            sys, "argv", [
                str(FINALIZER), "--knowledge-root", str(self.root), "--input", "-",
            ]
        ), patch.object(
            sys, "stdin", io.StringIO(json.dumps(payload))
        ), patch.dict(
            api["main"].__globals__, {"close_discovery": lambda *args: (_ for _ in ()).throw(
                DiscoveryRunError("Discovery finalized, but its open marker could not be closed")
            )}
        ), redirect_stderr(stderr):
            result = api["main"]()
        self.assertEqual(2, result)
        self.assertEqual("FINALIZATION_INCOMPLETE", json.loads(stderr.getvalue())["status"])
        self.assertEqual([opened["run_id"]], [
            item["run_id"] for item in list_open_discoveries(self.root)
        ])
        retried = self.finalize(payload)
        self.assertEqual(0, retried.returncode, retried.stderr)
        self.assertEqual("ALREADY_EXISTS", json.loads(retried.stdout)["status"])
        self.assertEqual([], list_open_discoveries(self.root))

    def test_symlinked_run_marker_is_refused(self) -> None:
        opened = self.begin("symlink-target")
        marker = _marker(self.root, opened["run_id"])
        real = self.root / "elsewhere-marker.json"
        marker.replace(real)
        try:
            os.symlink(real, marker)
        except OSError as exc:
            self.skipTest(f"cannot create a symlink on this platform: {exc}")
        with self.assertRaises(DiscoveryRunError):
            require_open_discovery(self.root, opened["target"], opened["capability"], opened["run_id"])
        records = list_open_discoveries(self.root)
        self.assertEqual([{"status": "INVALID", "marker": marker.name}], records)


if __name__ == "__main__":
    unittest.main()
