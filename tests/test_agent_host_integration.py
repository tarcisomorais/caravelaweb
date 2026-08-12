"""Agent-host discovery, checked structurally.

Three independent surfaces are covered here:

- Plugin distribution (Claude Code): the public install reads
  ``.claude-plugin/marketplace.json`` and ``.claude-plugin/plugin.json`` from
  a fresh clone, and loads the repository-root ``SKILL.md`` as the plugin's
  single skill. See ``PluginDistributionTests`` below.

- Checkout-local discovery: a host opened directly in a fresh clone must find
  CaravelaWeb with no registration step. That depends on tracked files: root
  instruction files, and one thin skill-discovery adapter per host
  convention. These tests assert the shape of that surface -- never the
  internals of a third-party host.
- Global registration (Claude Code only, verified): a host opened in an
  unrelated repository must find CaravelaWeb only after
  ``scripts/register-host`` links the canonical checkout into the host's
  per-user skill directory. See ``HostRegistrationTests`` below.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REGISTER_HOST = REPO / "scripts" / "register-host"
PLUGIN_MANIFEST = Path(".claude-plugin/plugin.json")
MARKETPLACE_MANIFEST = Path(".claude-plugin/marketplace.json")

ADAPTERS = (
    Path(".claude/skills/caravelaweb/SKILL.md"),  # Claude Code, and OpenCode
    Path(".agents/skills/caravelaweb/SKILL.md"),  # Codex, and OpenCode
)

# Directories a thin adapter must never re-create beside itself.
RUNTIME_TREES = ("scripts", "references", "operational_memory")


def frontmatter_name(path: Path) -> str | None:
    match = re.match(r"^---\n(.*?)\n---\n", path.read_text(encoding="utf-8"), re.DOTALL)
    if not match:
        return None
    name = re.search(r"^name:\s*(\S+)\s*$", match.group(1), re.MULTILINE)
    return name.group(1) if name else None


def tracked() -> set[str]:
    output = subprocess.run(
        ["git", "-C", str(REPO), "ls-files"],
        text=True, capture_output=True, check=True,
    ).stdout
    return set(output.splitlines())


def tracked_root_entries() -> set[str]:
    """Top-level names a fresh clone (and therefore the plugin cache) holds."""
    return {name.split("/", 1)[0] for name in tracked()}


class CheckoutLocalDiscoveryTests(unittest.TestCase):
    def test_repository_root_stays_the_canonical_skill(self) -> None:
        self.assertEqual("caravelaweb", frontmatter_name(REPO / "SKILL.md"))

    def test_project_local_discovery_files_are_tracked(self) -> None:
        files = tracked()
        for relative in (Path("AGENTS.md"), Path("CLAUDE.md"), *ADAPTERS):
            with self.subTest(file=relative):
                self.assertTrue((REPO / relative).is_file(), f"missing: {relative}")
                # A .gitignore rule that hides an adapter breaks a fresh clone
                # while leaving this working tree healthy.
                self.assertIn(relative.as_posix(), files, f"untracked: {relative}")

    def test_adapters_are_thin_and_defer_to_the_repository_root(self) -> None:
        for relative in ADAPTERS:
            with self.subTest(adapter=relative):
                path = REPO / relative
                self.assertEqual("caravelaweb", frontmatter_name(path))
                body = path.read_text(encoding="utf-8")
                self.assertIn("canonical contract is `SKILL.md` at the repository root", body)
                self.assertIn("repository root", body)

                siblings = {child.name for child in path.parent.iterdir()}
                self.assertEqual({"SKILL.md"}, siblings, f"adapter is not thin: {siblings}")
                for tree in RUNTIME_TREES:
                    self.assertFalse(
                        (path.parent / tree).exists(),
                        f"duplicated runtime tree beside adapter: {tree}",
                    )

    def test_no_nested_historical_skill_root_returns(self) -> None:
        nested = [name for name in tracked() if "skills" in Path(name).parts]
        self.assertEqual(
            sorted(relative.as_posix() for relative in ADAPTERS),
            sorted(nested),
            "only the host discovery adapters may live under a nested skills/ path",
        )

    def test_bootstrap_files_stay_concise_and_share_one_policy(self) -> None:
        agents = (REPO / "AGENTS.md").read_text(encoding="utf-8")
        claude = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertLess(len(agents.splitlines()), 60)
        self.assertLess(len(claude.splitlines()), 20)
        # Claude Code does not read AGENTS.md; the text import keeps one policy
        # document without a Windows-hostile symlink.
        self.assertIn("@AGENTS.md", claude)


class PluginDistributionTests(unittest.TestCase):
    """The published Claude Code plugin, checked from tracked files only.

    A consumer never sees this working tree: Claude Code clones the
    repository, reads the marketplace catalog, and copies the plugin source
    into its own cache. Every assertion here therefore runs against tracked
    content and the documented single-skill-at-plugin-root layout.
    """

    def setUp(self) -> None:
        self.plugin = json.loads((REPO / PLUGIN_MANIFEST).read_text(encoding="utf-8"))
        self.marketplace = json.loads((REPO / MARKETPLACE_MANIFEST).read_text(encoding="utf-8"))

    def test_both_manifests_are_tracked(self) -> None:
        files = tracked()
        for relative in (PLUGIN_MANIFEST, MARKETPLACE_MANIFEST):
            with self.subTest(file=relative):
                self.assertIn(relative.as_posix(), files, f"untracked: {relative}")

    def test_marketplace_publishes_the_repository_root_as_one_plugin(self) -> None:
        entries = self.marketplace["plugins"]
        self.assertEqual(1, len(entries), f"expected exactly one plugin entry: {entries}")
        self.assertEqual("./", entries[0]["source"])
        self.assertIn("name", self.marketplace["owner"])

    def test_one_name_identifies_the_marketplace_entry_plugin_and_skill(self) -> None:
        # These three names are what a user types and what Claude Code
        # namespaces the skill with; drift between them breaks the documented
        # `/plugin install caravelaweb@caravelaweb` install.
        self.assertEqual("caravelaweb", self.marketplace["name"])
        self.assertEqual("caravelaweb", self.marketplace["plugins"][0]["name"])
        self.assertEqual("caravelaweb", self.plugin["name"])
        self.assertEqual("caravelaweb", frontmatter_name(REPO / "SKILL.md"))

    def test_single_skill_at_plugin_root_layout_is_preserved(self) -> None:
        # Claude Code loads a root SKILL.md as the plugin's single skill only
        # while the plugin declares no skills/ directory and no skills field.
        self.assertNotIn("skills", self.plugin)
        self.assertNotIn("skills", self.marketplace["plugins"][0])
        self.assertFalse((REPO / "skills").exists(), "a skills/ tree would shadow the root SKILL.md")

    def test_plugin_root_holds_no_installation_state(self) -> None:
        # The cached plugin directory is replaced on every update, so nothing
        # writable may be published inside it.
        for name in (".caravelaweb", ".caravelaweb-knowledge-root", "targets"):
            with self.subTest(entry=name):
                self.assertNotIn(name, tracked_root_entries())


def fake_home_env(home: Path) -> dict[str, str]:
    """An isolated subprocess environment: a private HOME (and Windows
    equivalent) so registration tests never read or write this machine's
    real Claude Code skill directory."""
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    return env


def run_register_host(*arguments: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(REGISTER_HOST), *arguments],
        text=True,
        capture_output=True,
        env=env,
    )


class HostRegistrationTests(unittest.TestCase):
    """scripts/register-host: the verified Claude Code global registration.

    Every case runs against an isolated HOME so the suite never reads or
    writes this machine's real ``~/.claude/skills``.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name) / "home"
        self.home.mkdir()
        self.env = fake_home_env(self.home)
        self.link = self.home / ".claude" / "skills" / "caravelaweb"

    def test_registration_points_at_repository_root(self) -> None:
        result = run_register_host("--host", "claude", "--json", env=self.env)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(self.link.is_symlink() or self.link.is_dir())
        self.assertEqual(REPO, Path(os.readlink(self.link)))

    def test_registration_does_not_copy_runtime_files(self) -> None:
        run_register_host("--host", "claude", "--json", env=self.env)
        siblings = list(self.link.parent.iterdir())
        self.assertEqual([self.link], siblings)
        self.assertTrue(self.link.is_symlink())
        self.assertFalse((self.link / "SKILL.md").is_symlink())

    def test_registration_resolves_from_unrelated_consumer_directory(self) -> None:
        run_register_host("--host", "claude", "--json", env=self.env)
        consumer = Path(self._tmp.name) / "some-unrelated-project"
        consumer.mkdir()
        resolved = self.link / "SKILL.md"
        self.assertEqual(
            (REPO / "SKILL.md").read_text(encoding="utf-8"),
            resolved.read_text(encoding="utf-8"),
        )

    def test_registration_is_idempotent(self) -> None:
        first = run_register_host("--host", "claude", "--json", env=self.env)
        second = run_register_host("--host", "claude", "--json", env=self.env)
        self.assertEqual(0, first.returncode, first.stderr)
        self.assertEqual(0, second.returncode, second.stderr)
        self.assertIn('"status": "REGISTERED"', first.stdout)
        self.assertIn('"status": "ALREADY_REGISTERED"', second.stdout)
        self.assertEqual(REPO, Path(os.readlink(self.link)))

    def test_conflicting_destination_is_rejected_without_relink(self) -> None:
        elsewhere = Path(self._tmp.name) / "elsewhere"
        elsewhere.mkdir()
        self.link.parent.mkdir(parents=True)
        self.link.symlink_to(elsewhere, target_is_directory=True)

        refused = run_register_host("--host", "claude", "--json", env=self.env)
        self.assertEqual(2, refused.returncode)
        self.assertIn('"status": "REFUSED"', refused.stdout)
        self.assertEqual(elsewhere, Path(os.readlink(self.link)))

        repaired = run_register_host("--host", "claude", "--relink", "--json", env=self.env)
        self.assertEqual(0, repaired.returncode, repaired.stderr)
        self.assertIn('"status": "RELINKED"', repaired.stdout)
        self.assertEqual(REPO, Path(os.readlink(self.link)))

    def test_dangling_registration_is_detected_and_repaired(self) -> None:
        missing = Path(self._tmp.name) / "does-not-exist"
        self.link.parent.mkdir(parents=True)
        self.link.symlink_to(missing, target_is_directory=True)

        checked = run_register_host("--host", "claude", "--check", "--json", env=self.env)
        self.assertIn('"status": "DANGLING"', checked.stdout)

        refused = run_register_host("--host", "claude", "--json", env=self.env)
        self.assertEqual(2, refused.returncode)

        repaired = run_register_host("--host", "claude", "--relink", "--json", env=self.env)
        self.assertEqual(0, repaired.returncode, repaired.stderr)
        self.assertEqual(REPO, Path(os.readlink(self.link)))

    def test_plain_directory_at_link_path_is_never_touched(self) -> None:
        self.link.mkdir(parents=True)
        marker = self.link / "do-not-delete.txt"
        marker.write_text("unrelated content\n", encoding="utf-8")

        for arguments in (("--host", "claude"), ("--host", "claude", "--relink")):
            with self.subTest(arguments=arguments):
                result = run_register_host(*arguments, "--json", env=self.env)
                self.assertEqual(2, result.returncode)
                self.assertIn('"status": "REFUSED"', result.stdout)
                self.assertTrue(marker.is_file())
                self.assertEqual("unrelated content\n", marker.read_text(encoding="utf-8"))

    def test_registration_does_not_touch_knowledge_root_or_consumer_repo(self) -> None:
        consumer = Path(self._tmp.name) / "consumer-repo"
        consumer.mkdir()

        run_register_host("--host", "claude", "--json", env=self.env)

        self.assertEqual([], list(consumer.iterdir()))
        after = {path for path in self.home.rglob("*") if path != self.link}
        # Only the registration link itself (and its new parent directories)
        # may appear; no Knowledge Root state is created under HOME.
        self.assertFalse(any(".caravelaweb" in path.parts for path in after))
        self.assertFalse((self.home / "AppData").exists())
        self.assertFalse((self.home / ".local" / "share" / "caravelaweb").exists())


if __name__ == "__main__":
    unittest.main()
