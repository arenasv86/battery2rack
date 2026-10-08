"""Batch conversion shared by the command line and the GUI."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Iterable

from .adg import DEFAULT_DEVICE, DEFAULT_VOLUME_DB, build_rack, write_adg
from .live import find_core_library
from .nbkt import read_kit


@dataclass
class Result:
    source: str
    output: str | None = None
    pads: int = 0
    error: str | None = None


def find_kits(paths: Iterable[str]) -> list[str]:
    """Expand files and folders (recursively) into a sorted list of .nbkt files."""
    kits = []
    for p in paths:
        if os.path.isdir(p):
            for dp, dirs, fs in os.walk(p):
                dirs.sort()
                kits += [os.path.join(dp, f) for f in sorted(fs)
                         if f.lower().endswith(".nbkt") and not f.startswith("._")]
        elif p.lower().endswith(".nbkt"):
            kits.append(p)
    return kits


def _output_path(out_dir: str, kit_path: str, used: set[str]) -> str:
    """<out>/<Kit>.adg; on a name clash, add the library name: <Kit> (<Library>).adg"""
    name = os.path.splitext(os.path.basename(kit_path))[0]
    path = os.path.join(out_dir, name + ".adg")
    if path in used:
        parts = os.path.normpath(kit_path).split(os.sep)
        lib = next((d for d in reversed(parts[:-1]) if d.endswith("Library")), parts[-2])
        path = os.path.join(out_dir, f"{name} ({lib}).adg")
        n = 2
        while path in used:
            path = os.path.join(out_dir, f"{name} ({lib} {n}).adg"); n += 1
    used.add(path)
    return path


def convert(paths: Iterable[str], out_dir: str, device: str = DEFAULT_DEVICE,
            volume_db: float = DEFAULT_VOLUME_DB, choke: bool = False, live: str | None = None,
            progress: Callable[[int, int, Result], None] | None = None,
            cancelled: Callable[[], bool] = lambda: False) -> list[Result]:
    core = find_core_library(live)
    kits = find_kits(paths)
    results, used = [], set()
    for i, kit_path in enumerate(kits):
        if cancelled():
            break
        res = Result(kit_path)
        try:
            kit = read_kit(kit_path)
            out = _output_path(out_dir, kit_path, used)
            write_adg(build_rack(kit, core, device=device, choke=choke, volume_db=volume_db), out)
            res.output, res.pads = out, sum(1 for c in kit.cells if c.zones)
        except Exception as e:  # keep going with the rest of the batch
            res.error = f"{type(e).__name__}: {e}"
        results.append(res)
        if progress:
            progress(i + 1, len(kits), res)
    return results
