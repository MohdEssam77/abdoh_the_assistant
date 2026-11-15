import re
from pathlib import Path

from abdoh.updates import ASSET, REPO

DOCS = Path(__file__).resolve().parents[1] / "docs"
PAGE = (DOCS / "index.html").read_text(encoding="utf-8")


def test_downloads_come_from_the_same_repo_as_the_update_check():
    assert f'const REPO = "{REPO}";' in PAGE
    assert f"https://github.com/{REPO}/releases/latest/download/{ASSET}" in PAGE


def test_no_external_scripts_or_styles():
    assert not re.search(r"<script[^>]+src=", PAGE)
    assert not re.search(r'<link[^>]+rel="stylesheet"', PAGE)


def test_every_local_file_it_uses_exists():
    refs = re.findall(r'(?:src|srcset|href)="([^"#:?]+)"', PAGE)
    local = [r for r in refs if not r.startswith(("http", "./", "/"))]
    assert {"favicon.svg", "app-light.png", "app-dark.png"} <= set(local)
    for ref in local:
        assert (DOCS / ref).is_file(), ref
    assert (DOCS / ".nojekyll").is_file()  # GitHub Pages serves the files as they are


def test_it_says_abdoh_is_not_anthropics():
    assert "isn't made by, affiliated with or endorsed by Anthropic" in PAGE
    assert "free plan" in PAGE.lower()
