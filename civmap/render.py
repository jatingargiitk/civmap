"""Write the self-contained HTML map, and optionally a PNG via headless Chromium."""
from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

ROOT = resources.files("civmap") / "viewer"


def _asset(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def page(boot: str, title: str) -> str:
    html = _asset("template.html")
    # use explicit replacement so that "$" or "\\" in data never matter
    for key, val in (("__TITLE__", title), ("__CSS__", _asset("style.css")),
                     ("__BOOT__", boot), ("__JS__", _asset("app.js"))):
        html = html.replace(key, val, 1)
    return html


def html_for(data: dict) -> str:
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    return page("window.CIVMAP_DATA=" + payload + ";", f"{data['meta']['name']} · civmap")


def gallery_html(index: list[dict]) -> str:
    return page("window.CIVMAP_INDEX=" + json.dumps(index) + ";", "civmap · Civilization-style maps of real countries")


def write_html(data: dict, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_for(data), encoding="utf-8")
    return path


def screenshot(html_path: Path, png_path: Path, width: int = 1600, height: int = 1000,
               scale: float = 2.0, query: str = "hero=1") -> Path:
    """Render ``html_path`` in headless Chromium and save a PNG (needs playwright)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise SystemExit("PNG export needs playwright: pip install playwright && playwright install chromium") from exc
    url = Path(html_path).resolve().as_uri() + ("?" + query if query else "")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=scale)
        pg.goto(url, wait_until="networkidle", timeout=90000)
        pg.wait_for_function("window.CIVMAP_READY === true", timeout=60000)
        pg.wait_for_timeout(400)
        pg.screenshot(path=str(png_path))
        browser.close()
    return Path(png_path)
