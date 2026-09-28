"""Read-only platform facts used by the portable runtime."""

from __future__ import annotations

import importlib.util
import os
import platform
import stat
import sys
from pathlib import Path
from typing import Mapping

PYTHON_FLOOR = (3, 11)
KNOWLEDGE_ROOT_MARKER = ".caravelaweb-knowledge-root"
TARGETS_DIRECTORY = "targets"
# An advanced, session-scoped override -- e.g. to point at a second
# installation temporarily without disturbing the fixed per-user default.
KNOWLEDGE_ROOT_ENV = "CARAVELAWEB_KNOWLEDGE_ROOT"
# A per-process caller choice: "disabled" means no public command writes to
# the Knowledge Root in this process. Session-scoped like the root override,
# so it never changes what another session may write.
LEARNING_ENV = "CARAVELAWEB_LEARNING"
LEARNING_DISABLED = "LEARNING_DISABLED"  # reason_code on every refusal
_LEARNING_VALUES = {"disabled": "DISABLED", "enabled": "ENABLED"}


class LearningDisabledError(RuntimeError):
    """The caller disabled Knowledge Root writes for this process."""


def _learning_value(environ: Mapping[str, str] | None) -> str:
    environment = os.environ if environ is None else environ
    return environment.get(LEARNING_ENV, "").strip().lower()


def learning_mode(environ: Mapping[str, str] | None = None) -> str:
    """``"DISABLED"`` when the caller set the variable to ``disabled``.

    The value is read case-insensitively after trimming whitespace. Anything
    else, including an unrecognized value, leaves learning ``"ENABLED"``:
    the mode only ever removes writes, so no value can widen what a caller
    allowed, and preflight names an unrecognized value as a warning.
    """
    return "DISABLED" if _learning_value(environ) == "disabled" else "ENABLED"


def unrecognized_learning_value(environ: Mapping[str, str] | None = None) -> str | None:
    """The raw value when it is set, non-empty, and neither known spelling."""
    environment = os.environ if environ is None else environ
    raw = environment.get(LEARNING_ENV)
    if raw is None or not raw.strip() or _learning_value(environ) in _LEARNING_VALUES:
        return None
    return raw


def assert_learning_enabled(environ: Mapping[str, str] | None = None) -> None:
    if learning_mode(environ) == "DISABLED":
        raise LearningDisabledError(
            f"knowledge writes are disabled for this process by {LEARNING_ENV}=disabled"
        )


def configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if reconfigure := getattr(stream, "reconfigure", None):
            reconfigure(encoding="utf-8")


def is_wsl(
    *,
    environ: Mapping[str, str] | None = None,
    proc_version: str | Path = "/proc/version",
    platform_name: str | None = None,
) -> bool:
    if (platform_name or sys.platform) != "linux":
        return False
    environment = os.environ if environ is None else environ
    if environment.get("WSL_DISTRO_NAME"):
        return True
    try:
        return "microsoft" in Path(proc_version).read_text(errors="ignore").lower()
    except OSError:
        return False


def platform_identity() -> dict[str, object]:
    return {
        "sys_platform": sys.platform,
        "os_name": os.name,
        "release": platform.release(),
        "wsl": is_wsl(),
        "python": platform.python_version(),
        "python_executable": sys.executable,
        "python_meets_floor": sys.version_info >= PYTHON_FLOOR,
        "o_nofollow": hasattr(os, "O_NOFOLLOW"),
        "fcntl": importlib.util.find_spec("fcntl") is not None,
        "file_modes_enforced": os.name == "posix",
    }


def _exact_child(parent: Path, name: str, *, directory: bool) -> bool:
    try:
        child = next((item for item in parent.iterdir() if item.name == name), None)
    except OSError:
        return False
    return child is not None and (child.is_dir() if directory else child.is_file())


def validate_knowledge_root(candidate: str | Path) -> Path | None:
    try:
        root = Path(candidate).expanduser().resolve()
    except OSError:
        return None
    return root if root.is_dir() and _exact_child(root, TARGETS_DIRECTORY, directory=True) else None


def _user_app_directory() -> Path:
    """Per-user CaravelaWeb application directory: the default Knowledge Root
    parent. Never the source checkout or a project directory -- purely
    user/installation-owned."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        return (Path(base) if base else Path.home() / "AppData" / "Local") / "CaravelaWeb"
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / "caravelaweb"


def default_knowledge_root() -> Path:
    """The recommended Knowledge Root location when a user makes no explicit choice."""
    return _user_app_directory() / "knowledge-root"


def resolve_knowledge_root(override: str | Path | None = None) -> Path | None:
    """Explicit flag, then session environment variable, then the fixed
    per-user default location. Nothing else.

    Deliberately no persisted pointer and no marker walk-up. A per-user
    pointer file is shared mutable state: any session that initialized a
    root repointed every other session on the machine, including sessions
    of unrelated projects. Walking up from a script's own path resolved the
    source checkout, which must never hold a user's corpus (see
    docs/architecture.md). The default location is derived, not stored, so
    every project resolves the same folder with no state to corrupt.
    """
    if override is not None:
        return validate_knowledge_root(override)
    if env_value := os.environ.get(KNOWLEDGE_ROOT_ENV):
        return validate_knowledge_root(env_value)
    return validate_knowledge_root(default_knowledge_root())


def knowledge_root_marker_present(root: str | Path) -> bool:
    return _exact_child(Path(root), KNOWLEDGE_ROOT_MARKER, directory=False)


def filesystem_class(
    path: str | Path,
    *,
    platform_name: str | None = None,
    wsl: bool | None = None,
) -> str:
    """Classify paths without probing, mounting, or writing to them."""
    name = platform_name or sys.platform
    value = os.fspath(path).replace("\\", "/")
    folded = value.casefold()
    if name == "win32":
        if folded.startswith("//wsl.localhost/") or folded.startswith("//wsl$/"):
            return "boundary-crossing"
        return "network-remote" if value.startswith("//") else "native-local"
    if name == "linux" and (is_wsl() if wsl is None else wsl):
        parts = Path(value).parts
        if len(parts) > 2 and parts[1] == "mnt" and len(parts[2]) == 1:
            return "boundary-crossing"
    if value.startswith("//"):
        return "network-remote"
    return "native-local" if name in {"linux", "darwin"} else "unknown"


def safe_marker_stat(value: object) -> bool:
    """Accept only a regular, singly linked, non-reparse marker."""
    return (
        stat.S_ISREG(getattr(value, "st_mode", 0))
        and getattr(value, "st_nlink", 0) == 1
        and not (
            getattr(value, "st_file_attributes", 0)
            & stat.FILE_ATTRIBUTE_REPARSE_POINT
        )
    )


__all__ = [
    "KNOWLEDGE_ROOT_ENV",
    "LEARNING_DISABLED",
    "LEARNING_ENV",
    "LearningDisabledError",
    "PYTHON_FLOOR",
    "assert_learning_enabled",
    "configure_utf8_stdio",
    "default_knowledge_root",
    "filesystem_class",
    "is_wsl",
    "knowledge_root_marker_present",
    "learning_mode",
    "platform_identity",
    "resolve_knowledge_root",
    "safe_marker_stat",
    "unrecognized_learning_value",
    "validate_knowledge_root",
]
