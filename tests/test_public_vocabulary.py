"""The public vocabulary stays English.

CaravelaWeb once reported Discovery finalization with Portuguese statuses,
JSON keys, and reason codes. Those identifiers were retired before the first
public release. This gate keeps them from returning through a copied example,
a reverted edit, or a merge.

It is a targeted identifier gate, never a "no Unicode" rule: CaravelaWeb reads
international sites, and non-English page content in test data is legitimate.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Retired identifier -> the English identifier that replaced it.
RETIRED = {
    # statuses
    "SALVA": "SAVED",
    "JÁ_EXISTENTE": "ALREADY_EXISTS",
    "NÃO_SALVA": "NOT_SAVED",
    # JSON keys
    "motivo": "reason",
    "motivo_codigo": "reason_code",
    # reason codes
    "JA_PENDENTE": "ALREADY_PENDING",
    "APENAS_INFERENCIA": "INFERENCE_ONLY",
    "SUBSTITUICAO_NAO_COMPROVADA": "REPLACEMENT_UNPROVEN",
    "CONFLITO_OU_AMBIGUIDADE": "CONFLICT_OR_AMBIGUITY",
    "CONFIRMACAO_PENDENTE": "CONFIRMATION_PENDING",
    "EVIDENCIA_BILATERAL_INSUFICIENTE": "INSUFFICIENT_BILATERAL_EVIDENCE",
    "BASELINE_MATERIAL_INSUFICIENTE": "INSUFFICIENT_MATERIAL_BASELINE",
    "CONTEXTO_MATERIAL_INCOMPARAVEL": "INCOMPARABLE_MATERIAL_CONTEXT",
    "SEM_CONHECIMENTO_REUTILIZAVEL": "NO_REUSABLE_KNOWLEDGE",
}

# This file names every retired identifier by definition, so it excludes only
# itself. Every other tracked file is scanned with no exclusion.
SELF = Path(__file__).relative_to(REPO).as_posix()

STATUSES = ("SAVED", "ALREADY_EXISTS", "NOT_SAVED")


def tracked_text_files() -> list[Path]:
    names = subprocess.run(
        ["git", "-C", str(REPO), "ls-files"],
        text=True, capture_output=True, check=True,
    ).stdout.split()
    return [REPO / name for name in names if name != SELF]


class PublicVocabularyTests(unittest.TestCase):
    def test_no_tracked_file_reintroduces_a_retired_identifier(self) -> None:
        offenders: list[str] = []
        for path in tracked_text_files():
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for retired, replacement in RETIRED.items():
                if retired in text:
                    relative = path.relative_to(REPO).as_posix()
                    offenders.append(f"{relative}: {retired} -> use {replacement}")
        self.assertEqual([], sorted(offenders))

    def test_runtime_emits_only_the_english_statuses(self) -> None:
        source = (REPO / "discovery_finalize.py").read_text(encoding="utf-8")
        emitted = set(re.findall(r'DiscoveryFinalization\(\s*"([A-Z_]+)"', source))
        emitted |= set(re.findall(r'"([A-Z_]+)", target, capability', source))
        self.assertTrue(emitted, "no finalization status literal found")
        self.assertEqual(set(), emitted - set(STATUSES), f"unexpected status: {emitted}")

    def test_refusal_output_uses_the_english_keys(self) -> None:
        source = (REPO / "discovery_finalize.py").read_text(encoding="utf-8")
        self.assertIn('result["reason"]', source)
        self.assertIn('result["reason_code"]', source)


if __name__ == "__main__":
    unittest.main()
