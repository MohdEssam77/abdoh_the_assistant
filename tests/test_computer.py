import pytest

from abdoh.commands.actions import ActionError
from abdoh.computer import App, AppIndex, Computer, Timers, parse_duration, press_media_key


@pytest.mark.parametrize(
    "text, seconds, label",
    [
        ("5 minutes", 300, "5 minute"),
        ("set a timer for five minutes", 300, "5 minute"),
        ("twenty five minutes", 1500, "25 minute"),
        ("a minute", 60, "1 minute"),
        ("1 hour 30 minutes", 5400, "1 hour 30 minute"),
        ("an hour and a half", 5400, "1 and a half hour"),
        ("half an hour", 1800, "30 minute"),
        ("90 seconds", 90, "90 second"),
        ("2.5 minutes", 150, "2.5 minute"),
        ("10 secs", 10, "10 second"),
        ("Set a timer for 3 minutes.", 180, "3 minute"),
    ],
)
def test_parse_duration(text, seconds, label):
    assert parse_duration(text) == (seconds, label)


def test_parse_duration_without_a_duration():
    assert parse_duration("banana") is None
    assert parse_duration("set a timer") is None


class FakeTimer:
    started: list = []

    def __init__(self, seconds, function, args=()):
        self.seconds, self.function, self.args = seconds, function, args
        self.daemon = False
        self.cancelled = False

    def start(self):
        FakeTimer.started.append(self)

    def cancel(self):
        self.cancelled = True

    def is_alive(self):
        return not self.cancelled

    def fire(self):
        self.function(*self.args)


def test_timer_starts_and_announces_when_done():
    said = []
    FakeTimer.started = []
    timers = Timers(announce=said.append, start_timer=FakeTimer)
    assert timers.start("5 minutes") == "Okay, 5 minute timer starting now."
    (timer,) = FakeTimer.started
    assert timer.seconds == 300 and timer.daemon
    timer.fire()
    assert said == ["Your 5 minute timer is done."]


def test_cancel_timers():
    FakeTimer.started = []
    timers = Timers(announce=lambda t: None, start_timer=FakeTimer)
    assert timers.cancel_all() == "There's no timer running."
    timers.start("1 minute")
    assert timers.cancel_all() == "Timer cancelled."
    assert FakeTimer.started[0].cancelled


def test_timer_needs_a_duration():
    with pytest.raises(ActionError, match="how long"):
        Timers(announce=lambda t: None, start_timer=FakeTimer).start("soon")


def test_unknown_media_key():
    with pytest.raises(ActionError, match="don't know"):
        press_media_key("louder")


APPS = [
    App("Calculator", "Microsoft.WindowsCalculator!App"),
    App("Google Chrome", "Chrome"),
    App("Visual Studio Code", "Microsoft.VisualStudioCode"),
    App("Developer Command Prompt for VS 2022", "x"),
    App("Photos", "Microsoft.Windows.Photos!App"),
    App("Uninstall Zoom Workplace", "zoom-uninstall"),
    App("Zoom Workplace", "zoom"),
    App("Mail", "microsoft.windowscommunicationsapps!mail"),
    App("Notepad", "notepad"),
]


def index(apps=APPS):
    launched = []
    loads = []

    def loader():
        loads.append(1)
        return apps

    idx = AppIndex(loader=loader, launch=launched.append)
    idx.load()
    return idx, launched, loads


@pytest.mark.parametrize(
    "spoken, name",
    [
        ("calculator", "Calculator"),
        ("the calculator app", "Calculator"),
        ("chrome", "Google Chrome"),
        ("vs code", "Visual Studio Code"),
        ("zoom", "Zoom Workplace"),  # never the uninstaller
        ("my email", "Mail"),
        ("note pad", "Notepad"),
    ],
)
def test_find_apps_by_spoken_name(spoken, name):
    idx, _, _ = index()
    assert idx.find(spoken).name == name


@pytest.mark.parametrize("spoken", ["photoshop", "spotify", r"C:\Windows\System32\cmd.exe", ""])
def test_unknown_or_unsafe_names_find_nothing(spoken):
    idx, _, _ = index()
    assert idx.find(spoken) is None


def test_open_launches_the_matching_app():
    idx, launched, _ = index()
    assert idx.open("chrome") == "Google Chrome"
    assert launched == [App("Google Chrome", "Chrome")]
    with pytest.raises(ActionError, match="couldn't find an app called spotify"):
        idx.open("spotify")


def test_missing_app_reloads_the_list_only_when_stale(monkeypatch):
    idx, _, loads = index()
    assert idx.find("spotify") is None and len(loads) == 1  # fresh list: no reload
    monkeypatch.setattr(AppIndex, "REFRESH_SECONDS", -1)
    idx.find("spotify")
    assert len(loads) == 2


def test_loader_failure_means_no_apps():
    def broken():
        raise OSError("powershell missing")

    idx = AppIndex(loader=broken, launch=lambda a: None)
    idx.load()
    assert idx.find("calculator") is None


def test_computer_delegates():
    pressed, locked, urls = [], [], []
    idx, _, _ = index()
    timers = Timers(announce=lambda t: None, start_timer=FakeTimer)
    computer = Computer(
        timers=timers,
        apps=idx,
        press_key=pressed.append,
        lock=lambda: locked.append(1),
        open_url=lambda u: urls.append(u) or True,
    )
    computer.media(" Volume_Up ")
    computer.lock()
    computer.open_url("https://a.b")
    assert computer.open_app("notepad") == "Notepad"
    assert pressed == ["volume_up"] and locked == [1] and urls == ["https://a.b"]
    with pytest.raises(ActionError):
        Computer(apps=idx, open_url=lambda u: False).open_url("https://a.b")


def test_play_youtube_starts_the_top_video():
    urls = []
    computer = Computer(
        open_url=lambda u: urls.append(u) or True, find_video=lambda q: "abcdefghijk"
    )
    assert computer.play_youtube("bohemian rhapsody") == ""  # the video speaks for itself
    assert urls == ["https://www.youtube.com/watch?v=abcdefghijk"]


def test_play_youtube_falls_back_to_the_results_page():
    urls, searched = [], []
    computer = Computer(
        open_url=lambda u: urls.append(u) or True,
        find_video=lambda q: searched.append(q),  # finds nothing
    )
    assert computer.play_youtube(" lo-fi beats ") == "Here are the YouTube results."
    assert searched == ["lo-fi beats"]
    assert urls == ["https://www.youtube.com/results?search_query=lo-fi+beats"]
    with pytest.raises(ActionError):
        computer.play_youtube("  ")


def test_launch_for_your_own_commands(tmp_path):
    started = []
    idx, launched, _ = index()
    computer = Computer(apps=idx, start_app=started.append)
    computer.launch("calculator")  # an installed app (Store apps too)
    assert launched == [App("Calculator", "Microsoft.WindowsCalculator!App")]
    exe = tmp_path / "tool.exe"
    exe.write_text("")
    computer.launch(str(exe))  # a path is started as-is
    computer.launch("some-unknown-thing")  # left to Windows, like v1
    assert started == [str(exe), "some-unknown-thing"]
