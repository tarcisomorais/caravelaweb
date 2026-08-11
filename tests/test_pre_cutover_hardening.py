from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[0]
SKILL = REPO
sys.path.insert(0, str(SKILL))

from integration_bridge import KnowledgeLookupBoundary, default_operational_memory_path
from operational_memory import DatabaseOpenError, SchemaVersionError, SQLiteOperationalMemory

NOW = "2026-08-21T00:00:00Z"


def seed_scope(memory: SQLiteOperationalMemory) -> None:
    with memory.write_transaction() as writer:
        writer.target({"id": "tgt:scope", "name": "Scope"})
        writer.host({"id": "host:scope:a", "target_id": "tgt:scope", "hostname": "a.example"})
        writer.host({"id": "host:scope:b", "target_id": "tgt:scope", "hostname": "b.example"})
        writer.capability({"id": "cap:scope:read", "target_id": "tgt:scope", "key": "read"})


def accept_claim(memory: SQLiteOperationalMemory, claim: dict, suffix: str) -> None:
    with memory.write_transaction() as writer:
        writer.claim(claim)
        writer.decision(
            {
                "id": f"dec:scope:read:20260820T000000Z:{suffix}",
                "target_id": "tgt:scope",
                "capability_id": "cap:scope:read",
                "action": "ACCEPT",
                "claim_ids": [claim["id"]],
                "effective_at": "2026-08-20T00:00:00Z",
                "recorded_at": "2026-08-20T00:00:00Z",
                "validity": {"valid_from": "2026-08-20T00:00:00Z", "valid_to": None},
            }
        )


class Phase35SchemaHostRendererTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_schema_v2_create_reopen_and_v1_rejection(self) -> None:
        db = self.root / "v2.db"
        with SQLiteOperationalMemory(db, clock=lambda: NOW) as memory:
            self.assertEqual(2, memory.schema_version)
            self.assertEqual(
                2,
                memory._conn.execute(
                    "SELECT schema_version FROM schema_metadata WHERE singleton=1"
                ).fetchone()[0],
            )
            self.assertEqual(2, memory._conn.execute("PRAGMA user_version").fetchone()[0])
            self.assertIn(
                "host_id",
                {row[1] for row in memory._conn.execute("PRAGMA table_info(claims)")},
            )
        with SQLiteOperationalMemory(db, clock=lambda: NOW, create=False) as reopened:
            self.assertEqual(2, reopened.schema_version)

        v1 = self.root / "v1.db"
        conn = sqlite3.connect(v1)
        conn.executescript(
            "CREATE TABLE schema_metadata(singleton INTEGER PRIMARY KEY, schema_version INTEGER NOT NULL); "
            "INSERT INTO schema_metadata VALUES(1,1); PRAGMA user_version=1;"
        )
        conn.close()
        with self.assertRaises(SchemaVersionError):
            SQLiteOperationalMemory(v1, create=False)
        conn = sqlite3.connect(v1)
        self.assertEqual(1, conn.execute("PRAGMA user_version").fetchone()[0])
        conn.close()

    def test_corrupt_database_rejected(self) -> None:
        db = self.root / "corrupt.db"
        db.write_bytes(b"not sqlite")
        with self.assertRaises(DatabaseOpenError):
            SQLiteOperationalMemory(db, create=False)

    def test_claim_host_fk_null_and_reopen(self) -> None:
        db = self.root / "scope.db"
        with SQLiteOperationalMemory(db, clock=lambda: NOW) as memory:
            seed_scope(memory)
            accept_claim(
                memory,
                {
                    "id": "clm:scope:read:transport:a",
                    "target_id": "tgt:scope",
                    "capability_id": "cap:scope:read",
                    "host_id": "host:scope:a",
                    "family": "transport",
                    "epistemic": "OBSERVED",
                    "value": "DIRECT_READ",
                    "recorded_at": "2026-08-20T00:00:00Z",
                },
                "a",
            )
            accept_claim(
                memory,
                {
                    "id": "clm:scope:read:unknown:global",
                    "target_id": "tgt:scope",
                    "capability_id": "cap:scope:read",
                    "host_id": None,
                    "family": "unknown",
                    "epistemic": "UNKNOWN",
                    "value": "NOT ESTABLISHED",
                    "recorded_at": "2026-08-20T00:00:00Z",
                },
                "global",
            )
            with self.assertRaises(sqlite3.IntegrityError):
                with memory.write_transaction() as writer:
                    writer.claim(
                        {
                            "id": "clm:scope:read:transport:missing",
                            "target_id": "tgt:scope",
                            "capability_id": "cap:scope:read",
                            "host_id": "host:scope:missing",
                            "family": "transport",
                            "epistemic": "OBSERVED",
                            "value": "CHROME",
                        }
                    )
        with SQLiteOperationalMemory(db, clock=lambda: NOW, create=False) as reopened:
            claims = reopened.get_current("scope", "read")["accepted_claims"]
            by_id = {claim["id"]: claim for claim in claims}
            self.assertEqual("host:scope:a", by_id["clm:scope:read:transport:a"]["host_id"])
            self.assertIsNone(by_id["clm:scope:read:unknown:global"]["host_id"])

    def test_renderer_hosts_are_current_claim_scope_not_validation_history(self) -> None:
        with SQLiteOperationalMemory(self.root / "renderer.db", clock=lambda: NOW) as memory:
            seed_scope(memory)
            with memory.write_transaction() as writer:
                writer.evidence({"id": "ev:scope:a", "recorded_at": "2026-08-19T00:00:00Z"})
                writer.validation(
                    {
                        "id": "val:scope:read:a-current",
                        "capability_id": "cap:scope:read",
                        "host_id": "host:scope:a",
                        "observed_at": "2026-08-19T00:00:00Z",
                        "recorded_at": "2026-08-19T00:00:00Z",
                        "time_precision": "exact",
                        "transport": "DIRECT_READ",
                        "context": {},
                    }
                )
                writer.observation(
                    {
                        "id": "obs:scope:read:a",
                        "validation_id": "val:scope:read:a-current",
                        "result": {"ok": True},
                        "evidence_ids": ["ev:scope:a"],
                    }
                )
                # Historical, unrelated host-b Validation intentionally supports no current Claim.
                writer.validation(
                    {
                        "id": "val:scope:read:b-history",
                        "capability_id": "cap:scope:read",
                        "host_id": "host:scope:b",
                        "observed_at": "2026-08-18T00:00:00Z",
                        "recorded_at": "2026-08-18T00:00:00Z",
                        "time_precision": "exact",
                        "transport": "CHROME",
                        "context": {},
                    }
                )
            accept_claim(
                memory,
                {
                    "id": "clm:scope:read:negative:a",
                    "target_id": "tgt:scope",
                    "capability_id": "cap:scope:read",
                    "host_id": "host:scope:a",
                    "family": "negative",
                    "epistemic": "OBSERVED",
                    "value": {"blocker": "SITE_BLOCKING"},
                    "support_observation_ids": ["obs:scope:read:a"],
                    "recorded_at": "2026-08-20T00:00:00Z",
                },
                "negative",
            )
            accept_claim(
                memory,
                {
                    "id": "clm:scope:read:unknown:a",
                    "target_id": "tgt:scope",
                    "capability_id": "cap:scope:read",
                    "host_id": "host:scope:a",
                    "family": "unknown",
                    "epistemic": "UNKNOWN",
                    "value": "NOT ESTABLISHED",
                    "recorded_at": "2026-08-20T00:00:00Z",
                },
                "unknown",
            )
            context = memory.render_operational_context("scope", "read")
            self.assertEqual(["host:scope:a"], context["hosts"])
            self.assertNotIn("host:scope:b", context["hosts"])
            self.assertEqual(["ev:scope:a"], context["minimal_evidence_refs"])
            self.assertIn("negative", context["current"])
            self.assertEqual("UNKNOWN", context["current"]["unknown"][0]["epistemic"])
            self.assertEqual("host:scope:a", context["current"]["negative"][0]["host_id"])
            self.assertFalse(context["history_included"])
            self.assertNotIn("context_scoped_projection_proven", context)

    def test_two_current_host_scopes_remain_distinguishable(self) -> None:
        with SQLiteOperationalMemory(self.root / "two-hosts.db", clock=lambda: NOW) as memory:
            seed_scope(memory)
            for host, transport in (("a", "DIRECT_READ"), ("b", "CHROME")):
                accept_claim(
                    memory,
                    {
                        "id": f"clm:scope:read:transport:{host}",
                        "target_id": "tgt:scope",
                        "capability_id": "cap:scope:read",
                        "host_id": f"host:scope:{host}",
                        "family": "transport",
                        "epistemic": "OBSERVED",
                        "value": transport,
                        "recorded_at": "2026-08-20T00:00:00Z",
                    },
                    host,
                )
            context = memory.render_operational_context("scope", "read")
            self.assertEqual(["host:scope:a", "host:scope:b"], context["hosts"])
            self.assertEqual(
                {"host:scope:a", "host:scope:b"},
                {item["host_id"] for item in context["current"]["transport"]},
            )


class Phase35LookupOwnershipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "targets").mkdir()
        (self.root / "targets" / "known.md").write_text("# known\n", encoding="utf-8")
        self.script = SKILL / "scripts" / "knowledge-lookup"

    def run_lookup(self, *args: str) -> tuple[int, dict]:
        result = subprocess.run(
            [sys.executable, str(self.script), *args], text=True, capture_output=True
        )
        return result.returncode, json.loads(result.stdout)

    def test_operational_memory_target_only_capability_specific_and_errors(self) -> None:
        db = self.root / "memory.db"
        with SQLiteOperationalMemory(db, clock=lambda: NOW) as memory:
            with memory.write_transaction() as writer:
                writer.target({"id": "tgt:known", "name": "Known"})
                writer.capability(
                    {"id": "cap:known:read", "target_id": "tgt:known", "key": "read"}
                )
                writer.claim(
                    {
                        "id": "clm:known:read:transport:direct",
                        "target_id": "tgt:known",
                        "capability_id": "cap:known:read",
                        "family": "transport",
                        "epistemic": "OBSERVED",
                        "value": "DIRECT_READ",
                        "recorded_at": "2026-08-20T00:00:00Z",
                    }
                )
                writer.decision(
                    {
                        "id": "dec:known:read:20260726T000000Z:01",
                        "target_id": "tgt:known",
                        "capability_id": "cap:known:read",
                        "action": "ACCEPT",
                        "claim_ids": ["clm:known:read:transport:direct"],
                        "effective_at": "2026-07-26T00:00:00Z",
                        "recorded_at": "2026-07-26T00:00:00Z",
                        "validity": {"valid_from": "2026-07-26T00:00:00Z", "valid_to": None},
                    }
                )
        rc, ok = self.run_lookup(
            "--knowledge-root",
            str(self.root),
            "--target",
            "known",
            "--capability",
            "read",
            "--operational-memory-db",
            str(db),
            "--use-operational-memory",
        )
        self.assertEqual((0, "found", "operational-memory"), (rc, ok["status"], ok["source"]))
        self.assertIn("markdown_projection", ok)

        rc, target_only = self.run_lookup(
            "--knowledge-root",
            str(self.root),
            "--target",
            "known",
            "--operational-memory-db",
            str(db),
            "--use-operational-memory",
        )
        self.assertEqual(
            (0, "found", "operational-memory"),
            (rc, target_only["status"], target_only["source"]),
        )
        self.assertIsNone(target_only["capability"])
        self.assertEqual(
            ["read"], sorted(target_only["operational_context"]["capabilities"])
        )

        rc, missing_target = self.run_lookup(
            "--knowledge-root",
            str(self.root),
            "--target",
            "missing",
            "--operational-memory-db",
            str(db),
            "--use-operational-memory",
        )
        self.assertEqual(
            (0, "not_found", "operational-memory"),
            (rc, missing_target["status"], missing_target["source"]),
        )

        for index, args in enumerate((
            (
                "--knowledge-root",
                str(self.root),
                "--target",
                "known",
                "--capability",
                "read",
                "--operational-memory-db",
                str(self.root / "missing.db"),
                "--use-operational-memory",
            ),
            (
                "--knowledge-root",
                str(self.root),
                "--target",
                "known",
                "--capability",
                "missing",
                "--operational-memory-db",
                str(db),
                "--use-operational-memory",
            ),
        )):
            rc, payload = self.run_lookup(*args)
            if index == 0:
                self.assertEqual(2, rc)
                self.assertEqual("bridge_error", payload["status"])
            else:
                self.assertEqual(0, rc)
                self.assertEqual("not_found", payload["status"])
                self.assertEqual("operational-memory", payload["source"])

        v1 = self.root / "v1.db"
        conn = sqlite3.connect(v1)
        conn.executescript(
            "CREATE TABLE schema_metadata(singleton INTEGER PRIMARY KEY, schema_version INTEGER NOT NULL); "
            "INSERT INTO schema_metadata VALUES(1,1); PRAGMA user_version=1;"
        )
        conn.close()
        rc, payload = self.run_lookup(
            "--knowledge-root",
            str(self.root),
            "--target",
            "known",
            "--capability",
            "read",
            "--operational-memory-db",
            str(v1),
            "--use-operational-memory",
        )
        self.assertEqual((2, "bridge_error"), (rc, payload["status"]))

    def test_lookup_normalizes_profile_capability_underscores(self) -> None:
        db = self.root / "normalized.db"
        recorded = "2026-07-20T00:00:00Z"
        with SQLiteOperationalMemory(db, clock=lambda: recorded) as memory:
            with memory.write_transaction() as writer:
                writer.target({"id": "tgt:example-listings", "name": "Example Listings"})
                writer.capability({"id": "cap:example-listings:project-listings", "target_id": "tgt:example-listings", "key": "project-listings"})
                writer.claim({"id": "clm:example-listings:project-listings:transport", "target_id": "tgt:example-listings", "capability_id": "cap:example-listings:project-listings", "family": "transport", "epistemic": "OBSERVED", "value": "DIRECT_READ", "recorded_at": recorded})
                writer.decision({"id": "dec:example-listings:project-listings", "target_id": "tgt:example-listings", "capability_id": "cap:example-listings:project-listings", "action": "ACCEPT", "claim_ids": ["clm:example-listings:project-listings:transport"], "effective_at": recorded, "recorded_at": recorded, "validity": {"valid_from": recorded, "valid_to": None}})
        result = KnowledgeLookupBoundary(self.root, db).lookup(
            "example-listings", capability="project_listings", use_operational_memory=True
        )
        self.assertEqual("project-listings", result.capability)
        self.assertIsNotNone(result.operational_context)

    def test_public_surface_and_state_protection(self) -> None:
        self.assertEqual(
            self.root / ".caravelaweb" / "operational_memory.db",
            default_operational_memory_path(self.root),
        )
        skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("scripts/knowledge-lookup --target <target-id> --capability <capability>", skill)
        self.assertNotIn("--use-legacy", skill)
        self.assertNotIn("--capture-candidate-from", skill)
        self.assertNotIn("--promote-candidate", skill)
        ignore = (REPO / ".gitignore").read_text(encoding="utf-8")
        for pattern in (
            ".caravelaweb/*.db",
            ".caravelaweb/*.db-wal",
            ".caravelaweb/*.db-shm",
            ".caravelaweb/*.db-journal",
        ):
            self.assertIn(pattern, ignore)

    def test_knowledge_root_corpus_is_never_a_repository_artifact(self) -> None:
        """A checkout used as a Knowledge Root gains a targets/ corpus directory.

        That corpus is installation-owned state, so committing it would publish
        someone's operating knowledge. The rule is anchored to the repository
        root, which keeps repo-level targets/ unshippable without claiming
        anything about a Knowledge Root kept elsewhere on disk.
        """
        ignore = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("/targets/", ignore)

        completed = subprocess.run(
            ["git", "-C", str(REPO), "check-ignore", "-q", "targets/example-target.md"],
            capture_output=True,
        )
        if completed.returncode == 128:
            self.skipTest("not a git checkout")
        self.assertEqual(0, completed.returncode, "repo-level targets/ is not ignored")


if __name__ == "__main__":
    unittest.main(verbosity=2)
