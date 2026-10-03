"""Asset edits must invalidate browser caches without requiring a hard refresh."""

import re

import app as board


def test_asset_urls_follow_file_contents(tmp_path, monkeypatch):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text(
        '<link href="/static/style.css"><script src="/static/app.js"></script>'
    )
    script = static / "app.js"
    script.write_text("// original script")
    (static / "style.css").write_text("body { color: black; }")
    monkeypatch.setattr(board, "ROOT", tmp_path)

    def urls():
        return re.findall(r'(?:src|href)="(/static/[^\"]+)"', board.index().body.decode())

    original = urls()
    assert urls() == original
    script.write_text("// changed script")
    updated = urls()
    assert updated[0] == original[0]  # Unchanged CSS can reuse its cached response.
    assert updated[1] != original[1]
    (static / "style.css").write_text("body { color: blue; }")
    assert urls()[0] != original[0]
