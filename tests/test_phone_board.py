"""The board on the phone (ABDOH_EPIC_11.md, story 150): the hub keeps it and its pictures, and
the page gets the window's own board.js and its libraries."""

import base64

from test_phone import call, make_app, make_hub

from abdoh.phone.server import SECURITY


def test_the_board_grows_and_clears():
    bus, hub = make_hub()
    hub.take("board", {"id": 1, "text": "## Merge sort"})
    hub.take("board", {"id": 1, "text": "## Merge sort\nSplit the list."})
    hub.take("board", {"id": 2, "text": "## Quick sort"})
    first = {"id": 1, "text": "## Merge sort\nSplit the list."}
    assert hub.state()["board"] == [first, {"id": 2, "text": "## Quick sort"}]
    events = hub.events(0, wait=0)["events"]
    assert [e["card"]["id"] for e in events] == [1, 1, 2]
    places = [m for m in hub.state()["media"] if m["type"] == "board"]
    assert [m["id"] for m in places] == [1, 2]  # each new card has its place, for everyone
    hub.take("board", None)
    assert hub.state()["board"] == [] and hub.events(3, wait=0)["events"][0]["card"] is None


def test_a_board_picture_becomes_a_link():
    bus, hub = make_hub()
    png = b"\x89PNG fake"
    src = "data:image/png;base64," + base64.b64encode(png).decode()
    hub.take("board_picture", {"what": "pizza", "ok": True, "credit": "Photo: CC BY", "src": src})
    picture = hub.events(0, wait=0)["events"][0]["picture"]
    key = picture["src"].removeprefix("/media/")
    assert hub.media.get(key).data == png and hub.media.get(key).type == "image/png"
    assert hub.state()["pictures"]["pizza"]["credit"] == "Photo: CC BY"
    hub.take("board_picture", {"what": "cake", "ok": False, "error": "No picture."})
    assert hub.state()["pictures"]["cake"] == {
        "what": "cake", "ok": False, "credit": None, "title": None, "ai": None,
        "error": "No picture.", "src": ""}  # fmt: skip
    hub.take("board_picture", {"what": "", "ok": True})  # nothing it shows: ignored
    assert len(hub.events(0, wait=0)["events"]) == 2


def test_the_page_gets_the_windows_board_and_its_libraries(tmp_path):
    bus, hub, phones, app = make_app(tmp_path)
    shared = tmp_path / "shared"
    (shared / "vendor" / "katex" / "fonts").mkdir(parents=True)
    (shared / "board.js").write_text("const Board = {};")
    (shared / "vendor" / "katex" / "fonts" / "KaTeX_Main-Regular.woff2").write_bytes(b"wOF2")
    (shared / "app.js").write_text("the window's own")
    app.shared = shared
    response, _ = call(app, "GET", "/board.js")
    assert response.status == 200 and response.type.startswith("text/javascript")
    response, _ = call(app, "GET", "/vendor/katex/fonts/KaTeX_Main-Regular.woff2")
    assert response.status == 200 and response.type == "font/woff2"
    for path in ("/app.js", "/vendor/../app.js", "/vendor/katex/../../app.js", "/vendor/.x",
                 "/vendor/katex/missing.js"):  # fmt: skip
        assert call(app, "GET", path)[0].status == 404, path


def test_the_real_board_files_are_there():
    from abdoh.phone.server import SHARED_DIR

    for name in ("board.js", "vendor/katex/katex.min.js", "vendor/katex/katex.min.css",
                 "vendor/katex/contrib/mhchem.min.js", "vendor/mermaid/mermaid.min.js",
                 "vendor/viz/viz-global.js"):  # fmt: skip
        assert (SHARED_DIR / name).is_file(), name


def test_graphviz_may_run_its_webassembly():
    assert "'wasm-unsafe-eval'" in SECURITY["Content-Security-Policy"]
    assert "'unsafe-eval'" not in SECURITY["Content-Security-Policy"].replace("wasm-unsafe", "")
