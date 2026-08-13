"""Fresh-install lifecycle: NONE -> OPERATIONAL_MEMORY, from the outside.

Exercises the supported current-product lifecycle through the real CLI
surface only (init-knowledge-root, preflight, knowledge-lookup,
discovery-begin, discovery-finalize). No imported-installation receipt is fabricated here;
this file proves the end-to-end lifecycle a real fresh installation follows.

Every subprocess call runs with an isolated HOME/LOCALAPPDATA (see
``fake_home_env``): the default Knowledge Root location is derived from the
user's home directory, and these tests must never read or write the real
machine's own installation.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO
INIT = SKILL / "scripts" / "init-knowledge-root"
PREFLIGHT = SKILL / "scripts" / "preflight"
LOOKUP = SKILL / "scripts" / "knowledge-lookup"
BEGIN = SKILL / "scripts" / "discovery-begin"
FINALIZER = SKILL / "scripts" / "discovery-finalize"
sys.path.insert(0, str(SKILL))

from platform_adapter import KNOWLEDGE_ROOT_ENV
from write_authority import (
    FRESH_INSTALL_WRITE_AUTHORITY_KIND,
    MIGRATED_WRITE_AUTHORITY_KIND,
    automatic_legacy_rollback_allowed,
)

RECORDED = "2026-08-09T00:00:00Z"


def run(
    script: Path, *arguments: str, cwd: Path | None = None, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *arguments],
        text=True,
        capture_output=True,
        cwd=str(cwd) if cwd else None,
        env=env,
    )


def fake_home_env(home: Path, **overrides: str) -> dict[str, str]:
    """An isolated subprocess environment: a private HOME (and Windows
    equivalents) so the per-user default Knowledge Root never reads or
    writes this machine's real state, and each test's automatic resolution
    is hermetic and deterministic."""
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["LOCALAPPDATA"] = str(home / "AppData" / "Local")
    env.pop("XDG_DATA_HOME", None)
    env.pop(KNOWLEDGE_ROOT_ENV, None)
    env.update(overrides)
    return env


def snapshot_tree(root: Path) -> dict[str, bytes]:
    """Relative path -> file contents, for asserting a directory is left
    byte-identical after a refused operation (no partial writes)."""
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def discovery_payload(target: str, capability: str = "public-homepage") -> dict:
    return {
        "target": target,
        "capability": capability,
        "observations": [
            {"family": "transport", "value": {"transport": "DIRECT_READ", "outcome": "FUNCTIONAL"}},
        ],
        "evidence": [{"kind": "direct-read-validation", "locator": f"https://{target}.example/"}],
        "provenance": {"run_id": f"run:{target}:001", "observed_at": RECORDED},
        "recorded_at": RECORDED,
    }


def begin_for_payload(
    payload_path: Path, *root_arguments: str,
    cwd: Path | None = None, env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    result = run(
        BEGIN, *root_arguments, "--target", payload["target"],
        "--capability", payload["capability"], cwd=cwd, env=env,
    )
    if result.returncode == 0:
        payload["provenance"]["run_id"] = json.loads(result.stdout)["run_id"]
        payload_path.write_text(json.dumps(payload), encoding="utf-8")
    return result


class FreshInstallEndToEndTests(unittest.TestCase):
    """A CaravelaWeb code checkout and a separate empty Knowledge Root."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # The code checkout (REPO/SKILL) lives outside this directory entirely;
        # the Knowledge Root is a plain, unrelated empty directory.
        self.root = Path(self.temp.name) / "knowledge-root"
        self.home = Path(self.temp.name) / "home"
        self.env = fake_home_env(self.home)

    def test_uninitialized_to_found_via_supported_lifecycle(self) -> None:
        self.assertFalse(self.root.exists())

        initialize = run(INIT, "--knowledge-root", str(self.root), "--json", env=self.env)
        self.assertEqual(0, initialize.returncode, initialize.stderr)
        self.assertEqual("INITIALIZED", json.loads(initialize.stdout)["status"])

        preflight = run(PREFLIGHT, "--knowledge-root", str(self.root), "--json", env=self.env)
        self.assertEqual(0, preflight.returncode, preflight.stderr)
        report = json.loads(preflight.stdout)
        self.assertEqual("READY", report["status"])
        self.assertEqual([], report["errors"])
        self.assertTrue(report["operational_memory"]["ready"])

        first_lookup = run(LOOKUP, "--knowledge-root", str(self.root), "--target", "acme", env=self.env)
        self.assertEqual(0, first_lookup.returncode, first_lookup.stderr)
        found = json.loads(first_lookup.stdout)
        self.assertEqual("not_found", found["status"])
        self.assertEqual("operational-memory", found["source"])

        payload_path = self.root.parent / "discovery.json"
        payload_path.write_text(json.dumps(discovery_payload("acme")), encoding="utf-8")
        begun = begin_for_payload(
            payload_path, "--knowledge-root", str(self.root), env=self.env,
        )
        self.assertEqual(0, begun.returncode, begun.stderr)
        finalize = run(FINALIZER, "--knowledge-root", str(self.root), "--input", str(payload_path), env=self.env)
        self.assertEqual(0, finalize.returncode, finalize.stderr)
        self.assertEqual("SAVED", json.loads(finalize.stdout)["status"])

        second_lookup = run(LOOKUP, "--knowledge-root", str(self.root), "--target", "acme", env=self.env)
        self.assertEqual(0, second_lookup.returncode, second_lookup.stderr)
        found_again = json.loads(second_lookup.stdout)
        self.assertEqual("found", found_again["status"])
        self.assertEqual("operational-memory", found_again["source"])

        # Imported-installation receipt fields must never appear on a fresh
        # installation, before or after a real Discovery write.
        authority = json.loads((self.root / ".caravelaweb" / "write-authority.json").read_text(encoding="utf-8"))
        self.assertEqual(FRESH_INSTALL_WRITE_AUTHORITY_KIND, authority["kind"])
        self.assertEqual("NONE", authority["previous_write_authority"])
        for migration_field in (
            "activation_receipt", "first_om_write_receipt", "read_cutover_receipt_sha256",
            "database_counts_before_and_after", "gates",
            "om_authoritative_writes", "first_om_write",
        ):
            self.assertNotIn(migration_field, authority)
        self.assertEqual(
            {
                "open-discovery",
                "operational_memory.db",
                "read-authority-operational-memory",
                "write-authority.json",
            },
            {path.name for path in (self.root / ".caravelaweb").iterdir()},
        )

        # A fresh install never had LEGACY authority, so "automatic rollback
        # to LEGACY" is never meaningful for it -- this must hold regardless
        # of the real write that just happened, since fresh markers carry no
        # write counter to go stale in the first place.
        self.assertFalse(automatic_legacy_rollback_allowed(self.root))

    def test_default_location_is_found_across_separate_process_invocations(self) -> None:
        """The primary onboarding path: init with no --knowledge-root, then
        every later command finds the same installation automatically, with
        neither a repeated flag nor a temporary environment variable -- each
        step below is its own subprocess, simulating separate sessions."""
        initialize = run(INIT, "--json", env=self.env)
        self.assertEqual(0, initialize.returncode, initialize.stderr)
        report = json.loads(initialize.stdout)
        self.assertEqual("INITIALIZED", report["status"])
        default_root = Path(report["knowledge_root"])
        # The recommended default lives under the user's own app directory,
        # never inside the source checkout or a project directory. Compare
        # against the resolved form of self.home: the product canonicalizes
        # (e.g. a Windows short 8.3-alias segment resolves to its long
        # form), so an unresolved comparison here would mismatch even for a
        # genuinely correct result.
        self.assertTrue(default_root.is_relative_to(self.home.resolve()))
        self.assertFalse(default_root.is_relative_to(REPO))

        unrelated_cwd = self.home.parent  # an unrelated directory; resolution ignores cwd
        no_override_env = {k: v for k, v in self.env.items() if k != KNOWLEDGE_ROOT_ENV}

        preflight = run(PREFLIGHT, "--json", cwd=unrelated_cwd, env=no_override_env)
        self.assertEqual(0, preflight.returncode, preflight.stderr)
        preflight_report = json.loads(preflight.stdout)
        self.assertEqual("READY", preflight_report["status"])
        self.assertEqual(str(default_root), preflight_report["knowledge_root"]["path"])

        not_found = run(LOOKUP, "--target", "acme", cwd=unrelated_cwd, env=no_override_env)
        self.assertEqual(0, not_found.returncode, not_found.stderr)
        self.assertEqual("not_found", json.loads(not_found.stdout)["status"])

        payload_path = self.home.parent / "discovery.json"
        payload_path.write_text(json.dumps(discovery_payload("acme")), encoding="utf-8")
        begun = begin_for_payload(payload_path, cwd=unrelated_cwd, env=no_override_env)
        self.assertEqual(0, begun.returncode, begun.stderr)
        finalize = run(FINALIZER, "--input", str(payload_path), cwd=unrelated_cwd, env=no_override_env)
        self.assertEqual(0, finalize.returncode, finalize.stderr)
        self.assertEqual("SAVED", json.loads(finalize.stdout)["status"])

        found = run(LOOKUP, "--target", "acme", cwd=unrelated_cwd, env=no_override_env)
        self.assertEqual(0, found.returncode, found.stderr)
        self.assertEqual("found", json.loads(found.stdout)["status"])

    def test_an_explicit_root_never_changes_what_later_commands_resolve(self) -> None:
        """The isolation guarantee. Initializing a root somewhere else -- as a
        concurrent session on the same machine does -- must not move anyone's
        default. Only the flag or the environment variable reaches it."""
        default_init = run(INIT, "--json", env=self.env)
        self.assertEqual(0, default_init.returncode, default_init.stderr)
        default_root = Path(json.loads(default_init.stdout)["knowledge_root"])

        other_init = run(INIT, "--knowledge-root", str(self.root), "--json", env=self.env)
        self.assertEqual(0, other_init.returncode, other_init.stderr)
        self.assertNotEqual(default_root, self.root)

        # Explicit --knowledge-root selects self.root. Compare against the
        # resolved form: the product canonicalizes the supplied path.
        preflight = run(PREFLIGHT, "--knowledge-root", str(self.root), "--json", env=self.env)
        self.assertEqual(str(self.root.resolve()), json.loads(preflight.stdout)["knowledge_root"]["path"])

        # With no override, resolution still finds the fixed default -- the
        # second init changed nothing for anybody.
        no_override = run(PREFLIGHT, "--json", env=self.env)
        self.assertEqual(str(default_root), json.loads(no_override.stdout)["knowledge_root"]["path"])

        # And it reports the state of the default root, not of self.root: a
        # target saved in self.root is invisible without the override.
        payload_path = self.root.parent / "explicit-discovery.json"
        payload_path.write_text(json.dumps(discovery_payload("acme")), encoding="utf-8")
        begun = begin_for_payload(payload_path, "--knowledge-root", str(self.root), env=self.env)
        self.assertEqual(0, begun.returncode, begun.stderr)
        finalize = run(
            FINALIZER, "--knowledge-root", str(self.root), "--input", str(payload_path), env=self.env
        )
        self.assertEqual(0, finalize.returncode, finalize.stderr)

        unseen = run(LOOKUP, "--target", "acme", env=self.env)
        self.assertEqual(0, unseen.returncode, unseen.stderr)
        self.assertEqual("not_found", json.loads(unseen.stdout)["status"])

    def test_env_var_still_works_as_an_advanced_override(self) -> None:
        initialize = run(INIT, "--knowledge-root", str(self.root), "--json", env=self.env)
        self.assertEqual(0, initialize.returncode, initialize.stderr)

        unrelated_cwd = self.root.parent  # an unrelated directory; resolution ignores cwd
        session_env = {**self.env, KNOWLEDGE_ROOT_ENV: str(self.root)}

        preflight = run(PREFLIGHT, "--json", cwd=unrelated_cwd, env=session_env)
        self.assertEqual(0, preflight.returncode, preflight.stderr)
        self.assertEqual("READY", json.loads(preflight.stdout)["status"])

        not_found = run(LOOKUP, "--target", "acme", cwd=unrelated_cwd, env=session_env)
        self.assertEqual(0, not_found.returncode, not_found.stderr)
        self.assertEqual("not_found", json.loads(not_found.stdout)["status"])

        payload_path = self.root.parent / "env-discovery.json"
        payload_path.write_text(json.dumps(discovery_payload("acme")), encoding="utf-8")
        begun = begin_for_payload(payload_path, cwd=unrelated_cwd, env=session_env)
        self.assertEqual(0, begun.returncode, begun.stderr)
        finalize = run(FINALIZER, "--input", str(payload_path), cwd=unrelated_cwd, env=session_env)
        self.assertEqual(0, finalize.returncode, finalize.stderr)
        self.assertEqual("SAVED", json.loads(finalize.stdout)["status"])

        found = run(LOOKUP, "--target", "acme", cwd=unrelated_cwd, env=session_env)
        self.assertEqual("found", json.loads(found.stdout)["status"])
        # The env var, not the caller's cwd or a coincidental colocated
        # marker, is what resolved this: the target only exists in self.root.
        self.assertEqual("operational-memory", json.loads(found.stdout)["source"])


class FreshInstallSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "root"
        self.env = fake_home_env(Path(self.temp.name) / "home")

    def refuse(self, *arguments: str) -> dict:
        result = run(INIT, "--knowledge-root", str(self.root), "--json", *arguments, env=self.env)
        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual("REFUSED", report["status"])
        return report

    def test_refuses_when_targets_already_has_knowledge(self) -> None:
        (self.root / "targets").mkdir(parents=True)
        (self.root / "targets" / "known.md").write_text("# known\n", encoding="utf-8")
        self.refuse()

    def test_refuses_when_candidates_already_has_knowledge(self) -> None:
        """Candidate content makes a location non-fresh even without targets/."""
        (self.root / "candidates" / "some-target").mkdir(parents=True)
        (self.root / "candidates" / "some-target" / "delta.md").write_text("# delta\n", encoding="utf-8")
        self.refuse()

    def test_refuses_the_real_repository_legacy_corpus(self) -> None:
        """An existing corpus is refused and left byte-identical."""
        (self.root / "targets").mkdir(parents=True)
        (self.root / "targets" / "known.md").write_text("# known\n", encoding="utf-8")
        (self.root / "targets" / "other.md").write_text("# other\n", encoding="utf-8")
        (self.root / "candidates" / "some-target").mkdir(parents=True)
        (self.root / "candidates" / "some-target" / "delta.md").write_text("# delta\n", encoding="utf-8")
        (self.root / "candidates" / "some-target" / "notes.json").write_text('{"n": 1}\n', encoding="utf-8")

        before = snapshot_tree(self.root)
        self.refuse()
        self.assertEqual(before, snapshot_tree(self.root))

    def test_refuses_existing_migrated_authority_state(self) -> None:
        from operational_memory import SQLiteOperationalMemory

        self.root.mkdir(parents=True)
        (self.root / "targets").mkdir()
        state = self.root / ".caravelaweb"
        state.mkdir()
        with SQLiteOperationalMemory(state / "operational_memory.db"):
            pass
        (state / "write-authority.json").write_text(
            json.dumps({
                "kind": MIGRATED_WRITE_AUTHORITY_KIND, "status": "ACTIVE",
                "previous_write_authority": "LEGACY", "write_authority": "OPERATIONAL_MEMORY",
                "om_authoritative_writes": 0, "first_om_write": "NOT_PERFORMED",
            }),
            encoding="utf-8",
        )
        self.refuse()

    def test_refuses_malformed_or_contradictory_state_directory(self) -> None:
        self.root.mkdir(parents=True)
        state = self.root / ".caravelaweb"
        state.mkdir()
        (state / "garbage").write_text("not a real marker\n", encoding="utf-8")
        self.refuse()

    def test_refuses_an_already_initialized_root(self) -> None:
        first = run(INIT, "--knowledge-root", str(self.root), "--json", env=self.env)
        self.assertEqual(0, first.returncode, first.stderr)
        self.refuse()

    def test_tolerates_a_bare_advisory_lock_file(self) -> None:
        """The maintenance lock file is infrastructure, not installation state."""
        self.root.mkdir(parents=True)
        (self.root / ".caravelaweb").mkdir()
        (self.root / ".caravelaweb" / "write-authority.lock").touch()
        result = run(INIT, "--knowledge-root", str(self.root), "--json", env=self.env)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("INITIALIZED", json.loads(result.stdout)["status"])


class SourceAndKnowledgeRootIndependenceTests(unittest.TestCase):
    """Code location and knowledge location are independent; the selected root is authoritative."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.env = fake_home_env(self.base / "home")

    def test_two_installations_stay_isolated_regardless_of_cwd(self) -> None:
        root_a = self.base / "install-a"
        root_b = self.base / "install-b"
        unrelated_cwd = self.base  # deliberately not the code checkout, not either root
        for root in (root_a, root_b):
            initialize = run(INIT, "--knowledge-root", str(root), "--json", cwd=unrelated_cwd, env=self.env)
            self.assertEqual(0, initialize.returncode, initialize.stderr)

        payload_path = self.base / "discovery.json"
        payload_path.write_text(json.dumps(discovery_payload("only-in-a")), encoding="utf-8")
        begun = begin_for_payload(
            payload_path, "--knowledge-root", str(root_a),
            cwd=unrelated_cwd, env=self.env,
        )
        self.assertEqual(0, begun.returncode, begun.stderr)
        finalize = run(
            FINALIZER, "--knowledge-root", str(root_a), "--input", str(payload_path),
            cwd=unrelated_cwd, env=self.env,
        )
        self.assertEqual(0, finalize.returncode, finalize.stderr)
        self.assertEqual("SAVED", json.loads(finalize.stdout)["status"])

        found_in_a = run(
            LOOKUP, "--knowledge-root", str(root_a), "--target", "only-in-a", cwd=unrelated_cwd, env=self.env
        )
        self.assertEqual("found", json.loads(found_in_a.stdout)["status"])

        not_found_in_b = run(
            LOOKUP, "--knowledge-root", str(root_b), "--target", "only-in-a", cwd=unrelated_cwd, env=self.env
        )
        self.assertEqual("not_found", json.loads(not_found_in_b.stdout)["status"])

        # The code checkout was never touched by either installation.
        self.assertFalse((REPO / "knowledge-root").exists())


class ExplicitRootTouchesNoUserStateTests(unittest.TestCase):
    """Initializing an explicit root writes inside that root and nowhere
    else: it stores no per-user default, so an unusable home directory
    cannot make it fail, and no other session can be affected by it."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        # A plain file where the per-user app directory needs a directory
        # component, so any write under HOME would fail with
        # NotADirectoryError. Initialization must not attempt one.
        blocker = self.base / "blocked-home-parent"
        blocker.write_text("not a directory\n", encoding="utf-8")
        self.env = fake_home_env(blocker / "home")

    def test_an_unwritable_home_does_not_affect_an_explicit_root(self) -> None:
        root = self.base / "kr"
        result = run(INIT, "--knowledge-root", str(root), "--json", env=self.env)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        # The product resolves the supplied path (e.g. a Windows short
        # 8.3-alias segment like "RUNNER~1" canonicalizes to its long form);
        # compare against that same canonical form, not the raw input.
        self.assertEqual(
            {
                "status": "INITIALIZED",
                "knowledge_root": str(root.resolve()),
                "default_location": False,
            },
            json.loads(result.stdout),
        )

        preflight = run(PREFLIGHT, "--knowledge-root", str(root), "--json", env=self.env)
        self.assertEqual(0, preflight.returncode, preflight.stderr)
        self.assertEqual("READY", json.loads(preflight.stdout)["status"])

        # It also remains reachable through the advanced env-var override.
        env_override = {**self.env, KNOWLEDGE_ROOT_ENV: str(root)}
        via_env = run(PREFLIGHT, "--json", env=env_override)
        self.assertEqual("READY", json.loads(via_env.stdout)["status"])

    def test_human_readable_output_says_the_root_is_not_the_default(self) -> None:
        root = self.base / "kr2"
        result = run(INIT, "--knowledge-root", str(root), env=self.env)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("status: INITIALIZED", result.stdout)
        self.assertIn("not the default", result.stdout)
        self.assertIn(str(root.resolve()), result.stdout)
        self.assertIn(KNOWLEDGE_ROOT_ENV, result.stdout)


if __name__ == "__main__":
    unittest.main()
