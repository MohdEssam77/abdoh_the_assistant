from abdoh.ui.app import forget_old_page


def cached(storage):
    cache = storage / "EBWebView" / "Default"
    for name in ("Cache", "Code Cache", "Local Storage"):
        (cache / name).mkdir(parents=True, exist_ok=True)
        (cache / name / "f").write_text("x")
    return cache


def test_a_new_version_drops_the_old_page_but_keeps_what_the_page_remembers(tmp_path):
    cache = cached(tmp_path)
    (tmp_path / "version.txt").write_text("0.4.0")
    forget_old_page(tmp_path, "0.5.1")
    assert not (cache / "Cache").exists() and not (cache / "Code Cache").exists()
    assert (cache / "Local Storage" / "f").exists()
    assert (tmp_path / "version.txt").read_text() == "0.5.1"


def test_the_same_version_keeps_the_cache(tmp_path):
    cache = cached(tmp_path)
    (tmp_path / "version.txt").write_text("0.5.1")
    forget_old_page(tmp_path, "0.5.1")
    assert (cache / "Cache" / "f").exists()


def test_the_first_start_after_installing_over_an_old_version_drops_it(tmp_path):
    cache = cached(tmp_path)  # 0.4 left a cache and no version.txt
    forget_old_page(tmp_path, "0.5.1")
    assert not (cache / "Cache").exists()


def test_a_fresh_install_works(tmp_path):
    forget_old_page(tmp_path / "webview", "0.5.1")
    assert (tmp_path / "webview" / "version.txt").read_text() == "0.5.1"


def test_any_change_to_the_page_is_a_new_page(tmp_path):
    """Running from source between releases keeps the version: the page's files decide."""
    from abdoh.ui.app import page_stamp

    web = tmp_path / "web"
    (web / "vendor").mkdir(parents=True)
    (web / "settings.js").write_text("one")
    (web / "vendor" / "katex.js").write_text("k")
    first = page_stamp("0.8.0", web)
    assert first.startswith("0.8.0+") and page_stamp("0.8.0", web) == first
    (web / "settings.js").write_text("two")  # a new setting on the page
    assert page_stamp("0.8.0", web) != first
    (web / "settings.js").write_text("one")
    (web / "vendor" / "katex.js").write_text("k2")
    assert page_stamp("0.8.0", web) != first
    assert page_stamp("0.9.0", web) != page_stamp("0.8.0", web)


def test_the_real_page_has_a_stamp():
    from abdoh.ui.app import page_stamp

    assert len(page_stamp("0.8.0").split("+")[1]) == 12
