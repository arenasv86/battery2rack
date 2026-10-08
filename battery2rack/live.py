"""Locate the Ableton Live installation whose factory presets we use as templates.

Ableton's presets are not redistributed with this tool: they are read from the
user's own Live installation (Live 12.1 or newer for Drum Sampler).
"""
from __future__ import annotations

import glob
import os
import re
import sys

ENV_VAR = "BATTERY2RACK_LIVE"


def _core_from(path: str) -> str | None:
    """Accept a Live .app, a Windows install folder or a Core Library folder."""
    for cand in (path,
                 os.path.join(path, "Contents", "App-Resources", "Core Library"),  # macOS .app
                 os.path.join(path, "Resources", "Core Library")):                 # Windows
        if os.path.isdir(os.path.join(cand, "Defaults")):
            return cand
    return None


def _rank(path: str) -> tuple:
    """Newest version first; Suite > Standard > Intro/Lite for equal versions."""
    name = os.path.basename(path.rstrip("/\\"))
    m = re.search(r"Live (\d+)", name)
    version = int(m.group(1)) if m else 0
    edition = next((i for i, e in enumerate(("Lite", "Intro", "Standard", "Suite")) if e in name), -1)
    return (version, edition)


def candidates() -> list[str]:
    if sys.platform == "darwin":
        patterns = ["/Applications/Ableton Live 1*.app", os.path.expanduser("~/Applications/Ableton Live 1*.app")]
    elif sys.platform.startswith("win"):
        root = os.environ.get("ProgramData", r"C:\ProgramData")
        patterns = [os.path.join(root, "Ableton", "Live 1*")]
    else:
        patterns = []
    found = [p for pat in patterns for p in glob.glob(pat)]
    return sorted(found, key=_rank, reverse=True)


def find_core_library(explicit: str | None = None) -> str:
    """Return the path to Live's 'Core Library' folder, or raise with a helpful message."""
    for path in [explicit, os.environ.get(ENV_VAR)] + candidates():
        if path:
            core = _core_from(path)
            if core:
                return core
            if path in (explicit, os.environ.get(ENV_VAR)):
                raise FileNotFoundError(f"No Ableton Live Core Library found in: {path}")
    raise FileNotFoundError(
        "Ableton Live 12 was not found. Pass its location with --live "
        f"(or set {ENV_VAR}), e.g. --live '/Applications/Ableton Live 12 Suite.app'")
