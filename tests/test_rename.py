"""Abdoh's folders move over to Xanthos's on the first start under the new name."""

from abdoh.rename import move_folder, move_old_folders


def make(folder, name="config.yaml", text="mine"):
    folder.mkdir(parents=True)
    (folder / name).write_text(text)


def test_the_old_folders_move_over(tmp_path):
    home, appdata = tmp_path / "home", tmp_path / "appdata"
    make(home / ".abdoh", "update.json")
    make(appdata / "Abdoh")
    done = move_old_folders(home, appdata, frozen=True)
    assert len(done) == 2
    assert (home / ".xanthos" / "update.json").exists() and not (home / ".abdoh").exists()
    assert (appdata / "Xanthos" / "config.yaml").read_text() == "mine"


def test_a_new_folder_that_exists_gets_only_what_it_lacks(tmp_path):
    make(tmp_path / ".abdoh", text="old")
    (tmp_path / ".abdoh" / "xanthos.log").write_text("log")
    make(tmp_path / ".xanthos", text="new")
    assert move_old_folders(tmp_path, frozen=False) == [
        f"Moved 1 items from {tmp_path / '.abdoh'} to {tmp_path / '.xanthos'}"
    ]
    assert (tmp_path / ".xanthos" / "config.yaml").read_text() == "new"  # never overwritten
    assert (tmp_path / ".xanthos" / "xanthos.log").read_text() == "log"
    assert move_old_folders(tmp_path, frozen=False) == []  # the second time: nothing to do


def test_a_fresh_install_has_nothing_to_move(tmp_path):
    assert move_old_folders(tmp_path, tmp_path, frozen=True) == []
    assert not (tmp_path / ".xanthos").exists()


def test_running_from_source_keeps_the_settings_where_they_are(tmp_path):
    make(tmp_path / "Abdoh")
    move_old_folders(tmp_path / "home", tmp_path, frozen=False)
    assert (tmp_path / "Abdoh").exists() and not (tmp_path / "Xanthos").exists()


def test_a_folder_in_use_is_copied(tmp_path, monkeypatch):
    make(tmp_path / "old")

    def busy(old, new):
        raise PermissionError("in use")

    monkeypatch.setattr("abdoh.rename.os.replace", busy)
    assert move_folder(tmp_path / "old", tmp_path / "new").startswith("Copied")
    assert (tmp_path / "new" / "config.yaml").exists() and (tmp_path / "old").exists()
