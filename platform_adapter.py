"""Read-only platform facts used by the portable runtime."""

from __future__ import annotations

import importlib.util
import os
import platform
import stat
import sys
import tempfile
from pathlib import Path
from typing import Mapping

PYTHON_FLOOR = (3, 11)
KNOWLEDGE_ROOT_MARKER = ".caravelaweb-knowledge-root"
TARGETS_DIRECTORY = "targets"
# An advanced, session-scoped override -- e.g. to point at a second
# installation temporarily without disturbing the remembered default below.
KNOWLEDGE_ROOT_ENV = "CARAVELAWEB_KNOWLEDGE_ROOT"
# Distinct from default_knowledge_root()'s "knowledge-root" data directory,
# both under the same per-user app directory.
_CONFIGURED_ROOT_FILE_NAME = "config"


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
    """Per-user CaravelaWeb application directory: default Knowledge Root
    parent and home for the remembered-root pointer file. Never the source
    checkout or a project directory -- purely user/installation-owned."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        return (Path(base) if base else Path.home() / "AppData" / "Local") / "CaravelaWeb"
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / "caravelaweb"


def default_knowledge_root() -> Path:
    """The recommended Knowledge Root location when a user makes no explicit choice."""
    return _user_app_directory() / "knowledge-root"


def configured_knowledge_root_file() -> Path:
    """Where the remembered Knowledge Root choice is persisted across sessions."""
    return _user_app_directory() / _CONFIGURED_ROOT_FILE_NAME


def read_configured_knowledge_root() -> Path | None:
    path = configured_knowledge_root_file()
    try:
        marker_stat = os.lstat(path)
    except OSError:
        return None
    if not safe_marker_stat(marker_stat):
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return Path(text) if text else None


def write_configured_knowledge_root(root: str | Path) -> Path:
    """Remember ``root`` as the default Knowledge Root for future sessions."""
    path = configured_knowledge_root_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temporary = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(f"{Path(root)}\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def resolve_knowledge_root(
    override: str | Path | None = None, *, start: str | Path | None = None
) -> Path | None:
    if override is not None:
        return validate_knowledge_root(override)
    if env_value := os.environ.get(KNOWLEDGE_ROOT_ENV):
        return validate_knowledge_root(env_value)
    if (configured := read_configured_knowledge_root()) is not None:
        if resolved := validate_knowledge_root(configured):
            return resolved
    origin = Path(start or __file__).resolve()
    for parent in origin.parents:
        if _exact_child(parent, KNOWLEDGE_ROOT_MARKER, directory=False):
            return validate_knowledge_root(parent)
    return None


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
    "PYTHON_FLOOR",
    "configure_utf8_stdio",
    "configured_knowledge_root_file",
    "default_knowledge_root",
    "filesystem_class",
    "is_wsl",
    "knowledge_root_marker_present",
    "platform_identity",
    "read_configured_knowledge_root",
    "resolve_knowledge_root",
    "safe_marker_stat",
    "validate_knowledge_root",
    "write_configured_knowledge_root",
]
