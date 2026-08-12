"""Public runtime import closure, proven mechanically.

The repository root is the CaravelaWeb skill root, so the runtime modules sit
directly beside `scripts/`. This test walks the import graph outward from the
four public runtime CLI entry points and asserts the reachable set is exactly
the eleven runtime modules this repository ships -- no more, no fewer.

`scripts/register-host` is a separate concern (host discovery registration,
not Knowledge Root/Operational Memory runtime -- see docs/architecture.md)
with its own single-module closure, walked and asserted independently.

Together, this also proves that no unreachable Python module sits at the
runtime level: a file that nothing imports cannot ship unnoticed.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO
SCRIPTS = SKILL / "scripts"

# The §2.2 runtime lock: exactly these 11 Python runtime modules.
EXPECTED_RUNTIME_CLOSURE = {
    "discovery_finalize",
    "installation_init",
    "integration_bridge",
    "knowledge_write_freeze",
    "om_native_writes",
    "operational_memory",
    "operational_memory.core",
    "platform_adapter",
    "read_authority",
    "transport_policy",
    "write_authority",
}

# Host registration shares only the platform-facts module with the runtime
# closure above; it never imports Knowledge Root or Operational Memory code.
EXPECTED_REGISTRATION_CLOSURE = {"host_registration", "platform_adapter"}


def module_name(path: Path) -> str:
    relative = path.relative_to(SKILL).with_suffix("")
    parts = relative.parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def walk_closure(modules: dict[str, Path], entry_points: list[Path]) -> set[str]:
    pending = list(entry_points)
    reached: set[str] = set()
    while pending:
        path = pending.pop()
        current = module_name(path) if path.suffix == ".py" else ""
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                package = current if path.name == "__init__.py" else current.rpartition(".")[0]
                names = [f"{package}.{node.module}" if node.level else node.module]
            for name in names:
                if name in modules and name not in reached:
                    reached.add(name)
                    pending.append(modules[name])
    return reached


class PublicRuntimeBoundaryTests(unittest.TestCase):
    def test_public_runtime_import_closure_is_exact(self) -> None:
        modules = {
            module_name(path): path
            for path in SKILL.rglob("*.py")
            if "scripts" not in path.parts and "tests" not in path.parts
        }
        runtime_reached = walk_closure(
            modules,
            [
                SCRIPTS / name
                for name in ("knowledge-lookup", "discovery-finalize", "preflight", "init-knowledge-root")
            ],
        )
        entered = runtime_reached - EXPECTED_RUNTIME_CLOSURE
        left = EXPECTED_RUNTIME_CLOSURE - runtime_reached
        self.assertEqual(
            EXPECTED_RUNTIME_CLOSURE,
            runtime_reached,
            f"public runtime import closure mismatch: entered={sorted(entered)} left={sorted(left)}",
        )

        registration_reached = walk_closure(modules, [SCRIPTS / "register-host"])
        self.assertEqual(
            EXPECTED_REGISTRATION_CLOSURE,
            registration_reached,
            f"host registration import closure mismatch: {sorted(registration_reached)}",
        )

        unreachable = set(modules) - runtime_reached - registration_reached
        self.assertEqual(
            set(),
            unreachable,
            f"runtime modules present but reachable from no public CLI: {sorted(unreachable)}",
        )


if __name__ == "__main__":
    unittest.main()
