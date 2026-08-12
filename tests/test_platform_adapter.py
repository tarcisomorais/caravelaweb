from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))

from platform_adapter import (
    KNOWLEDGE_ROOT_ENV,
    configured_knowledge_root_file,
    default_knowledge_root,
    filesystem_class,
    is_wsl,
    platform_identity,
    read_configured_knowledge_root,
    resolve_knowledge_root,
    validate_knowledge_root,
    write_configured_knowledge_root,
)


class PlatformAdapterTests(unittest.TestCase):
    def test_wsl_requires_linux_and_detects_environment(self) -> None:
        self.assertTrue(
            is_wsl(
                environ={"WSL_DISTRO_NAME": "Ubuntu"},
                proc_version="/missing",
                platform_name="linux",
            )
        )
        self.assertFalse(
            is_wsl(environ={"WSL_DISTRO_NAME": "Ubuntu"}, platform_name="win32")
        )

    def test_filesystem_classes(self) -> None:
        cases = (
            ("C:\\data", "win32", False, "native-local"),
            ("\\\\server\\share", "win32", False, "network-remote"),
            ("\\\\wsl.localhost\\Ubuntu\\home", "win32", False, "boundary-crossing"),
            ("/mnt/c/data", "linux", True, "boundary-crossing"),
            ("/home/user/data", "linux", True, "native-local"),
            ("/Users/user/data", "darwin", False, "native-local"),
        )
        for path, name, wsl, expected in cases:
            with self.subTest(path=path):
                self.assertEqual(
                    expected,
                    filesystem_class(path, platform_name=name, wsl=wsl),
                )

    def test_identity_reports_the_declared_floor_and_features(self) -> None:
        identity = platform_identity()
        self.assertEqual(sys.platform, identity["sys_platform"])
        self.assertEqual(sys.version_info >= (3, 11), identity["python_meets_floor"])
        self.assertIsInstance(identity["fcntl"], bool)
        self.assertIsInstance(identity["o_nofollow"], bool)

    def test_root_requires_exact_targets_case(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Targets").mkdir()
            self.assertIsNone(validate_knowledge_root(root))

    def test_env_var_lets_a_selected_root_be_reused_without_an_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "targets").mkdir()
            with patch.dict("os.environ", {KNOWLEDGE_ROOT_ENV: str(root)}, clear=True):
                self.assertEqual(root.resolve(), resolve_knowledge_root(start=root))
            # Without the env var (and with no marker to walk up to), unresolved.
            with patch.dict("os.environ", {}, clear=True), patch(
                "platform_adapter.read_configured_knowledge_root", return_value=None
            ):
                self.assertIsNone(resolve_knowledge_root(start=root))

    def test_explicit_override_wins_over_the_env_var(self) -> None:
        with tempfile.TemporaryDirectory() as env_directory, tempfile.TemporaryDirectory() as override_directory:
            env_root, override_root = Path(env_directory), Path(override_directory)
            (env_root / "targets").mkdir()
            (override_root / "targets").mkdir()
            with patch.dict("os.environ", {KNOWLEDGE_ROOT_ENV: str(env_root)}, clear=False):
                self.assertEqual(override_root.resolve(), resolve_knowledge_root(override_root))

    def test_env_var_pointing_at_an_invalid_root_resolves_to_none(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict("os.environ", {KNOWLEDGE_ROOT_ENV: directory}, clear=False):
                self.assertIsNone(resolve_knowledge_root())


class PersistedDefaultRootTests(unittest.TestCase):
    """The per-user default Knowledge Root location and its remembered pointer."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "home"
        self._patch = patch.dict(
            "os.environ",
            {
                "HOME": str(self.home),
                "USERPROFILE": str(self.home),
                # On native Windows, _user_app_directory() reads LOCALAPPDATA,
                # not HOME/USERPROFILE -- without isolating it too, these
                # tests read and write this machine's real per-user pointer
                # file instead of a disposable one, and pollute each other.
                "LOCALAPPDATA": str(self.home / "AppData" / "Local"),
            },
            clear=False,
        )
        self._patch.start()
        self.addCleanup(self._patch.stop)
        os.environ.pop("XDG_DATA_HOME", None)
        os.environ.pop(KNOWLEDGE_ROOT_ENV, None)

    # Mirrors the native-Windows note below, in the opposite direction:
    # patching platform_adapter.os.name to "posix" only fools the branch
    # *selection* in _user_app_directory(); Path.home() underneath still
    # picks WindowsPath vs. PosixPath from the real interpreter platform,
    # which pathlib refuses to instantiate as PosixPath on real Windows
    # (NotImplementedError) -- observed failing on the hosted windows-latest
    # CI runner. There is no way to unit-test the posix branch from there.
    @unittest.skipIf(os.name == "nt", "posix branch cannot be simulated on a native-Windows interpreter")
    def test_default_location_is_under_the_users_own_app_directory_posix(self) -> None:
        with patch("platform_adapter.os.name", "posix"):
            self.assertEqual(
                self.home / ".local" / "share" / "caravelaweb" / "knowledge-root",
                default_knowledge_root(),
            )

    @unittest.skipIf(os.name == "nt", "posix branch cannot be simulated on a native-Windows interpreter")
    def test_default_location_respects_xdg_data_home_when_set(self) -> None:
        xdg = Path(self.temp.name) / "custom-data"
        with patch("platform_adapter.os.name", "posix"), patch.dict("os.environ", {"XDG_DATA_HOME": str(xdg)}):
            self.assertEqual(xdg / "caravelaweb" / "knowledge-root", default_knowledge_root())

    # The native-Windows branch (os.name == "nt") constructs a real
    # WindowsPath, which pathlib refuses to instantiate on a POSIX
    # interpreter (NotImplementedError) -- there is no way to unit-test it
    # from here. Like filesystem_class's win32 cases, that branch is proven
    # by the real native-Windows CI runner (tests/windows_real_task_exercise.py),
    # not a simulated unit test.

    def test_configured_root_file_is_distinct_from_the_default_data_directory(self) -> None:
        # The pointer file and the default Knowledge Root data directory
        # must never collide -- os.replace()-ing the pointer must not clobber
        # (or be blocked by) an actual installation directory of the same name.
        self.assertNotEqual(default_knowledge_root(), configured_knowledge_root_file())
        self.assertEqual(default_knowledge_root().parent, configured_knowledge_root_file().parent)

    def test_write_then_read_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as other:
            root = Path(other)
            self.assertIsNone(read_configured_knowledge_root())
            write_configured_knowledge_root(root)
            self.assertEqual(root, read_configured_knowledge_root())
            # A later init overwrites the remembered choice, it does not merge.
            second = Path(other) / "elsewhere"
            write_configured_knowledge_root(second)
            self.assertEqual(second, read_configured_knowledge_root())

    def test_resolve_falls_back_to_the_persisted_default_below_the_env_var(self) -> None:
        with tempfile.TemporaryDirectory() as configured, tempfile.TemporaryDirectory() as via_env:
            configured_root, env_root = Path(configured), Path(via_env)
            (configured_root / "targets").mkdir()
            (env_root / "targets").mkdir()
            write_configured_knowledge_root(configured_root)

            # No override, no env var: the persisted default resolves.
            self.assertEqual(configured_root.resolve(), resolve_knowledge_root(start=self.home))

            # The env var still wins over the persisted default when set.
            with patch.dict("os.environ", {KNOWLEDGE_ROOT_ENV: str(env_root)}):
                self.assertEqual(env_root.resolve(), resolve_knowledge_root(start=self.home))

            # An explicit override always wins over both.
            self.assertEqual(
                env_root.resolve(), resolve_knowledge_root(env_root, start=self.home)
            )

    def test_resolve_ignores_a_persisted_pointer_at_a_no_longer_valid_location(self) -> None:
        with tempfile.TemporaryDirectory() as gone:
            write_configured_knowledge_root(Path(gone) / "moved-away")
            self.assertIsNone(resolve_knowledge_root(start=self.home))


if __name__ == "__main__":
    unittest.main()
