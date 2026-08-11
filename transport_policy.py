"""Capability-scoped transport ordering with knowledge-free platform limits."""

from __future__ import annotations

from typing import Mapping

AVAILABLE = "AVAILABLE"
UNAVAILABLE = "UNAVAILABLE"
PLATFORM_UNSUPPORTED = "PLATFORM_UNSUPPORTED"
SATISFIED = "SATISFIED"
INSUFFICIENT = "INSUFFICIENT"

DIRECT_READ = "DIRECT_READ"
LIGHTPANDA = "LIGHTPANDA"
CHROME = "CHROME"

BROWSER_TRANSPORTS = frozenset({LIGHTPANDA, CHROME})


class TransportPolicyError(ValueError):
    """Transport history violates the frozen hierarchy."""


def next_transport(
    attempts: Mapping[str, str], availability: Mapping[str, str]
) -> str | None:
    if any(name in attempts for name in (LIGHTPANDA, CHROME)) and DIRECT_READ not in attempts:
        raise TransportPolicyError("DIRECT_READ must be attempted first")
    if DIRECT_READ not in attempts:
        return DIRECT_READ
    if attempts[DIRECT_READ] == SATISFIED:
        return None
    if attempts[DIRECT_READ] != INSUFFICIENT:
        raise TransportPolicyError("DIRECT_READ outcome must be SATISFIED or INSUFFICIENT")

    lightpanda = availability.get(LIGHTPANDA, UNAVAILABLE)
    if lightpanda == AVAILABLE:
        if LIGHTPANDA not in attempts:
            return LIGHTPANDA
        if attempts[LIGHTPANDA] == SATISFIED:
            return None
        if attempts[LIGHTPANDA] != INSUFFICIENT:
            raise TransportPolicyError("LIGHTPANDA outcome must be SATISFIED or INSUFFICIENT")
    elif lightpanda != PLATFORM_UNSUPPORTED:
        return None

    if availability.get(CHROME, UNAVAILABLE) != AVAILABLE or CHROME in attempts:
        return None
    return CHROME


def simplify_transports(availability: Mapping[str, str]) -> tuple[str, ...]:
    """Return the simpler transports that physically exist for SIMPLIFY."""
    return (DIRECT_READ,) + (
        (LIGHTPANDA,) if availability.get(LIGHTPANDA) == AVAILABLE else ()
    )


def platform_limit_report(target: str, transport: str, platform: str) -> dict[str, object]:
    return {
        "classification": PLATFORM_UNSUPPORTED,
        "transport": transport,
        "platform": platform,
        "target": target,
        "target_degraded": False,
        "knowledge_observations": [],
        "message": (
            f"{transport} is unavailable on {platform}; "
            f"target {target} is not degraded"
        ),
    }


__all__ = [
    "AVAILABLE",
    "BROWSER_TRANSPORTS",
    "CHROME",
    "DIRECT_READ",
    "INSUFFICIENT",
    "LIGHTPANDA",
    "PLATFORM_UNSUPPORTED",
    "SATISFIED",
    "TransportPolicyError",
    "UNAVAILABLE",
    "next_transport",
    "platform_limit_report",
    "simplify_transports",
]
