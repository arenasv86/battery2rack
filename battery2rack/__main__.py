"""battery2rack: convert Native Instruments Battery 4 kits into Ableton Live Drum Racks."""
from __future__ import annotations

import argparse
import sys

from . import __version__
from .adg import DEFAULT_DEVICE, DEFAULT_VOLUME_DB, DEVICES
from .convert import convert, find_kits
from .paths import default_output_dir


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(
        prog="battery2rack",
        description="Convert Battery 4 kits (.nbkt) into Ableton Live Drum Racks (.adg).",
        epilog="examples:\n"
               "  battery2rack /Users/Shared\n"
               "  battery2rack \"My Kit.nbkt\" -o ~/Desktop --device simpler --volume -9\n\n"
               "Tip: type 'battery2rack ' and drag a folder from Finder onto the terminal.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", nargs="+", help=".nbkt files or folders (searched recursively)")
    ap.add_argument("-o", "--output", default=default_output_dir(),
                    help="output folder (default: %(default)s)")
    ap.add_argument("-d", "--device", choices=list(DEVICES), default=DEFAULT_DEVICE,
                    help="instrument used on each pad (default: %(default)s)")
    ap.add_argument("--volume", type=float, default=DEFAULT_VOLUME_DB, metavar="DB",
                    help="output volume of every pad in dB (default: %(default)s)")
    ap.add_argument("--choke", action="store_true",
                    help="map Battery's cell group to Choke Group (experimental)")
    ap.add_argument("--live", metavar="PATH", help="Ableton Live location, if not auto-detected")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    if not argv:
        ap.print_help()
        return 0
    args = ap.parse_args(argv)

    if not find_kits(args.input):
        print("No .nbkt kits found in the given paths.", file=sys.stderr)
        return 1

    def progress(i, total, res):
        if res.error:
            print(f"[{i}/{total}] ✗ {res.source}: {res.error}", file=sys.stderr)
        else:
            print(f"[{i}/{total}] ✓ {res.output} ({res.pads} pads)")

    try:
        results = convert(args.input, args.output, device=args.device, volume_db=args.volume,
                          choke=args.choke, live=args.live, progress=progress)
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 1
    errors = sum(1 for r in results if r.error)
    print(f"\n{len(results) - errors} kits converted, {errors} errors -> {args.output}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
