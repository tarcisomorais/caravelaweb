"""`CARAVELAWEB_LEARNING=disabled`: no public command writes to the Knowledge Root.

A caller that starts CaravelaWeb with learning disabled relies on four
promises: every write path refuses with the `LEARNING_DISABLED` reason code,
the store's bytes stay unchanged, lookup and preflight keep answering `READY`
and say `learning: DISABLED`, and nothing changes when the variable is unset.
The last test inventories every write primitive in the public runtime, so a
new write path cannot appear without someone deciding whether it needs the
gate.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
BEGIN = SCRIPTS / "discovery-begin"
FINALIZER = SCRIPTS / "discovery-finalize"
RESOLVE = SCRIPTS / "knowledge-resolve"
INIT = SCRIPTS / "init-knowledge-root"
LOOKUP = SCRIPTS / "knowledge-lookup"
PREFLIGHT = SCRIPTS / "preflight"
sys.path.insert(0, str(REPO))

from discovery_runs import DiscoveryRunError, begin_discovery, close_discovery
from installation_init import initialize_knowledge_root
from knowledge_write_freeze import enable_freeze
from operational_memory import SQLiteOperationalMemory
from platform_adapter import (
    KNOWLEDGE_ROOT_ENV,
    LEARNING_DISABLED,
    LEARNING_ENV,
    LearningDisabledError,
    learning_mode,
    unrecognized_learning_value,
)

RECORDED = "2026-08-13T19:02:11Z"
PROPOSAL = "prop:example-news:topic-search:candidate"


def tree_hash(root: Path) -> str:
    """One digest over every file's relative path and bytes under ``root``."""
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


class LearningDisabledTests(unittest.TestCase):
    def setUp(self) -> None:
        # This module must pass whatever the developer's shell exports.
        environment = patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.pop(LEARNING_ENV, None)
        os.environ.pop(KNOWLEDGE_ROOT_ENV, None)

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "root"
        initialized = self.run_cli(INIT, "--json", learning=None)
        self.assertEqual(0, initialized.returncode, initialized.stderr)
        self.assertEqual("INITIALIZED", json.loads(initialized.stdout)["status"])
        self.db = self.root / ".caravelaweb" / "operational_memory.db"

    def run_cli(self, script: Path, *args: str, learning: str | None, input: str | None = None):
        env = {k: v for k, v in os.environ.items() if k not in {LEARNING_ENV, KNOWLEDGE_ROOT_ENV}}
        if learning is not None:
            env[LEARNING_ENV] = learning
        return subprocess.run(
            [sys.executable, str(script), "--knowledge-root", str(self.root), *args],
            input=input, text=True, capture_output=True, encoding="utf-8", env=env,
        )

    def assert_learning_refusal(self, result, status: str, *, stream: str = "stderr") -> dict:
        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        payload = json.loads(getattr(result, stream))
        self.assertEqual(status, payload["status"])
        self.assertEqual(LEARNING_DISABLED, payload["reason_code"])
        self.assertIn(LEARNING_ENV, payload["reason"])
        return payload

    def open_run(self) -> dict:
        opened = self.run_cli(
            BEGIN, "--target", "example-news", "--capability", "topic-search", learning=None,
        )
        self.assertEqual(0, opened.returncode, opened.stderr)
        return json.loads(opened.stdout)

    def payload(self, opened: dict, *, observations: list | None = None) -> str:
        return json.dumps({
            "target": opened["target"], "capability": opened["capability"],
            "observations": observations if observations is not None else [{
                "family": "transport",
                "value": {"transport": "DIRECT_READ", "outcome": "FUNCTIONAL"},
            }],
            "evidence": [{"kind": "direct-read-validation", "locator": "https://example.com/"}],
            # Observed at the instant `discovery-begin` opened the run, so the
            # control finalize falls inside the run window.
            "provenance": {"run_id": opened["run_id"], "observed_at": opened["opened_at"]},
        })

    def open_markers(self) -> list[Path]:
        directory = self.root / ".caravelaweb" / "open-discovery"
        return sorted(directory.glob("*.json")) if directory.exists() else []

    # Case 1
    def test_the_value_is_read_case_insensitively_and_only_disabled_disables(self) -> None:
        for value in (None, "", "enabled", "ENABLED", "off", "0", "no"):
            environ = {} if value is None else {LEARNING_ENV: value}
            self.assertEqual("ENABLED", learning_mode(environ), value)
        for value in ("disabled", " Disabled ", "DISABLED\n"):
            self.assertEqual("DISABLED", learning_mode({LEARNING_ENV: value}), value)
        self.assertIsNone(unrecognized_learning_value({}))
        self.assertIsNone(unrecognized_learning_value({LEARNING_ENV: "  "}))
        self.assertIsNone(unrecognized_learning_value({LEARNING_ENV: " Enabled "}))
        self.assertIsNone(unrecognized_learning_value({LEARNING_ENV: "disabled"}))
        self.assertEqual("off", unrecognized_learning_value({LEARNING_ENV: "off"}))

    # Case 2
    def test_discovery_begin_refuses_and_opens_no_run(self) -> None:
        before = tree_hash(self.root)
        result = self.run_cli(
            BEGIN, "--target", "example-news", "--capability", "topic-search", learning="disabled",
        )
        self.assert_learning_refusal(result, "NOT_OPEN")
        self.assertEqual([], self.open_markers())
        self.assertEqual(before, tree_hash(self.root))

    # Case 3
    def test_discovery_finalize_refuses_every_payload_and_leaves_the_run_open(self) -> None:
        opened = self.open_run()
        control = self.run_cli(
            FINALIZER, "--validate", learning=None, input=self.payload(opened),
        )
        self.assertEqual(0, control.returncode, control.stderr)
        self.assertEqual("SAVED", json.loads(control.stdout)["would_finalize_as"])
        markers = self.open_markers()
        self.assertEqual(1, len(markers))
        before = tree_hash(self.root)

        for args, observations in (((), None), ((), []), (("--validate",), None)):
            with self.subTest(args=args, observations=observations):
                result = self.run_cli(
                    FINALIZER, *args, learning="disabled",
                    input=self.payload(opened, observations=observations),
                )
                refusal = self.assert_learning_refusal(result, "NOT_SAVED")
                self.assertEqual("OPEN", refusal["run_state"])
                self.assertEqual(markers, self.open_markers())
                self.assertEqual(before, tree_hash(self.root))

    # Case 4
    def test_knowledge_resolve_refuses_to_reject_a_pending_candidate(self) -> None:
        with SQLiteOperationalMemory(self.db, create=False, knowledge_root=self.root) as memory:
            with memory.write_transaction() as writer:
                writer.target({"id": "tgt:example-news", "name": "Example News"})
                writer.capability({
                    "id": "cap:example-news:topic-search",
                    "target_id": "tgt:example-news",
                    "key": "topic-search",
                })
                writer.claim({
                    "id": "clm:example-news:topic-search:blocking:candidate",
                    "target_id": "tgt:example-news",
                    "capability_id": "cap:example-news:topic-search",
                    "family": "blocking",
                    "epistemic": "OBSERVED",
                    "value": {"blocking": True},
                    "proposal_id": PROPOSAL,
                    "recorded_at": RECORDED,
                })
                writer.proposal({
                    "id": PROPOSAL,
                    "target_id": "tgt:example-news",
                    "capability_id": "cap:example-news:topic-search",
                    "claim_ids": ["clm:example-news:topic-search:blocking:candidate"],
                    "recorded_at": RECORDED,
                })
        before = tree_hash(self.root)
        result = self.run_cli(
            RESOLVE, "--target", "example-news", "--capability", "topic-search",
            "--reject-pending", PROPOSAL, "--reason", "stale", learning="disabled",
        )
        self.assert_learning_refusal(result, "NOT_REJECTED")
        self.assertEqual(before, tree_hash(self.root))

    # Case 5
    def test_root_creation_is_refused_and_creates_nothing(self) -> None:
        target = Path(self.temp.name) / "second-root"
        env = {k: v for k, v in os.environ.items() if k != KNOWLEDGE_ROOT_ENV}
        env[LEARNING_ENV] = "disabled"
        as_json = subprocess.run(
            [sys.executable, str(INIT), "--json", "--knowledge-root", str(target)],
            text=True, capture_output=True, encoding="utf-8", env=env,
        )
        self.assert_learning_refusal(as_json, "REFUSED", stream="stdout")
        as_text = subprocess.run(
            [sys.executable, str(INIT), "--knowledge-root", str(target)],
            text=True, capture_output=True, encoding="utf-8", env=env,
        )
        self.assertEqual(2, as_text.returncode)
        self.assertIn("status: REFUSED", as_text.stdout)
        self.assertIn(f"reason_code: {LEARNING_DISABLED}", as_text.stdout)
        self.assertFalse(target.exists())

    # Case 6
    def test_every_library_write_path_refuses(self) -> None:
        opened = self.open_run()
        fresh_db = Path(self.temp.name) / "fresh" / "operational_memory.db"
        with patch.dict(os.environ, {LEARNING_ENV: "disabled"}):
            with self.assertRaises(DiscoveryRunError) as begun:
                begin_discovery(self.root, "example-news", "topic-search")
            self.assertIsInstance(begun.exception.__cause__, LearningDisabledError)
            with self.assertRaises(DiscoveryRunError) as closed:
                close_discovery(self.root, opened["target"], opened["capability"], opened["run_id"])
            self.assertIsInstance(closed.exception.__cause__, LearningDisabledError)
            with self.assertRaises(LearningDisabledError):
                SQLiteOperationalMemory(fresh_db, create=True)
            self.assertFalse(fresh_db.parent.exists())
            with self.assertRaises(LearningDisabledError):
                initialize_knowledge_root(Path(self.temp.name) / "library-root")
            self.assertFalse((Path(self.temp.name) / "library-root").exists())
            # Reading an existing database is not a write and stays allowed.
            with SQLiteOperationalMemory(self.db, knowledge_root=self.root) as memory:
                with self.assertRaises(LearningDisabledError):
                    with memory.write_transaction():
                        pass
        self.assertEqual(1, len(self.open_markers()))

    def test_learning_refusal_wins_over_an_active_freeze(self) -> None:
        enable_freeze(self.root, reason="maintenance")
        with patch.dict(os.environ, {LEARNING_ENV: "disabled"}):
            with SQLiteOperationalMemory(self.db, knowledge_root=self.root) as memory:
                with self.assertRaises(LearningDisabledError):
                    with memory.write_transaction():
                        pass

    # Case 7
    def test_lookup_and_preflight_stay_ready_and_report_disabled(self) -> None:
        before = tree_hash(self.root)
        lookup = self.run_cli(
            LOOKUP, "--target", "example.com", "--capability", "page-read", learning="disabled",
        )
        self.assertEqual(0, lookup.returncode, lookup.stderr)
        answer = json.loads(lookup.stdout)
        self.assertEqual("not_found", answer["status"])
        self.assertEqual("READY", answer["readiness"])
        self.assertEqual("DISABLED", answer["learning"])
        listed = self.run_cli(LOOKUP, "--list", learning="disabled")
        self.assertEqual("DISABLED", json.loads(listed.stdout)["learning"])

        preflight = self.run_cli(PREFLIGHT, "--json", learning="disabled")
        self.assertEqual(0, preflight.returncode, preflight.stdout)
        report = json.loads(preflight.stdout)
        self.assertEqual("READY", report["status"])
        self.assertEqual("DISABLED", report["learning"])
        self.assertEqual([], report["errors"])
        text = self.run_cli(PREFLIGHT, learning="disabled")
        self.assertIn("learning: DISABLED", text.stdout)
        self.assertEqual(before, tree_hash(self.root))

    # Case 8
    def test_learning_enabled_output_is_unchanged(self) -> None:
        args = ("--target", "example.com", "--capability", "page-read")
        unset = self.run_cli(LOOKUP, *args, learning=None)
        enabled = self.run_cli(LOOKUP, *args, learning="enabled")
        self.assertEqual(unset.stdout, enabled.stdout)
        self.assertNotIn("learning", json.loads(unset.stdout))

        report = json.loads(self.run_cli(PREFLIGHT, "--json", learning=None).stdout)
        self.assertEqual(("READY", "ENABLED"), (report["status"], report["learning"]))
        self.assertFalse(any(LEARNING_ENV in warning for warning in report["warnings"]))
        typo = self.run_cli(PREFLIGHT, "--json", learning="off")
        self.assertEqual(0, typo.returncode)
        report = json.loads(typo.stdout)
        self.assertEqual(("READY", "ENABLED"), (report["status"], report["learning"]))
        self.assertIn(
            f"{LEARNING_ENV}=off is not recognized; learning is ENABLED", report["warnings"],
        )


# Case 9. Every write primitive in the public runtime, by enclosing function.
RUNTIME_SOURCES = [
    "discovery_finalize.py", "discovery_runs.py", "installation_init.py",
    "integration_bridge.py", "knowledge_write_freeze.py", "om_native_writes.py",
    "operational_memory/__init__.py", "operational_memory/core.py",
    "platform_adapter.py", "read_authority.py", "readiness.py",
    "transport_policy.py", "write_authority.py",
]
# Each entry is gated by assert_learning_enabled, or says why it needs no gate.
KNOWN_WRITERS = {
    ("discovery_runs.py", "begin_discovery"): "gated",
    ("discovery_runs.py", "close_discovery"): "gated",
    ("installation_init.py", "initialize_knowledge_root"): "gated",
    ("installation_init.py", "_write_new_marker"): "only called by initialize_knowledge_root",
    ("operational_memory/core.py", "SQLiteOperationalMemory._open"): "gated on creation",
    ("operational_memory/core.py", "SQLiteOperationalMemory.write_transaction"): "gated",
    ("knowledge_write_freeze.py", "enable_freeze"): "maintenance only; no public command",
    ("knowledge_write_freeze.py", "disable_freeze"): "maintenance only; no public command",
    ("write_authority.py", "authority_lock"): "maintenance lock; no runtime caller",
}
# Read-only descriptor opens that the scan cannot tell apart from writes.
READ_ONLY_OPENS = {
    ("discovery_runs.py", "_open_marker"),
    ("write_authority.py", "_read_marker"),
}
WRITE_ATTRIBUTES = {
    "write_text", "write_bytes", "unlink", "mkdir", "rmdir", "touch",
    "rename", "executescript", "symlink_to", "hardlink_to",
}
WRITE_SQL = {"INSERT", "UPDATE", "DELETE", "BEGIN", "CREATE", "DROP", "REPLACE", "ALTER"}


def _write_primitive(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Attribute):
        owner = func.value.id if isinstance(func.value, ast.Name) else None
        if func.attr in WRITE_ATTRIBUTES:
            return func.attr
        if func.attr in {"replace", "open"} and owner == "os":
            return f"os.{func.attr}"
        if func.attr == "open":
            mode = next((a.value for a in call.args[:1] if isinstance(a, ast.Constant)), None)
            mode = next((k.value.value for k in call.keywords if k.arg == "mode"), mode)
            if isinstance(mode, str) and set(mode) & set("wax+"):
                return f"open({mode})"
        if func.attr == "execute" and call.args and isinstance(call.args[0], ast.Constant):
            sql = str(call.args[0].value).strip().split(maxsplit=1)
            if sql and sql[0].upper() in WRITE_SQL:
                return f"execute({sql[0].upper()})"
    if isinstance(func, ast.Name) and func.id == "open":
        mode = next((a.value for a in call.args[1:2] if isinstance(a, ast.Constant)), None)
        mode = next((k.value.value for k in call.keywords if k.arg == "mode"), mode)
        if isinstance(mode, str) and set(mode) & set("wax+"):
            return f"open({mode})"
    return None


def _writes(source: Path) -> list[tuple[str, str, int]]:
    found: list[tuple[str, str, int]] = []

    def visit(node: ast.AST, scope: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            inner = scope
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                inner = [*scope, child.name]
            if isinstance(child, ast.Call) and (primitive := _write_primitive(child)):
                found.append((".".join(scope) or "<module>", primitive, child.lineno))
            visit(child, inner)

    visit(ast.parse(source.read_text(encoding="utf-8"), str(source)), [])
    return found


class WritePathInventoryTests(unittest.TestCase):
    def test_every_runtime_write_is_gated_or_explained(self) -> None:
        sources = [REPO / name for name in RUNTIME_SOURCES]
        sources += sorted(path for path in SCRIPTS.iterdir() if path.is_file())
        unexplained: list[str] = []
        seen: set[tuple[str, str]] = set()
        for source in sources:
            relative = source.relative_to(REPO).as_posix()
            for scope, primitive, line in _writes(source):
                key = (relative, scope)
                if key in READ_ONLY_OPENS and primitive == "os.open":
                    continue
                if relative == "operational_memory/core.py" and scope.startswith("_Writer."):
                    # _Writer instances exist only inside write_transaction().
                    continue
                if key in KNOWN_WRITERS:
                    seen.add(key)
                    continue
                unexplained.append(f"{relative}:{line} {scope} {primitive}")
        self.assertEqual([], unexplained, "a new write path needs the learning gate or an entry here")
        self.assertEqual(set(KNOWN_WRITERS), seen, "stale inventory entry")

    def test_only_write_transaction_constructs_a_writer(self) -> None:
        source = (REPO / "operational_memory" / "core.py").read_text(encoding="utf-8")
        self.assertEqual(1, source.count("_Writer(self._conn)"))


if __name__ == "__main__":
    unittest.main()
