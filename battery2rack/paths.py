"""Default folders."""
from __future__ import annotations

import os
import sys


def user_library() -> str:
    if sys.platform.startswith("win"):
        return os.path.expanduser(os.path.join("~", "Documents", "Ableton", "User Library"))
    return os.path.expanduser(os.path.join("~", "Music", "Ableton", "User Library"))


def default_output_dir() -> str:
    """Inside the Ableton User Library, so the racks show up in Live's browser."""
    lib = user_library()
    if os.path.isdir(lib):
        return os.path.join(lib, "Presets", "Instruments", "Drum Rack", "Battery Kits")
    return os.path.join(os.path.expanduser("~"), "Battery Drum Racks")

