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

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO
sys.path.insert(0, str(SKILL))

from discovery_finalize import DiscoveryFinalizationError, finalize_discovery
from discovery_runs import begin_discovery
from integration_bridge import KnowledgeLookupBoundary
from operational_memory import SQLiteOperationalMemory, TargetIdentityError
from operational_memory.core import (
    is_canonical_target_id,
    normalize_host_reference,
    validate_public_hostname,
)
from write_authority import MIGRATED_WRITE_AUTHORITY_KIND

RECORDED = "2026-08-09T00:00:00Z"
INIT = SKILL / "scripts" / "init-knowledge-root"
LOOKUP = SKILL / "scripts" / "knowledge-lookup"
BEGIN = SKILL / "scripts" / "discovery-begin"
FINALIZER = SKILL / "scripts" / "discovery-finalize"
EXAMPLES = SKILL / "references" / "discovery-payload-examples.md"


def documented_example(name: str, *, target: str, capability: str, host: str) -> dict:
    """A tested payload from the reference, moved onto ``target`` and ``host``."""
    text = EXAMPLES.read_text(encoding="utf-8")
    for block in re.findall(r"```json\n(.*?)\n```", text, re.S):
        if json.loads(block)["target"] == name:
            moved = json.loads(block.replace(f"{name}.example", host).replace(f'"{name}"', f'"{target}"'))
            moved["capability"] = capability
            return moved
    raise LookupError(f"no documented example for {name}")


def profile_sections(markdown: str) -> dict[str, str]:
    """Each capability's lines in a Markdown target profile, by capability key."""
    sections: dict[str, str] = {}
    for chunk in markdown.split("\n## ")[1:]:
        heading, _, body = chunk.partition("\n")
        if heading.startswith("Capability: "):
            sections[heading.removeprefix("Capability: ")] = body.strip()
    return sections


def israel_hayom_search_payload() -> dict:
    """The shape of the record Disperta's reproduction never read: a search
    route proven in Lightpanda after a failed direct read."""
    host = "www.israelhayom.co.il"
    direct = f"https://{host}/search?hdyQ=consulate"
    rendered = f"https://{host}/search?hdyQ=consulate#rendered"
    context = {"authentication": "PUBLIC", "environment": "PRODUCTION"}
    lightpanda = {
        "transport": "LIGHTPANDA", "engine": "lightpanda", "javascript": True,
        "context": context, "evidence": [rendered],
    }
    return {
        "target": "israel-hayom-he",
        "capability": "search-articles",
        "observations": [
            {
                "family": "transport", "value": {"transport": "DIRECT_READ", "outcome": "FAILED"},
                "host": host,
                "validation": {
                    "transport": "DIRECT_READ", "outcome": "FAILED", "engine": None,
                    "javascript": False, "context": context, "evidence": [direct],
                },
            },
            {
                "family": "transport", "value": {"transport": "LIGHTPANDA", "outcome": "FUNCTIONAL"},
                "host": host, "validation": {**lightpanda, "outcome": "FUNCTIONAL"},
            },
            {"family": "authentication", "value": {"access_model": "PUBLIC"}},
            {
                "family": "validation",
                "value": {"operational_proof": {
                    "entrypoint": f"https://{host}/search?hdyQ={{percent-encoded-query}}",
                    "required_output": {"field_paths": {"url": "items[].url"}},
                    "completion_condition": "the results page lists /article/ links",
                    "critical_constraints": [],
                }},
                "host": host, "validation": {**lightpanda, "outcome": "SUCCESS"},
            },
        ],
        "evidence": [
            {"kind": "transport-validation", "locator": direct, "scope": "TARGET_SURFACE"},
            {"kind": "bounded-browser-validation", "locator": rendered, "scope": "TARGET_SURFACE"},
        ],
        "transport_trace": {
            "availability": {"LIGHTPANDA": "AVAILABLE", "CHROME": "AVAILABLE"},
            "attempts": [
                {"transport": "DIRECT_READ", "outcome": "FAILED", "host": host, "evidence": [direct]},
                {"transport": "LIGHTPANDA", "outcome": "FUNCTIONAL", "host": host, "evidence": [rendered]},
            ],
        },
        "provenance": {"run_id": "<from discovery-begin>", "observed_at": "2026-08-14T12:00:00Z"},
    }


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

    def test_short_form_and_hex_ipv4_are_rejected(self) -> None:
        for reference in ("127.1", "0x7f.0.0.1", "2130706433", "0177.0.0.1"):
            with self.assertRaises(TargetIdentityError):
                validate_public_hostname(reference)

    def test_non_numeric_labels_are_not_mistaken_for_ip_literals(self) -> None:
        self.assertEqual("1e100.net", validate_public_hostname("1e100.net"))


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
        opened = json.loads(begun.stdout)
        payload["provenance"]["run_id"] = opened["run_id"]
        # Observed and recorded at the instant the run opened: inside its window.
        payload["provenance"]["observed_at"] = opened["opened_at"]
        payload["recorded_at"] = opened["opened_at"]
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


class CombinedLookupIndexTests(unittest.TestCase):
    """One lookup call per capability answers with what the executor can use.

    The executor names a capability before it has seen the target's names,
    so a resolved target always brings its whole accepted profile, hit or
    miss. A reference that resolves to nothing gets no index: the whole
    ``--list`` payload outgrew any reply a model reads and hid the answer
    when cut short. ``--list`` itself is unchanged.
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "knowledge-root"
        self.home = Path(self.temp.name) / "home"
        self.env = fake_home_env(self.home)
        initialize = run(INIT, "--knowledge-root", str(self.root), "--json", env=self.env)
        self.assertEqual(0, initialize.returncode, initialize.stderr)
        self._seed("gtolab", "gtolab.com")
        self._seed("sky-news-world", "news.example")

    def _seed(self, target: str, host: str, capability: str = "public-homepage") -> None:
        begun = run(
            BEGIN, "--knowledge-root", str(self.root), "--target", target,
            "--capability", capability, env=self.env,
        )
        self.assertEqual(0, begun.returncode, begun.stderr)
        opened = json.loads(begun.stdout)
        payload = {
            "target": target,
            "capability": capability,
            "observations": [{
                "family": "transport",
                "value": {"transport": "DIRECT_READ", "outcome": "FUNCTIONAL"},
                "host": host,
            }],
            "evidence": [{
                "kind": "direct-read-validation", "locator": f"https://{host}/",
                "scope": "TARGET_SURFACE",
            }],
            # Observed and recorded at the instant the run opened: inside its window.
            "provenance": {"run_id": opened["run_id"], "observed_at": opened["opened_at"]},
            "recorded_at": opened["opened_at"],
        }
        path = self.root.parent / f"{target}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        finalize = run(FINALIZER, "--knowledge-root", str(self.root), "--input", str(path), env=self.env)
        self.assertEqual(0, finalize.returncode, finalize.stderr)
        self.assertEqual("SAVED", json.loads(finalize.stdout)["status"])

    def _seed_pending(self, target: str, capability: str) -> None:
        """A Candidate proposed for ``target`` and never accepted."""
        target_id, capability_id = f"tgt:{target}", f"cap:{target}:{capability}"
        claim_id = f"clm:{target}:{capability}:transport:direct"
        db = self.root / ".caravelaweb/operational_memory.db"
        with SQLiteOperationalMemory(db, knowledge_root=self.root) as memory:
            with memory.write_transaction() as writer:
                writer.capability({"id": capability_id, "target_id": target_id, "key": capability})
                writer.claim({
                    "id": claim_id, "target_id": target_id, "capability_id": capability_id,
                    "family": "transport", "epistemic": "OBSERVED",
                    "value": {"transport": "DIRECT_READ", "outcome": "FUNCTIONAL"},
                    "recorded_at": RECORDED,
                })
                writer.proposal({
                    "id": f"prop:{target}:{capability}:pending", "target_id": target_id,
                    "capability_id": capability_id, "recorded_at": RECORDED,
                    "claim_ids": [claim_id],
                })

    def _raw(self, *arguments: str) -> str:
        result = run(LOOKUP, "--knowledge-root", str(self.root), *arguments, env=self.env)
        self.assertEqual(0, result.returncode, result.stderr)
        return result.stdout

    def _lookup(self, reference: str, capability: str = "public-homepage") -> dict:
        return json.loads(self._raw("--target", reference, "--capability", capability))

    def _standalone_list(self) -> dict:
        result = run(LOOKUP, "--knowledge-root", str(self.root), "--list", env=self.env)
        self.assertEqual(0, result.returncode, result.stderr)
        return json.loads(result.stdout)

    def _seed_many(self, count: int) -> None:
        """``count`` more targets, each with a host, written directly."""
        db = self.root / ".caravelaweb/operational_memory.db"
        with SQLiteOperationalMemory(db, knowledge_root=self.root) as memory:
            with memory.write_transaction() as writer:
                for number in range(count):
                    target = f"filler-{number:02d}"
                    writer.target({"id": f"tgt:{target}", "name": target})
                    writer.host({
                        "id": f"host:{target}:1", "target_id": f"tgt:{target}",
                        "hostname": f"{target}.example",
                    })

    def _finalize(self, payload: dict) -> subprocess.CompletedProcess[str]:
        """Finalize ``payload`` in a run opened at its own ``observed_at``."""
        opened = begin_discovery(
            self.root, payload["target"], payload["capability"],
            opened_at=payload["provenance"]["observed_at"],
        )
        payload["provenance"]["run_id"] = opened["run_id"]
        path = self.root.parent / f"{payload['target']}-{payload['capability']}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return run(FINALIZER, "--knowledge-root", str(self.root), "--input", str(path), env=self.env)

    def _save(self, payload: dict) -> None:
        finalized = self._finalize(payload)
        self.assertEqual(0, finalized.returncode, finalized.stderr)
        self.assertEqual("SAVED", json.loads(finalized.stdout)["status"])

    def _seed_newsdesk(self) -> None:
        """One target with an OPERATIONAL, a blocked and a plain capability."""
        self._save(documented_example(
            "example-operational", target="newsdesk", capability="article-read",
            host="newsdesk.example",
        ))
        self._save(documented_example(
            "example-blocked-ladder", target="newsdesk", capability="site-search",
            host="newsdesk.example",
        ))
        self._seed("newsdesk", "newsdesk.example", "read-homepage-stories")

    def test_a_known_target_returns_its_own_index_row(self) -> None:
        payload = self._lookup("gtolab")
        self.assertEqual("found", payload["status"])
        self.assertEqual("READY", payload["readiness"])
        self.assertEqual("target", payload["index_scope"])
        self.assertEqual("gtolab", payload["index"]["target"])
        self.assertEqual(["gtolab.com"], payload["index"]["hosts"])

    def test_an_unresolved_reference_gets_no_index(self) -> None:
        """A reference no target answers to gets a small, constant reply.

        Disperta passed its own Source IDs (``israelhayom`` for
        ``israel-hayom-he``) and each miss printed 222 KB of index, which
        the agent cut to 1.5 KB and never read.
        """
        arguments = ("--target", "sky-news", "--capability", "public-homepage")
        raw = self._raw(*arguments)
        payload = json.loads(raw)
        self.assertEqual("not_found", payload["status"])
        self.assertEqual("none", payload["index_scope"])
        self.assertEqual("READY", payload["readiness"])
        for absent in ("index", "markdown_projection", "operational_context"):
            self.assertNotIn(absent, payload)
        for other in ("gtolab", "sky-news-world", "news.example"):
            self.assertNotIn(other, raw)
        self.assertLess(len(raw.encode("utf-8")), 512)
        self._seed_many(30)
        self.assertEqual(raw, self._raw(*arguments), "the reply must not grow with the index")
        # --list still shows every exact ID for an executor about to mint one.
        listed = [row["target"] for row in self._standalone_list()["targets"]]
        self.assertIn("sky-news-world", listed)
        self.assertEqual(32, len(listed))

    def test_a_hostname_reference_resolves_without_returning_the_whole_index(self) -> None:
        for reference in ("gtolab.com", "https://www.gtolab.com/path"):
            with self.subTest(reference=reference):
                payload = self._lookup(reference)
                self.assertEqual("found", payload["status"])
                self.assertEqual("target", payload["index_scope"])
                self.assertEqual("gtolab", payload["index"]["target"])

    def test_an_unknown_capability_on_a_known_target_carries_its_profile(self) -> None:
        """A guessed capability ID still reaches the target's accepted knowledge.

        The reference resolved, so no target ID can be minted. The reply
        carries that target's row and its whole profile, byte-equal to the
        profile a hit carries, and nothing about any other target.
        """
        hit = self._lookup("gtolab")
        for reference in ("gtolab", "gtolab.com", "https://www.gtolab.com/path"):
            with self.subTest(reference=reference):
                raw = self._raw("--target", reference, "--capability", "search-results")
                payload = json.loads(raw)
                self.assertEqual("not_found", payload["status"])
                self.assertEqual("target", payload["index_scope"])
                self.assertEqual("gtolab", payload["index"]["target"])
                self.assertEqual(
                    ["public-homepage"],
                    [row["capability"] for row in payload["index"]["capabilities"] if row["accepted"]],
                )
                self.assertNotIn("targets", payload["index"])
                self.assertNotIn("operational_context", payload)
                self.assertEqual(hit["markdown_projection"], payload["markdown_projection"])
                self.assertIn("## Capability: public-homepage", payload["markdown_projection"])
                self.assertIn('"transport":"DIRECT_READ"', payload["markdown_projection"])
                self.assertNotIn("sky-news-world", raw)
                self.assertNotIn("news.example", raw)

    def test_a_miss_shows_every_capability_with_its_verdict(self) -> None:
        """An OPERATIONAL record and a recorded block both reach the executor.

        Plan 011's P2 retried Le Monde's blocked search on every tier because
        the miss listed ``site-search`` without its record (DIRECTION-11).
        """
        self._seed_newsdesk()
        payload = self._lookup("https://newsdesk.example/", "search-results")
        self.assertEqual(("not_found", "target"), (payload["status"], payload["index_scope"]))
        rows = {row["capability"]: row["lifecycle"] for row in payload["index"]["capabilities"]}
        self.assertEqual(
            {"article-read": "OPERATIONAL", "read-homepage-stories": None, "site-search": None}, rows,
        )
        sections = profile_sections(payload["markdown_projection"])
        self.assertEqual(["article-read", "read-homepage-stories", "site-search"], list(sections))
        self.assertIn("- **lifecycle** [OBSERVED]: OPERATIONAL", sections["article-read"])
        self.assertIn("https://newsdesk.example/articles/{id}", sections["article-read"])
        self.assertIn("**blocking**", sections["site-search"])
        self.assertIn("SITE_BLOCKING", sections["site-search"])
        self.assertNotIn("lifecycle", sections["site-search"])
        self.assertIn('"transport":"DIRECT_READ"', sections["read-homepage-stories"])

    def test_a_miss_is_never_larger_than_a_hit_on_the_same_target(self) -> None:
        self._seed_newsdesk()
        miss = self._raw("--target", "newsdesk.example", "--capability", "search-results")
        for capability in ("article-read", "read-homepage-stories", "site-search"):
            with self.subTest(capability=capability):
                hit = self._raw("--target", "newsdesk.example", "--capability", capability)
                self.assertEqual("found", json.loads(hit)["status"])
                self.assertLess(len(miss), len(hit))

    def test_learning_mode_changes_no_lookup_answer_and_writes_nothing(self) -> None:
        self._seed_newsdesk()
        db = self.root / ".caravelaweb/operational_memory.db"
        before = hashlib.sha256(db.read_bytes()).hexdigest()
        disabled = {**self.env, "CARAVELAWEB_LEARNING": "disabled"}
        for arguments in (
            ("--target", "newsdesk.example", "--capability", "search-results"),
            ("--target", "newsdesk", "--capability", "article-read"),
            ("--target", "sky-news", "--capability", "public-homepage"),
        ):
            with self.subTest(arguments=arguments):
                enabled = json.loads(self._raw(*arguments))
                result = run(LOOKUP, "--knowledge-root", str(self.root), *arguments, env=disabled)
                self.assertEqual(0, result.returncode, result.stderr)
                withheld = json.loads(result.stdout)
                self.assertEqual("DISABLED", withheld.pop("learning"))
                self.assertNotIn("learning", enabled)
                self.assertEqual(enabled, withheld)
        self.assertEqual(before, hashlib.sha256(db.read_bytes()).hexdigest())

    def test_a_caller_source_id_misses_and_the_website_hostname_reaches_the_route(self) -> None:
        """The Disperta failure, end to end on synthetic data.

        ``israelhayom`` is a caller's Source ID, not a target ID; the
        website hostname resolves, and a guessed capability ID still
        delivers the accepted search route and its working tier.
        """
        self._save(israel_hayom_search_payload())
        by_source_id = self._lookup("israelhayom", "search-results")
        self.assertEqual(("not_found", "none"), (by_source_id["status"], by_source_id["index_scope"]))
        self.assertNotIn("markdown_projection", by_source_id)
        by_website = self._lookup("https://www.israelhayom.co.il/", "search-results")
        self.assertEqual(("not_found", "target"), (by_website["status"], by_website["index_scope"]))
        self.assertEqual("israel-hayom-he", by_website["index"]["target"])
        search = profile_sections(by_website["markdown_projection"])["search-articles"]
        self.assertIn("https://www.israelhayom.co.il/search?hdyQ={percent-encoded-query}", search)
        self.assertIn('{"outcome":"FUNCTIONAL","transport":"LIGHTPANDA"}', search)
        self.assertIn('{"outcome":"FAILED","transport":"DIRECT_READ"}', search)
        self.assertIn("- **lifecycle** [OBSERVED]: OPERATIONAL", search)

    def test_a_new_source_discovery_still_mints_and_cannot_duplicate_a_known_host(self) -> None:
        """Dropping the whole index from a miss opens no duplicate path.

        A new target is minted after a ``none`` miss and found by its
        hostname afterwards. A brand-name guess for a known target misses,
        its URL resolves, and a finalize that would give the known host to
        a second target is refused.
        """
        self.assertEqual("none", self._lookup("brand-new.example", "read-homepage-stories")["index_scope"])
        self._seed("brand-new", "brand-new.example", "read-homepage-stories")
        found = self._lookup("https://brand-new.example/", "search-results")
        self.assertEqual(("target", "brand-new"), (found["index_scope"], found["index"]["target"]))
        self.assertIn("## Capability: read-homepage-stories", found["markdown_projection"])

        self.assertEqual("none", self._lookup("sky-news")["index_scope"])
        self.assertEqual("sky-news-world", self._lookup("https://news.example/")["index"]["target"])
        duplicate = documented_example(
            "example-operational", target="sky-news", capability="public-homepage",
            host="news.example",
        )
        refused = self._finalize(duplicate)
        self.assertNotEqual(0, refused.returncode, refused.stdout)
        self.assertEqual("HOST_SCOPE", json.loads(refused.stderr)["reason_code"])
        self.assertEqual("none", self._lookup("sky-news")["index_scope"])

    def test_a_pending_only_capability_on_a_known_target_returns_its_row(self) -> None:
        self._seed_pending("gtolab", "site-search")
        payload = self._lookup("gtolab.com", "site-search")
        self.assertEqual("not_found", payload["status"])
        self.assertEqual(
            ["prop:gtolab:site-search:pending"],
            [candidate["proposal_id"] for candidate in payload["pending_candidates"]],
        )
        self.assertEqual("target", payload["index_scope"])
        self.assertEqual("gtolab", payload["index"]["target"])
        rows = {row["capability"]: row for row in payload["index"]["capabilities"]}
        self.assertEqual(
            (False, 1), (rows["site-search"]["accepted"], rows["site-search"]["pending_proposals"]),
        )
        # A pending Candidate is not accepted knowledge: its section is empty.
        sections = profile_sections(payload["markdown_projection"])
        self.assertEqual("", sections["site-search"])
        self.assertIn('"transport":"DIRECT_READ"', sections["public-homepage"])

    def test_status_leads_every_reply(self) -> None:
        """A reader that cuts a long reply short still sees its status."""
        cases = {
            "found": (("--target", "gtolab", "--capability", "public-homepage"),
                      ["status", "target", "capability"]),
            "not_found, target scope": (("--target", "gtolab.com", "--capability", "search-results"),
                                        ["status", "target"]),
            "not_found, none scope": (("--target", "sky-news", "--capability", "public-homepage"),
                                      ["status", "target"]),
            "list": (("--list",), ["status"]),
            "bare target": (("--target", "gtolab"), ["status", "target", "capability"]),
        }
        for name, (arguments, leading) in cases.items():
            with self.subTest(name):
                raw = self._raw(*arguments)
                self.assertTrue(raw.startswith('{"status": '), raw[:80])
                keys = list(json.loads(raw))
                self.assertEqual(leading, keys[:len(leading)])
                bulky = [key for key in ("index", "operational_context", "markdown_projection") if key in keys]
                middle = keys[len(leading):len(keys) - len(bulky)]
                self.assertEqual(sorted(middle), middle)
                self.assertEqual(bulky, keys[len(keys) - len(bulky):], "bulky values go last")
                if "index_scope" in keys and "index" in keys:
                    self.assertLess(keys.index("index_scope"), keys.index("index"))
                self.assertEqual(raw, self._raw(*arguments), "the same call must print the same bytes")
        unresolved = run(LOOKUP, "--target", "gtolab", "--capability", "public-homepage", env=self.env)
        self.assertTrue(unresolved.stdout.startswith('{"status": "unresolved", "target": "gtolab", '))

    def test_an_unresolved_root_reports_readiness_and_no_index(self) -> None:
        result = run(LOOKUP, "--target", "gtolab", "--capability", "public-homepage", env=self.env)
        payload = json.loads(result.stdout)
        self.assertEqual("unresolved", payload["status"])
        self.assertNotEqual("READY", payload["readiness"])
        self.assertNotIn("index", payload)

    def test_a_bare_target_call_keeps_its_shape(self) -> None:
        result = run(LOOKUP, "--knowledge-root", str(self.root), "--target", "gtolab", env=self.env)
        payload = json.loads(result.stdout)
        self.assertEqual("found", payload["status"])
        for added in ("readiness", "index", "index_scope"):
            self.assertNotIn(added, payload)
        self.assertEqual(
            self._lookup("gtolab", "search-results")["markdown_projection"],
            payload["markdown_projection"],
            "the bare call and a miss show one and the same profile",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
