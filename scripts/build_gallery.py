"""Rebuild the GitHub Pages gallery and the README images from real runs.

    python scripts/build_gallery.py            # data + index.html
    python scripts/build_gallery.py --images   # also re-render docs/img/*.png

Needs network on the first run (everything is cached afterwards) and
playwright + chromium for --images.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from civmap.build import build, gather  # noqa: E402
from civmap.render import gallery_html, screenshot, write_html  # noqa: E402

COUNTRIES = ["IN", "JP", "GB", "IT", "EG", "BR", "FR", "AU"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", action="store_true")
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    docs = ROOT / "docs"
    (docs / "data").mkdir(parents=True, exist_ok=True)
    (docs / "img").mkdir(exist_ok=True)
    index = []
    for iso in COUNTRIES:
        path = docs / "data" / f"{iso}.json"
        if not a.only or iso in a.only:
            data = build(gather(iso), log=print)
            path.write_text(json.dumps(data, separators=(",", ":")))
        data = json.loads(path.read_text())
        index.append({"iso2": iso, "name": data["meta"]["name"]})
        if a.images and (not a.only or iso in a.only):
            html = Path("/tmp/civmap-gallery") / f"{iso}.html"
            write_html(data, html)
            screenshot(html, docs / "img" / f"{iso.lower()}.png", width=1600, height=1000, scale=1.5)
            print("rendered", iso)
    (docs / "countries.json").write_text(json.dumps(index, indent=1))
    (docs / "index.html").write_text(gallery_html(index))
    (docs / ".nojekyll").write_text("")
    print("gallery:", ", ".join(c["iso2"] for c in index))


if __name__ == "__main__":
    main()
