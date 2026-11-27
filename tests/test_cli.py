import shutil
import subprocess
from pathlib import Path

import pytest

from civmap import build as B
from civmap import cli


def test_cli_writes_html(tmp_path, monkeypatch, toy_inputs, capsys):
    monkeypatch.setattr(B, "gather", lambda *a, **k: toy_inputs)
    out = tmp_path / "toy.html"
    assert cli.main(["TL", "-o", str(out), "--hexes", "300", "--json", "-q"]) == 0
    assert out.exists() and out.with_suffix(".json").exists()
    assert "land hexes" in capsys.readouterr().out


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_viewer_js_parses():
    js = Path(__file__).parent.parent / "civmap" / "viewer" / "app.js"
    subprocess.run(["node", "--check", str(js)], check=True)
