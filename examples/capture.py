"""
Capture N raw fingerprint scans from the U.are.U reader and save them as PNGs.

Usage:
    python examples/capture.py --count 5 --out captures/finger

Produces: captures/finger_0.png, captures/finger_1.png, ...
"""
import utils.transport
import utils.session
import argparse
import logging
import sys
from pathlib import Path

# Make repo root importable when running from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scanner import ScannerBridge  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Capture fingerprint scans")
    ap.add_argument("--count", type=int, default=5, help="Number of scans to capture")
    ap.add_argument("--out",   type=str, default="capture", help="Output prefix (e.g. captures/finger)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    out_dir = Path(args.out).parent
    if str(out_dir) and out_dir != Path("."):
        out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Place your finger on the reader. Capturing {args.count} scans...")
    print("(lift and press again between each scan)\n")

    n = 0
    with ScannerBridge() as bridge:
        for evt in bridge.events():
            t = evt["type"]
            if t == "scan":
                path = Path(f"{args.out}_{n}.png")
                path.write_bytes(evt["data"])
                print(f"  [{n + 1}/{args.count}] saved {path} ({len(evt['data'])} bytes)")
                n += 1
                if n >= args.count:
                    break
            elif t == "status":
                print(f"  status: {evt['status']}")
            elif t == "error":
                print(f"  bridge error [{evt['code']}]: {evt['message']}")

    print(f"\nDone. Captured {n} scans.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
