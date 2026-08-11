from __future__ import annotations

import stat
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))

import knowledge_write_freeze
import read_authority
import write_authority
from platform_adapter import safe_marker_stat


def marker_stat(*, links: int = 1, reparse: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        st_mode=stat.S_IFREG | 0o600,
        st_nlink=links,
        st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT if reparse else 0,
    )


class MarkerParityTests(unittest.TestCase):
    def test_shared_check_rejects_missing_metadata(self) -> None:
        self.assertFalse(safe_marker_stat(SimpleNamespace(st_mode=stat.S_IFREG)))

    def test_read_authority_rejects_reparse_points(self) -> None:
        with patch.object(read_authority.os, "lstat", return_value=marker_stat(reparse=True)):
            with self.assertRaisesRegex(
                read_authority.ReadAuthorityStateError, "unsafe read-authority marker"
            ):
                read_authority.read_cutover_active("root")

    def test_write_authority_rejects_multiple_links(self) -> None:
        with patch.object(write_authority.os, "lstat", return_value=marker_stat(links=2)):
            with self.assertRaisesRegex(
                write_authority.WriteAuthorityStateError,
                "unsafe write-authority marker",
            ):
                write_authority.current_write_authority("root")

    def test_freeze_marker_fails_closed_for_reparse_points(self) -> None:
        with patch.object(
            knowledge_write_freeze.os,
            "lstat",
            return_value=marker_stat(reparse=True),
        ):
            with self.assertRaisesRegex(
                knowledge_write_freeze.KnowledgeWriteFrozenError,
                "knowledge write freeze active \(unexpected marker\)",
            ):
                knowledge_write_freeze.assert_knowledge_writes_allowed("root")


if __name__ == "__main__":
    unittest.main()
