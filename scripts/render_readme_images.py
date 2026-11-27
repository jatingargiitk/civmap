"""Render the README hero, a close-up and the lens animation from docs/data/IN.json.

    python scripts/render_readme_images.py

Needs playwright + chromium. Every image is a real screenshot of the viewer.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from civmap.render import screenshot, write_html  # noqa: E402

TMP = Path("/tmp/civmap-readme")
IMG = ROOT / "docs" / "img"


def main() -> None:
    TMP.mkdir(exist_ok=True)
    IMG.mkdir(parents=True, exist_ok=True)
    data = json.loads((ROOT / "docs" / "data" / "IN.json").read_text())
    html = write_html(data, TMP / "india.html")

    hero = screenshot(html, TMP / "hero.png", width=1500, height=1150, scale=2, query="hero=1")
    Image.open(hero).convert("RGB").save(IMG / "hero-india.jpg", quality=90, optimize=True, progressive=True)
    print("hero", IMG / "hero-india.jpg")

    # close-up on the Mumbai-Pune region
    city = next(c for c in data["cities"] if c["name"] == "Mumbai")
    q = f"hero=1&zoom=3.2&at={city['x'] + 180:.0f},{city['y'] - 60:.0f}"
    close = screenshot(html, TMP / "close.png", width=1500, height=900, scale=1.5, query=q)
    Image.open(close).convert("RGB").save(IMG / "closeup-india.jpg", quality=90, optimize=True, progressive=True)
    print("close-up", IMG / "closeup-india.jpg")

    frames = []
    for lens in ["terrain", "relief", "rain", "temp", "food", "cit", "mw", "sci"]:
        p = screenshot(html, TMP / f"lens-{lens}.png", width=1000, height=770, scale=1, query=f"hero=1&lens={lens}")
        frames.append(Image.open(p).convert("RGB").quantize(colors=200, method=Image.Quantize.MEDIANCUT))
    frames[0].save(IMG / "lenses-india.gif", save_all=True, append_images=frames[1:], duration=1400, loop=0,
                   optimize=True)
    print("lenses", IMG / "lenses-india.gif")


if __name__ == "__main__":
    main()
