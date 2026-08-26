"""One-time global registration of this checkout with a supported agent
host's personal skill-discovery directory.

Registration manages a single link (a POSIX symlink or a Windows junction)
at the host's per-user skill path, pointing at this repository root. It
never copies runtime files, never touches Knowledge Root state, never
installs browser dependencies, and never modifies a consumer repository.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
SUPPORTED_HOSTS = ("claude", "codex", "opencode")


class RegistrationError(RuntimeError):
    """Registration cannot proceed safely; nothing was changed."""


@dataclass(frozen=True)
class RegistrationResult:
    status: str  # ALREADY_REGISTERED, REGISTERED, or RELINKED
    link: Path
    target: Path


def _host_skills_directory(host: str) -> Path:
    if host == "claude":
        return Path.home() / ".claude" / "skills"
    if host == "codex":
        return Path.home() / ".agents" / "skills"
    if host == "opencode":
        return Path.home() / ".config" / "opencode" / "skills"
    raise RegistrationError(f"unsupported host: {host} (supported: {', '.join(SUPPORTED_HOSTS)})")


def strip_extended_path_prefix(raw: str) -> str:
    """``raw`` without any Windows extended-length prefix.

    ``os.readlink`` reports a junction or an absolute Windows symlink as
    ``\\\\?\\C:\\...`` (or ``\\\\?\\UNC\\server\\share\\...``). The prefix is
    transport syntax, not path identity; keeping it makes an equal path
    compare unequal and a correct registration classify as CONFLICT.
    """
    if raw.startswith("\\\\?\\UNC\\"):
        return "\\\\" + raw[len("\\\\?\\UNC\\"):]
    if raw.startswith("\\\\?\\"):
        return raw[len("\\\\?\\"):]
    return raw


def _reparse_target(link: Path) -> Path | None:
    """The recorded target of ``link``, a POSIX symlink or Windows junction.

    Raises RegistrationError if ``link`` exists but is a plain file or
    directory, since that path must never be silently touched. Returns None
    only when the link itself cannot be read (a corrupt reparse point).
    """
    result = os.lstat(link)
    is_link_like = stat.S_ISLNK(result.st_mode) or bool(
        getattr(result, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )
    if not is_link_like:
        raise RegistrationError(
            f"refusing to touch existing path that is not a CaravelaWeb registration link: {link}"
        )
    try:
        return Path(strip_extended_path_prefix(os.readlink(link)))
    except OSError:
        return None


def _same_directory(left: Path, right: Path) -> bool:
    """Case-normalized, fully resolved path equality."""
    return os.path.normcase(os.path.realpath(left)) == os.path.normcase(os.path.realpath(right))


def _create_link(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


def registration_state(host: str) -> dict[str, object]:
    """Read-only classification of the current registration for ``host``.

    ``state`` is one of ABSENT, REGISTERED, CONFLICT, or DANGLING.
    """
    link = _host_skills_directory(host) / "caravelaweb"
    target = REPO_ROOT
    try:
        os.lstat(link)
    except OSError:
        return {"state": "ABSENT", "link": link, "target": target, "points_to": None}

    points_to = _reparse_target(link)
    if points_to is None or not points_to.is_dir():
        return {"state": "DANGLING", "link": link, "target": target, "points_to": points_to}
    if _same_directory(points_to, target):
        return {"state": "REGISTERED", "link": link, "target": target, "points_to": points_to}
    return {"state": "CONFLICT", "link": link, "target": target, "points_to": points_to}


def register(host: str, *, relink: bool = False) -> RegistrationResult:
    """Register this checkout as the global ``host`` skill.

    Idempotent when already correctly registered. A conflicting or dangling
    existing link is only replaced with ``relink=True``; a plain file or
    directory at the link path is never replaced, with or without ``relink``.
    """
    info = registration_state(host)
    link, target, state = info["link"], info["target"], info["state"]

    if state == "REGISTERED":
        return RegistrationResult(status="ALREADY_REGISTERED", link=link, target=target)
    if state in ("CONFLICT", "DANGLING"):
        if not relink:
            detail = f"points to {info['points_to']}" if state == "CONFLICT" else "target is missing"
            raise RegistrationError(
                f"existing registration at {link} is {state} ({detail}); rerun with --relink to repair"
            )
        link.unlink()
        _create_link(link, target)
        return RegistrationResult(status="RELINKED", link=link, target=target)

    _create_link(link, target)
    return RegistrationResult(status="REGISTERED", link=link, target=target)


__all__ = [
    "REPO_ROOT",
    "SUPPORTED_HOSTS",
    "RegistrationError",
    "RegistrationResult",
    "register",
    "registration_state",
    "strip_extended_path_prefix",
]
