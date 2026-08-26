"""Agent-host discovery, checked structurally.

Four independent surfaces are covered here:

- Plugin distribution (Claude Code): the public install reads
  ``.claude-plugin/marketplace.json`` and ``.claude-plugin/plugin.json`` from
  a fresh clone and discovers the shared ``skills/caravelaweb/SKILL.md``
  adapter. See ``PluginDistributionTests`` below.

- Plugin distribution (Codex): the public install reads
  ``.agents/plugins/marketplace.json`` and ``.codex-plugin/plugin.json`` and
  loads the same shared plugin adapter.

- Checkout-local discovery: a host opened directly in a fresh clone must find
  CaravelaWeb with no registration step. That depends on tracked files: root
  instruction files, and one thin skill-discovery adapter per host
  convention. These tests assert the shape of that surface -- never the
  internals of a third-party host.
- Global registration: a host opened in an
  unrelated repository must find CaravelaWeb only after
  ``scripts/register-host`` links the canonical checkout into the host's
  per-user skill directory. See ``HostRegistrationTests`` below.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REGISTER_HOST = REPO / "scripts" / "register-host"

sys.path.insert(0, str(REPO))

from host_registration import strip_extended_path_prefix  # noqa: E402


def link_destination(link: Path) -> Path:
    """The stored target of a registration link, on POSIX and Windows.

    Windows reports a junction or absolute symlink with the extended-length
    prefix (``\\\\?\\``); strip it so assertions compare user-visible paths.
    """
    return Path(strip_extended_path_prefix(os.readlink(link)))


def is_registration_link(link: Path) -> bool:
    """True for a POSIX symlink or a Windows junction, never a plain path."""
    result = os.lstat(link)
    return stat.S_ISLNK(result.st_mode) or bool(
        getattr(result, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )
PLUGIN_MANIFEST = Path(".claude-plugin/plugin.json")
MARKETPLACE_MANIFEST = Path(".claude-plugin/marketplace.json")
CODEX_PLUGIN_MANIFEST = Path(".codex-plugin/plugin.json")
CODEX_MARKETPLACE_MANIFEST = Path(".agents/plugins/marketplace.json")
PLUGIN_ADAPTER = Path("skills/caravelaweb/SKILL.md")

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
    def test_repository_root_stays_the_only_canonical_contract(self) -> None:
        self.assertEqual("caravelaweb", frontmatter_name(REPO / "SKILL.md"))
        for relative in (*ADAPTERS, PLUGIN_ADAPTER):
            with self.subTest(adapter=relative):
                self.assertIn(
                    "not the CaravelaWeb contract",
                    " ".join((REPO / relative).read_text(encoding="utf-8").split()),
                )

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
                self.assertIn("canonical contract is `SKILL.md`", body)

                if relative == Path(".agents/skills/caravelaweb/SKILL.md"):
                    self.assertIn(
                        "`../../..` from the directory holding this adapter",
                        " ".join(body.split()),
                    )
                    self.assertIn("never from the current working directory", body)
                else:
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
            sorted(relative.as_posix() for relative in (*ADAPTERS, PLUGIN_ADAPTER)),
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
    content and the documented shared plugin-skill layout.
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
        self.assertEqual("caravelaweb", frontmatter_name(REPO / PLUGIN_ADAPTER))

    def test_exactly_one_shared_plugin_skill_defers_to_the_root_contract(self) -> None:
        self.assertNotIn("skills", self.plugin)
        self.assertNotIn("skills", self.marketplace["plugins"][0])
        plugin_skills = sorted((REPO / "skills").glob("*/SKILL.md"))
        self.assertEqual([REPO / PLUGIN_ADAPTER], plugin_skills)
        body = plugin_skills[0].read_text(encoding="utf-8")
        self.assertIn("canonical contract is `SKILL.md` at the plugin root", body)
        self.assertIn("`../..` from the", body)
        for tree in RUNTIME_TREES:
            self.assertFalse(plugin_skills[0].parent.joinpath(tree).exists())

    def test_published_files_are_checked_out_with_lf_endings(self) -> None:
        # Claude Code clones this repository to install the plugin. With a
        # CRLF checkout -- the Git for Windows default -- its frontmatter
        # parser misses `name:` and falls back to the install directory name,
        # which is the version string, so the skill stops being invocable as
        # `caravelaweb` on native Windows only.
        published = (
            "SKILL.md",
            PLUGIN_ADAPTER.as_posix(),
            PLUGIN_MANIFEST.as_posix(),
            MARKETPLACE_MANIFEST.as_posix(),
        )
        attributes = subprocess.run(
            ["git", "-C", str(REPO), "check-attr", "eol", "--", *published],
            text=True, capture_output=True, check=True,
        ).stdout
        for line in attributes.splitlines():
            with self.subTest(attribute=line):
                self.assertTrue(line.endswith(": eol: lf"), f"not pinned to LF: {line}")

    def test_plugin_root_holds_no_installation_state(self) -> None:
        # The cached plugin directory is replaced on every update, so nothing
        # writable may be published inside it.
        for name in (".caravelaweb", ".caravelaweb-knowledge-root", "targets"):
            with self.subTest(entry=name):
                self.assertNotIn(name, tracked_root_entries())


class CodexPluginDistributionTests(unittest.TestCase):
    """The native Codex marketplace uses the shared plugin adapter."""

    def setUp(self) -> None:
        self.plugin = json.loads((REPO / CODEX_PLUGIN_MANIFEST).read_text(encoding="utf-8"))
        self.marketplace = json.loads(
            (REPO / CODEX_MARKETPLACE_MANIFEST).read_text(encoding="utf-8")
        )

    def test_native_manifests_are_tracked(self) -> None:
        files = tracked()
        for relative in (CODEX_PLUGIN_MANIFEST, CODEX_MARKETPLACE_MANIFEST):
            with self.subTest(file=relative):
                self.assertIn(relative.as_posix(), files, f"untracked: {relative}")

    def test_native_marketplace_publishes_one_repository_root_plugin(self) -> None:
        entries = self.marketplace["plugins"]
        self.assertEqual("caravelaweb", self.marketplace["name"])
        self.assertEqual(1, len(entries), f"expected exactly one plugin entry: {entries}")
        self.assertEqual("caravelaweb", entries[0]["name"])
        self.assertEqual("./", entries[0]["source"])
        self.assertEqual("AVAILABLE", entries[0]["policy"]["installation"])
        self.assertNotIn("authentication", entries[0]["policy"])

    def test_native_plugin_has_release_version_and_shared_skill_layout(self) -> None:
        self.assertEqual("caravelaweb", self.plugin["name"])
        self.assertRegex(self.plugin["version"], r"^\d+\.\d+\.\d+$")
        self.assertEqual("./skills/", self.plugin["skills"])
        self.assertEqual("caravelaweb", frontmatter_name(REPO / PLUGIN_ADAPTER))

    def test_native_plugin_has_required_interface_metadata(self) -> None:
        interface = self.plugin["interface"]
        required = {
            "displayName",
            "shortDescription",
            "longDescription",
            "developerName",
            "category",
            "capabilities",
            "defaultPrompt",
        }
        self.assertEqual(set(), required - set(interface))

    def test_native_published_files_are_checked_out_with_lf_endings(self) -> None:
        published = (
            CODEX_PLUGIN_MANIFEST.as_posix(),
            CODEX_MARKETPLACE_MANIFEST.as_posix(),
            PLUGIN_ADAPTER.as_posix(),
        )
        attributes = subprocess.run(
            ["git", "-C", str(REPO), "check-attr", "eol", "--", *published],
            text=True, capture_output=True, check=True,
        ).stdout
        for line in attributes.splitlines():
            with self.subTest(attribute=line):
                self.assertTrue(line.endswith(": eol: lf"), f"not pinned to LF: {line}")


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


class ExtendedPathPrefixTests(unittest.TestCase):
    """Windows link targets carry an extended-length prefix that is
    transport syntax, not identity; comparisons must not see it."""

    def test_drive_prefix_is_stripped(self) -> None:
        self.assertEqual(
            "C:\\repo\\caravelaweb",
            strip_extended_path_prefix("\\\\?\\C:\\repo\\caravelaweb"),
        )

    def test_unc_prefix_is_stripped_to_unc_form(self) -> None:
        self.assertEqual(
            "\\\\server\\share\\repo",
            strip_extended_path_prefix("\\\\?\\UNC\\server\\share\\repo"),
        )

    def test_posix_and_plain_windows_paths_pass_through(self) -> None:
        self.assertEqual("/home/user/repo", strip_extended_path_prefix("/home/user/repo"))
        self.assertEqual("C:\\repo", strip_extended_path_prefix("C:\\repo"))


class HostRegistrationTests(unittest.TestCase):
    """scripts/register-host: verified per-user global registration.

    Every case runs against an isolated HOME so the suite never reads or
    writes this machine's real host skill directories.
    """

    HOST_DIRECTORIES = {
        "claude": Path(".claude/skills"),
        "codex": Path(".agents/skills"),
        "opencode": Path(".config/opencode/skills"),
    }

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name) / "home"
        self.home.mkdir()
        self.env = fake_home_env(self.home)

    def links(self):
        for host, directory in self.HOST_DIRECTORIES.items():
            yield host, self.home / directory / "caravelaweb"

    def test_registration_points_at_repository_root(self) -> None:
        for host, link in self.links():
            with self.subTest(host=host):
                result = run_register_host("--host", host, "--json", env=self.env)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertTrue(is_registration_link(link))
                self.assertEqual(REPO, link_destination(link))

    def test_registration_does_not_copy_runtime_files(self) -> None:
        for host, link in self.links():
            with self.subTest(host=host):
                run_register_host("--host", host, "--json", env=self.env)
                siblings = list(link.parent.iterdir())
                self.assertEqual([link], siblings)
                self.assertTrue(is_registration_link(link))
                self.assertFalse((link / "SKILL.md").is_symlink())

    def test_registration_resolves_from_unrelated_consumer_directory(self) -> None:
        consumer = Path(self._tmp.name) / "some-unrelated-project"
        consumer.mkdir()
        for host, link in self.links():
            with self.subTest(host=host):
                run_register_host("--host", host, "--json", env=self.env)
                self.assertEqual(
                    (REPO / "SKILL.md").read_text(encoding="utf-8"),
                    (link / "SKILL.md").read_text(encoding="utf-8"),
                )

    def test_registration_is_idempotent(self) -> None:
        for host, link in self.links():
            with self.subTest(host=host):
                first = run_register_host("--host", host, "--json", env=self.env)
                second = run_register_host("--host", host, "--json", env=self.env)
                self.assertEqual(0, first.returncode, first.stderr)
                self.assertEqual(0, second.returncode, second.stderr)
                self.assertIn('"status": "REGISTERED"', first.stdout)
                self.assertIn('"status": "ALREADY_REGISTERED"', second.stdout)
                self.assertEqual(REPO, link_destination(link))

    def test_conflicting_destination_is_rejected_without_relink(self) -> None:
        for host, link in self.links():
            with self.subTest(host=host):
                elsewhere = Path(self._tmp.name) / f"elsewhere-{host}"
                elsewhere.mkdir()
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(elsewhere, target_is_directory=True)
                refused = run_register_host("--host", host, "--json", env=self.env)
                self.assertEqual(2, refused.returncode)
                self.assertIn('"status": "REFUSED"', refused.stdout)
                self.assertEqual(elsewhere, link_destination(link))
                repaired = run_register_host("--host", host, "--relink", "--json", env=self.env)
                self.assertEqual(0, repaired.returncode, repaired.stderr)
                self.assertIn('"status": "RELINKED"', repaired.stdout)
                self.assertEqual(REPO, link_destination(link))

    def test_dangling_registration_is_detected_and_repaired(self) -> None:
        for host, link in self.links():
            with self.subTest(host=host):
                missing = Path(self._tmp.name) / f"does-not-exist-{host}"
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(missing, target_is_directory=True)
                checked = run_register_host("--host", host, "--check", "--json", env=self.env)
                self.assertIn('"status": "DANGLING"', checked.stdout)
                refused = run_register_host("--host", host, "--json", env=self.env)
                self.assertEqual(2, refused.returncode)
                repaired = run_register_host("--host", host, "--relink", "--json", env=self.env)
                self.assertEqual(0, repaired.returncode, repaired.stderr)
                self.assertEqual(REPO, link_destination(link))

    def test_plain_directory_at_link_path_is_never_touched(self) -> None:
        for host, link in self.links():
            link.mkdir(parents=True)
            marker = link / "do-not-delete.txt"
            marker.write_text("unrelated content\n", encoding="utf-8")
            for arguments in (("--host", host), ("--host", host, "--relink")):
                with self.subTest(host=host, arguments=arguments):
                    result = run_register_host(*arguments, "--json", env=self.env)
                    self.assertEqual(2, result.returncode)
                    self.assertIn('"status": "REFUSED"', result.stdout)
                    self.assertTrue(marker.is_file())
                    self.assertEqual("unrelated content\n", marker.read_text(encoding="utf-8"))

    def test_registration_does_not_touch_knowledge_root_or_consumer_repo(self) -> None:
        consumer = Path(self._tmp.name) / "consumer-repo"
        consumer.mkdir()

        links = dict(self.links())
        for host in links:
            run_register_host("--host", host, "--json", env=self.env)

        self.assertEqual([], list(consumer.iterdir()))
        after = {path for path in self.home.rglob("*") if path not in links.values()}
        # Only the registration link itself (and its new parent directories)
        # may appear; no Knowledge Root state is created under HOME.
        self.assertFalse(any(".caravelaweb" in path.parts for path in after))
        self.assertFalse((self.home / "AppData").exists())
        self.assertFalse((self.home / ".local" / "share" / "caravelaweb").exists())


if __name__ == "__main__":
    unittest.main()
