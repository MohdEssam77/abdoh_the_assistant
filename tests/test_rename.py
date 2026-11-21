"""Krekos's (and Xanthos's) folders move back to Abdoh's on the first start as Abdoh."""

from abdoh.rename import MARK, move_folder, move_old_folders


def make(folder, name="config.yaml", text="mine"):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text)


def test_krekos_folders_move_back(tmp_path):
    home, appdata = tmp_path / "home", tmp_path / "appdata"
    make(home / ".krekos", "update.json")
    make(appdata / "Krekos")
    done = move_old_folders(home, appdata, frozen=True)
    assert len(done) == 2
    assert (home / ".abdoh" / "update.json").exists() and not (home / ".krekos").exists()
    assert (appdata / "Abdoh" / "config.yaml").read_text() == "mine"


def test_xanthos_folders_move_back_too(tmp_path):
    home, appdata = tmp_path / "home", tmp_path / "appdata"
    make(home / ".xanthos", "update.json")
    make(appdata / "Xanthos")
    assert len(move_old_folders(home, appdata, frozen=True)) == 2
    assert (appdata / "Abdoh" / "config.yaml").read_text() == "mine"


def test_krekos_wins_over_xanthos(tmp_path):
    make(tmp_path / ".xanthos", text="older")
    (tmp_path / ".xanthos" / "notes.txt").write_text("only xanthos had this")
    make(tmp_path / ".krekos", text="newer")
    move_old_folders(tmp_path, frozen=False)
    assert (tmp_path / ".abdoh" / "config.yaml").read_text() == "newer"
    assert (tmp_path / ".abdoh" / "notes.txt").read_text() == "only xanthos had this"


def test_an_abdoh_folder_from_before_the_renames_is_set_aside_not_mixed_in(tmp_path):
    make(tmp_path / ".abdoh", "claude", text="an old sign-in")  # left behind back then
    make(tmp_path / ".krekos", "claude", text="your sign-in now")
    done = move_old_folders(tmp_path, frozen=False)
    assert (tmp_path / ".abdoh" / "claude").read_text() == "your sign-in now"
    assert (tmp_path / ".abdoh-before-krekos" / "claude").read_text() == "an old sign-in"
    assert done[0].startswith("Kept the older")


def test_once_back_leftovers_only_fill_in(tmp_path):
    make(tmp_path / ".krekos", text="settings")
    move_old_folders(tmp_path, frozen=False)
    assert (tmp_path / ".abdoh" / MARK).exists()
    make(tmp_path / ".krekos", text="a copy that couldn't move")  # still held open back then
    (tmp_path / ".krekos" / "extra.txt").write_text("extra")
    move_old_folders(tmp_path, frozen=False)
    assert (tmp_path / ".abdoh" / "config.yaml").read_text() == "settings"  # never set aside
    assert (tmp_path / ".abdoh" / "extra.txt").exists()
    assert not (tmp_path / ".abdoh-before-krekos").exists()


def test_a_long_time_abdoh_install_is_left_alone(tmp_path):
    make(tmp_path / ".abdoh", text="mine")
    assert move_old_folders(tmp_path, tmp_path, frozen=True) == []
    assert (tmp_path / ".abdoh" / "config.yaml").read_text() == "mine"
    assert not (tmp_path / ".abdoh" / MARK).exists()


def test_running_from_source_keeps_the_settings_where_they_are(tmp_path):
    make(tmp_path / "Krekos")
    move_old_folders(tmp_path / "home", tmp_path, frozen=False)
    assert (tmp_path / "Krekos").exists() and not (tmp_path / "Abdoh").exists()


def test_a_folder_in_use_is_copied(tmp_path, monkeypatch):
    make(tmp_path / "old")

    def busy(old, new):
        raise PermissionError("in use")

    monkeypatch.setattr("abdoh.rename.os.replace", busy)
    assert move_folder(tmp_path / "old", tmp_path / "new").startswith("Copied")
    assert (tmp_path / "new" / "config.yaml").exists() and (tmp_path / "old").exists()
