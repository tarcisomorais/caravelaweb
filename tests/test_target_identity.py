"""Target-identity resolution: one path, target != host, no invented IDs.

Covers the pre-public bug where a Discovery write for ``gtolab.com`` was
stored as ``gtolab-com`` while a later lookup for the original reference
``gtolab.com`` reported ``not_found`` -- breaking "learn once, reuse later" --
and the follow-up correction that a hostname must never become the canonical
target ID by slugging (it must resolve through an existing target<->host
association, or fail closed). All examples here are synthetic, not real
target data.
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
sys.path.insert(0, str(SKILL))

from discovery_finalize import DiscoveryFinalizationError, finalize_discovery
from integration_bridge import KnowledgeLookupBoundary
from operational_memory import SQLiteOperationalMemory, TargetIdentityError
from operational_memory.core import is_canonical_target_id, normalize_host_reference
from write_authority import MIGRATED_WRITE_AUTHORITY_KIND

RECORDED = "2026-08-09T00:00:00Z"
INIT = SKILL / "scripts" / "init-knowledge-root"
LOOKUP = SKILL / "scripts" / "knowledge-lookup"
BEGIN = SKILL / "scripts" / "discovery-begin"
FINALIZER = SKILL / "scripts" / "discovery-finalize"


def run(script: Path, *arguments: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *arguments], text=True, capture_output=True, env=env,
    )


def fake_home_env(home: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["LOCALAPPDATA"] = str(home / "AppData" / "Local")
    env.pop("XDG_DATA_HOME", None)
    env.pop("CARAVELAWEB_KNOWLEDGE_ROOT", None)
    return env


class NormalizeHostReferenceTests(unittest.TestCase):
    """Pure host-string normalization: never a target ID."""

    def test_www_and_scheme_variants_share_one_host_string(self) -> None:
        equivalents = (
            "example.com", "www.example.com",
            "https://example.com/", "https://www.example.com/",
            "http://EXAMPLE.com",
        )
        resolved = {normalize_host_reference(reference) for reference in equivalents}
        self.assertEqual({"example.com"}, resolved)

    def test_url_path_query_and_fragment_are_dropped(self) -> None:
        self.assertEqual(
            "example.com",
            normalize_host_reference("https://example.com/some/path?q=1#frag"),
        )

    def test_dots_are_never_collapsed_to_hyphens(self) -> None:
        """The bug this correction targets: a host string is not a target ID."""
        self.assertEqual("gtolab.com", normalize_host_reference("gtolab.com"))
        self.assertNotIn("-", normalize_host_reference("gtolab.com"))

    def test_distinct_hosts_never_collide(self) -> None:
        """a.b.com and a-b.com must never be conflated by any normalization."""
        self.assertNotEqual(
            normalize_host_reference("a.b.com"),
            normalize_host_reference("a-b.com"),
        )
        self.assertEqual("a.b.com", normalize_host_reference("a.b.com"))
        self.assertEqual("a-b.com", normalize_host_reference("a-b.com"))

    def test_ambiguous_references_fail_closed(self) -> None:
        for reference in (
            "user:pass@evil.com",
            "http://1.2.3.4/",
            "ftp://example.com",
            "",
            "   ",
        ):
            with self.assertRaises(TargetIdentityError):
                normalize_host_reference(reference)

    def test_invalid_textual_port_fails_closed(self) -> None:
        with self.assertRaises(TargetIdentityError):
            normalize_host_reference("https://example.com:bad")

    def test_out_of_range_port_fails_closed(self) -> None:
        with self.assertRaises(TargetIdentityError):
            normalize_host_reference("https://example.com:99999")

    def test_embedded_leading_and_trailing_whitespace_fail_closed(self) -> None:
        for reference in ("exa mple.com", " example.com", "example.com ", "example.com\t"):
            with self.assertRaises(TargetIdentityError):
                normalize_host_reference(reference)

    def test_ipv4_literal_fails_closed(self) -> None:
        with self.assertRaises(TargetIdentityError):
            normalize_host_reference("1.2.3.4")

    def test_ipv6_literal_fails_closed(self) -> None:
        with self.assertRaises(TargetIdentityError):
            normalize_host_reference("[2001:db8::1]")

    def test_ipv4_mapped_ipv6_literal_fails_closed(self) -> None:
        with self.assertRaises(TargetIdentityError):
            normalize_host_reference("http://[::ffff:192.0.2.1]/")

    def test_single_trailing_dot_normalizes_like_no_trailing_dot(self) -> None:
        self.assertEqual("example.com", normalize_host_reference("example.com."))

    def test_repeated_trailing_dots_fail_closed(self) -> None:
        for reference in ("example.com..", "example.com..."):
            with self.assertRaises(TargetIdentityError):
                normalize_host_reference(reference)

    def test_unicode_and_punycode_idna_forms_converge(self) -> None:
        self.assertEqual(
            normalize_host_reference("xn--bcher-kva.example"),
            normalize_host_reference("bücher.example"),
        )
        self.assertEqual("xn--bcher-kva.example", normalize_host_reference("bücher.example"))


class CanonicalTargetIdShapeTests(unittest.TestCase):
    def test_existing_canonical_ids_are_recognized_and_kept_stable(self) -> None:
        for existing in ("example-jobs", "example-news", "gtolab"):
            self.assertTrue(is_canonical_target_id(existing))

    def test_a_host_reference_is_not_a_canonical_id(self) -> None:
        for hostlike in ("example.com", "www.example.com", "gtolab.com"):
            self.assertFalse(is_canonical_target_id(hostlike))


class TargetHostAssociationTests(unittest.TestCase):
    """Write/read parity, target != host, through the real OM boundary."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / ".caravelaweb").mkdir()
        (self.root / "targets").mkdir()
        (self.root / ".caravelaweb/write-authority.json").write_text(json.dumps({
            "kind": MIGRATED_WRITE_AUTHORITY_KIND, "status": "ACTIVE",
            "previous_write_authority": "LEGACY", "write_authority": "OPERATIONAL_MEMORY",
            "om_authoritative_writes": 0, "first_om_write": "NOT_PERFORMED",
        }), encoding="utf-8")
        self.db = self.root / ".caravelaweb/operational_memory.db"
        self.memory = SQLiteOperationalMemory(self.db, knowledge_root=self.root)
        self.addCleanup(self.memory.close)

    def _finalize(self, target: str, *, host: str | None = None, run="001", capability="public-homepage"):
        observation = {
            "family": "transport",
            "value": {"transport": "DIRECT_READ", "outcome": "FUNCTIONAL"},
        }
        if host:
            observation["host"] = host
        return finalize_discovery(
            self.memory, target=target, capability=capability,
            observations=[observation],
            evidence=[{
                "kind": "direct-read-validation", "locator": f"https://{host or target}/",
                "scope": "TARGET_SURFACE",
            }],
            provenance={"run_id": f"run:synthetic:{run}", "observed_at": RECORDED},
            recorded_at=RECORDED,
        )

    def test_first_time_discovery_requires_the_stable_canonical_id(self) -> None:
        """A bare hostname with no prior association must not invent a target."""
        with self.assertRaises(DiscoveryFinalizationError):
            self._finalize("gtolab.com")

    def test_hostname_slug_is_never_manufactured_as_target_id(self) -> None:
        result = self._finalize("gtolab", host="gtolab.com")
        self.assertEqual("SAVED", result.status)
        self.assertEqual("tgt:gtolab", self.memory.resolve_target("gtolab"))
        with self.assertRaises(KeyError):
            self.memory.resolve_target("gtolab-com")

    def test_known_hostname_reference_resolves_to_its_canonical_target(self) -> None:
        self._finalize("gtolab", host="gtolab.com")
        self.assertEqual("tgt:gtolab", self.memory.resolve_target("gtolab.com"))
        self.assertEqual("tgt:gtolab", self.memory.resolve_target("https://www.gtolab.com/path"))

    def test_lookup_by_canonical_target_id_still_works(self) -> None:
        self._finalize("gtolab", host="gtolab.com")
        lookup = KnowledgeLookupBoundary(self.root, self.db)
        result = lookup.lookup("gtolab", capability="public-homepage", use_operational_memory=True)
        self.assertTrue(any(result.operational_context["current"].values()))

    def test_www_and_url_syntax_do_not_fork_a_known_host_reference(self) -> None:
        self._finalize("gtolab", host="www.gtolab.com")
        lookup = KnowledgeLookupBoundary(self.root, self.db)
        for reference in ("gtolab.com", "www.gtolab.com", "https://gtolab.com/"):
            result = lookup.lookup(reference, capability="public-homepage", use_operational_memory=True)
            self.assertTrue(
                any(result.operational_context["current"].values()),
                f"{reference!r} should resolve through the known host association",
            )

    def test_zero_host_matches_do_not_invent_a_target(self) -> None:
        self._finalize("gtolab", host="gtolab.com")
        lookup = KnowledgeLookupBoundary(self.root, self.db)
        result = lookup.lookup("unrelated-brand.example", capability="public-homepage", use_operational_memory=True)
        self.assertIsNone(result.operational_context)

    def test_a_second_target_cannot_claim_a_known_hostname(self) -> None:
        """The collision is refused while the caller can still fix the target."""
        self._finalize("gtolab-one", host="shared.example.com", run="001")
        with self.assertRaises(DiscoveryFinalizationError):
            self._finalize("gtolab-two", host="shared.example.com", run="002")
        self.assertEqual("tgt:gtolab-one", self.memory.resolve_target("shared.example.com"))
        self.assertEqual(
            1,
            self.memory._conn.execute(
                "SELECT count(*) FROM hosts WHERE hostname=?", ("shared.example.com",),
            ).fetchone()[0],
        )

    def test_multiple_target_matches_fail_closed(self) -> None:
        """Defence in depth for a database that already holds a collision."""
        self._finalize("gtolab-one", host="shared.example.com", run="001")
        self._finalize("gtolab-two", host="other.example.com", run="002")
        with self.memory.write_transaction() as writer:
            writer.host({
                "id": "host:gtolab-two:collision", "target_id": "tgt:gtolab-two",
                "hostname": "shared.example.com",
            })
        with self.assertRaises(KeyError):
            self.memory.resolve_target("shared.example.com")
        lookup = KnowledgeLookupBoundary(self.root, self.db)
        result = lookup.lookup("shared.example.com", capability="public-homepage", use_operational_memory=True)
        self.assertIsNone(result.operational_context)

    def test_ab_dot_com_and_a_hyphen_b_dot_com_do_not_collide(self) -> None:
        self._finalize("target-dot", host="a.b.com", run="001")
        self._finalize("target-hyphen", host="a-b.com", run="002")
        self.assertEqual("tgt:target-dot", self.memory.resolve_target("a.b.com"))
        self.assertEqual("tgt:target-hyphen", self.memory.resolve_target("a-b.com"))

    def test_target_and_host_remain_separate_concepts(self) -> None:
        self._finalize("gtolab", host="www.gtolab.com")
        rows = list(self.memory._conn.execute(
            "SELECT hostname FROM hosts WHERE target_id=?", ("tgt:gtolab",),
        ))
        self.assertEqual(["www.gtolab.com"], [row["hostname"] for row in rows])

    def test_ambiguous_target_reference_is_rejected_not_saved(self) -> None:
        with self.assertRaises(DiscoveryFinalizationError):
            self._finalize("user:pass@evil.com")

    def test_known_host_later_write_resolves_to_canonical_target(self) -> None:
        """Once target=example/host=example.com is known, a later Discovery
        finalized with target='example.com' must resolve and save under the
        existing canonical target, not fail and not fork a new target."""
        self._finalize("example", host="example.com", run="001")
        result = self._finalize("example.com", capability="search", run="002")
        self.assertEqual("SAVED", result.status)
        self.assertEqual("example", result.target)
        self.assertEqual("tgt:example", self.memory.resolve_target("example"))
        with self.assertRaises(KeyError):
            self.memory.resolve_target("example-com")

    def test_ambiguous_host_write_fails_closed_with_no_write(self) -> None:
        """A hostname shared by two targets must refuse to finalize under
        that hostname, and must not create or mutate any capability."""
        self._finalize("gtolab-one", host="shared.example.com", run="001")
        self._finalize("gtolab-two", host="other.example.com", run="002")
        with self.memory.write_transaction() as writer:
            writer.host({
                "id": "host:gtolab-two:collision", "target_id": "tgt:gtolab-two",
                "hostname": "shared.example.com",
            })
        with self.assertRaises(DiscoveryFinalizationError):
            self._finalize("shared.example.com", capability="search", run="003")
        with self.assertRaises(KeyError):
            self.memory.resolve_capability("gtolab-one", "search")
        with self.assertRaises(KeyError):
            self.memory.resolve_capability("gtolab-two", "search")

    def test_malformed_observation_host_values_fail_closed(self) -> None:
        """observation.host must reject the same structural malformations
        as target host references: IP literals, whitespace, repeated
        trailing dots, and malformed/empty labels."""
        for bad_host in (
            "1.2.3.4",
            "[::ffff:192.0.2.1]",
            " example.com",
            "example.com ",
            "exa mple.com",
            "example.com..",
            "example.com...",
            "..example.com",
        ):
            with self.assertRaises(DiscoveryFinalizationError):
                self._finalize("gtolab-malformed", host=bad_host)

    def test_malformed_observation_host_creates_no_host_row(self) -> None:
        with self.assertRaises(DiscoveryFinalizationError):
            self._finalize("gtolab-malformed", host="1.2.3.4")
        rows = list(self.memory._conn.execute("SELECT 1 FROM hosts"))
        self.assertEqual([], rows)

    def test_malformed_observation_host_leaves_no_partial_target_or_capability(self) -> None:
        with self.assertRaises(DiscoveryFinalizationError):
            self._finalize("gtolab-malformed", host="example.com..")
        with self.assertRaises(KeyError):
            self.memory.resolve_target("gtolab-malformed")
        with self.assertRaises(KeyError):
            self.memory.resolve_capability("gtolab-malformed", "public-homepage")

    def test_valid_observation_host_still_works_including_idna(self) -> None:
        result = self._finalize("gtolab", host="www.gtolab.com")
        self.assertEqual("SAVED", result.status)
        rows = list(self.memory._conn.execute(
            "SELECT hostname FROM hosts WHERE target_id=?", ("tgt:gtolab",),
        ))
        self.assertEqual(["www.gtolab.com"], [row["hostname"] for row in rows])

        unicode_result = finalize_discovery(
            self.memory, target="bucher-brand", capability="public-homepage",
            observations=[{
                "family": "transport",
                "value": {"transport": "DIRECT_READ", "outcome": "FUNCTIONAL"},
                "host": "bücher.example",
            }],
            evidence=[{
                "kind": "direct-read-validation", "locator": "https://xn--bcher-kva.example/",
                "scope": "TARGET_SURFACE",
            }],
            provenance={"run_id": "run:synthetic:unicode", "observed_at": RECORDED},
            recorded_at=RECORDED,
        )
        self.assertEqual("SAVED", unicode_result.status)
        idna_rows = list(self.memory._conn.execute(
            "SELECT hostname FROM hosts WHERE target_id=?", ("tgt:bucher-brand",),
        ))
        self.assertEqual(["xn--bcher-kva.example"], [row["hostname"] for row in idna_rows])


class TargetIdentityCrossProcessTests(unittest.TestCase):
    """Real CLI round trip: canonical target on write, host/URL reference on
    a later, separate-process read."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "knowledge-root"
        self.home = Path(self.temp.name) / "home"
        self.env = fake_home_env(self.home)
        initialize = run(INIT, "--knowledge-root", str(self.root), "--json", env=self.env)
        self.assertEqual(0, initialize.returncode, initialize.stderr)

    def test_finalize_with_canonical_id_then_lookup_by_host_reference(self) -> None:
        payload = {
            "target": "gtolab",
            "capability": "public-homepage",
            "observations": [
                {
                    "family": "transport",
                    "value": {"transport": "DIRECT_READ", "outcome": "FUNCTIONAL"},
                    "host": "gtolab.com",
                },
            ],
            "evidence": [{
                "kind": "direct-read-validation", "locator": "https://gtolab.com/",
                "scope": "TARGET_SURFACE",
            }],
            "provenance": {"run_id": "run:gtolab:001", "observed_at": RECORDED},
            "recorded_at": RECORDED,
        }
        payload_path = self.root.parent / "discovery.json"
        payload_path.write_text(json.dumps(payload), encoding="utf-8")
        begun = run(
            BEGIN, "--knowledge-root", str(self.root), "--target", payload["target"],
            "--capability", payload["capability"], env=self.env,
        )
        self.assertEqual(0, begun.returncode, begun.stderr)
        payload["provenance"]["run_id"] = json.loads(begun.stdout)["run_id"]
        payload_path.write_text(json.dumps(payload), encoding="utf-8")
        finalize = run(FINALIZER, "--knowledge-root", str(self.root), "--input", str(payload_path), env=self.env)
        self.assertEqual(0, finalize.returncode, finalize.stderr)
        self.assertEqual("SAVED", json.loads(finalize.stdout)["status"])

        for reference in ("gtolab", "gtolab.com", "https://www.gtolab.com/"):
            lookup = run(LOOKUP, "--knowledge-root", str(self.root), "--target", reference, env=self.env)
            self.assertEqual(0, lookup.returncode, lookup.stderr)
            self.assertEqual(
                "found", json.loads(lookup.stdout)["status"],
                f"expected {reference!r} to resolve to the gtolab target",
            )

        # 'gtolab-com' is a plain kebab-case reference, not the same target.
        unrelated = run(LOOKUP, "--knowledge-root", str(self.root), "--target", "gtolab-com", env=self.env)
        self.assertEqual(0, unrelated.returncode, unrelated.stderr)
        self.assertEqual("not_found", json.loads(unrelated.stdout)["status"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
