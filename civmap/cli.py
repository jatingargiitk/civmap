"""civmap command line: ``civmap IN`` -> india.html (+ optional PNG)."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import __version__


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="civmap",
        description="Render any country as a Civilization-style hex map from open data.")
    ap.add_argument("country", help="ISO code or name: IN, JPN, 'United Kingdom', ...")
    ap.add_argument("-o", "--out", help="output HTML path (default: <country>.html)")
    ap.add_argument("--png", nargs="?", const="", default=None,
                    help="also save a PNG screenshot (needs playwright); optional path")
    ap.add_argument("--json", nargs="?", const="", default=None, help="also save the map data as JSON")
    ap.add_argument("--hexes", type=int, default=5000, help="approximate number of land hexes (default 5000)")
    ap.add_argument("--lens", default="terrain", help="lens for the PNG: terrain, relief, rain, temp, food, prod, gold, sci, cul, cit, mw")
    ap.add_argument("--size", default="1600x1000", help="PNG viewport, WIDTHxHEIGHT (default 1600x1000)")
    ap.add_argument("--scale", type=float, default=2.0, help="PNG device pixel ratio (default 2)")
    ap.add_argument("-q", "--quiet", action="store_true")
    ap.add_argument("--version", action="version", version=f"civmap {__version__}")
    a = ap.parse_args(argv)

    from .build import build, gather
    from .render import screenshot, write_html

    log = (lambda *_: None) if a.quiet else (lambda *m: print("·", *m, file=sys.stderr))
    t0 = time.time()
    inp = gather(a.country, target_hexes=a.hexes, log=log)
    data = build(inp, target_hexes=a.hexes, log=log)
    stem = inp.name.lower().replace(" ", "-")
    out = Path(a.out or f"{stem}.html")
    write_html(data, out)
    print(f"wrote {out}  ({data['meta']['landHexes']} land hexes, {len(data['cities'])} cities, "
          f"{len(data['wonders'])} wonders, {time.time() - t0:.0f}s)")
    if a.json is not None:
        jp = Path(a.json or out.with_suffix(".json"))
        jp.write_text(json.dumps(data, separators=(",", ":")))
        print(f"wrote {jp}")
    if a.png is not None:
        w, h = (int(v) for v in a.size.lower().split("x"))
        pp = Path(a.png or out.with_suffix(".png"))
        q = "hero=1" + (f"&lens={a.lens}" if a.lens != "terrain" else "")
        screenshot(out, pp, width=w, height=h, scale=a.scale, query=q)
        print(f"wrote {pp}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
