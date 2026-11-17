"""Things you can say to control the computer itself: screens on and off, which speakers,
dark mode, the power mode, sleep and shutdown, other programs' windows, folders and the
clipboard. Part of the local skills (instant, no Claude).

Shutting down and restarting ask first ("Shut down the computer?"); the answer comes as the
next request.
"""

import re
import time
from dataclasses import dataclass

from abdoh.computer import parse_duration
from abdoh.system import POWER_NAMES

CONFIRM_SECONDS = 60
SHUTDOWN_DELAY = 20  # seconds: time to say "cancel the shutdown"
NO_POWER = "Sleep, shutdown and restart are turned off in Abdoh's permissions."
_YES = re.compile(
    r"(?:yes|yeah|yep|sure|ok|okay|do it|go ahead|confirm|please do)(?: please| do it)?"
)
_NO = re.compile(r"(?:no|nope|dont|do not|cancel|never mind|stop)(?: .*)?")

_SCREEN = r"(?:monitors?|screens?|displays?)"
_THE = r"(?:the |my )?"
_SCREENS_ONOFF = [
    re.compile(rf"turn (?P<onoff>on|off) {_THE}{_SCREEN} (?P<which>[\w ,]+)"),
    re.compile(rf"turn {_THE}{_SCREEN} (?P<which>[\w ,]+?) (?P<onoff>on|off)"),
    re.compile(rf"turn (?P<onoff>on|off) {_THE}(?P<which>[\w ,]+?) {_SCREEN}"),
    re.compile(rf"turn {_THE}(?P<which>[\w ,]+?) {_SCREEN} (?P<onoff>on|off)"),
]
_OTHERS_OFF = re.compile(rf"turn off {_THE}other {_SCREEN}|turn {_THE}other {_SCREEN} off")
_ONLY = re.compile(
    rf"(?:use |keep )?(?:only|just) {_THE}(?:{_SCREEN} )?(?P<which>[\w ,]+?)(?: {_SCREEN})?(?: on)?"
)
_ALL_ON = re.compile(rf"(?:turn on |use )?all {_THE}{_SCREEN}(?: on)?|turn {_THE}{_SCREEN} on")
_WHICH_ON = re.compile(rf"(?:which|what) {_SCREEN} are on|list {_THE}{_SCREEN}")
_SCREENS_SLEEP = re.compile(rf"turn off {_THE}{_SCREEN}|turn {_THE}{_SCREEN} off|{_SCREEN} off")

_OUTPUT = re.compile(
    r"(?:switch|change|move|send) (?:the )?(?:sound|audio)(?: output)? to (?P<out>.+)"
    r"|play (?:the )?(?:sound|audio) (?:on|through|from) (?P<out2>.+)"
    r"|(?:use|switch to) (?P<out3>(?:the |my )?(?:headphones|headset|speakers|earphones))"
)
_WHICH_OUTPUT = re.compile(
    r"(?:whats|what is|which is) (?:my |the )?(?:audio|sound) output|which speakers(?: am i using)?"
)
_THEME = re.compile(
    r"(?:switch to |turn on |enable |use |go )?(?P<mode>dark|light) (?:mode|theme)(?: on)?"
)
_THEME_OFF = re.compile(r"(?:turn off|disable) (?P<mode>dark|light) (?:mode|theme)")
_NIGHT_LIGHT = re.compile(
    r"(?:turn |switch )?(?P<on>on|off) (?:the )?night ?light"
    r"|(?:turn |switch )?(?:the )?night ?light (?P<on2>on|off)|night ?light"
)
_POWER_MODES = {
    "best_performance": r"(?:best |high )?performance",
    "balanced": r"balanced",
    "efficiency": r"(?:power|battery) sav(?:er|ing)|(?:best )?(?:power )?efficiency|eco",
}
_POWER_MODE = re.compile(
    r"(?:switch to |set |use |go to |turn on )?(?:the )?(?P<mode>"
    + "|".join(f"(?P<{k}>{v})" for k, v in _POWER_MODES.items())
    + r")(?: power)? mode"
    r"|(?:turn on )?(?:the )?(?P<saver>(?:power|battery) saver)"
)
_SLEEP = re.compile(
    r"go to sleep|(?:put|send) (?:the |my )?(?:computer|pc|laptop) to sleep"
    r"|sleep (?:the |my )?(?:computer|pc|laptop)"
)
_SHUTDOWN = re.compile(
    r"(?:shut ?down|turn off|power off) (?:the |my )?(?:computer|pc|laptop)(?: in (?P<when>.+))?"
    r"|shut ?down(?: in (?P<when2>.+))?"
)
_RESTART = re.compile(r"(?:restart|reboot)(?: (?:the |my )?(?:computer|pc|laptop))?")
_CANCEL_SHUTDOWN = re.compile(
    r"(?:cancel|stop|abort) (?:the )?(?:shutdown|shut down|restart)|dont (?:shut down|restart)"
)

_APP = r"(?P<app>[\w .]+?)"
_CLOSE = re.compile(rf"(?:close|quit|exit) {_THE}{_APP}")
_FOCUS = re.compile(rf"(?:switch to|go to|show(?: me)?|bring up) {_THE}{_APP}")
_MOVE = re.compile(
    rf"(?:move|put|send) {_THE}{_APP}(?: window)? (?:to|on|onto) {_THE}"
    rf"(?P<screen>[\w ]+?)(?: (?P<how>left|right))?"
)
_SNAP = re.compile(r"snap (?:this |the )?(?:window )?(?:to )?(?:the )?(?P<how>left|right)")
_FOLDER = re.compile(
    r"open (?:my |the )?(?P<folder>downloads|documents|desktop|pictures|music|videos|screenshots)"
    r"(?: folder)?"
)
_NEWEST = re.compile(
    r"open (?:my |the )?(?:last|latest|newest|most recent) (?P<kind>download|screenshot)"
)
_COPY = re.compile(r"copy (?:that|this|it|your (?:answer|reply)|the (?:answer|reply))")
_READ_CLIPBOARD = re.compile(
    r"(?:read|whats in|what is in|what is on|whats on) (?:my |the )?clipboard|what did i copy"
)
CLIPBOARD_LIMIT = 300
_SCREEN_WORDS = ("screen", "monitor", "display")


@dataclass
class Pending:
    """Something that needs a yes first."""

    question: str
    run: object  # () -> str
    until: float


class Question(str):
    """A reply that asks something: Abdoh listens for the answer without the wake word."""


class SystemSkills:
    def __init__(self, computer, allow_power=lambda: True, last_reply=lambda: "", clock=None):
        self.computer = computer
        self._allow_power = allow_power
        self._last_reply = last_reply
        self._clock = clock or (lambda: time.time())
        self._pending: Pending | None = None

    def handle(self, request: str, original: str = "") -> str | None:
        for handler in (self._screens, self._sound, self._settings, self._power, self._windows,
                        self._folders, self._clipboard):  # fmt: skip
            reply = handler(request)
            if reply is not None:
                return reply
        return None

    # ----- asking first -----

    def answer(self, request: str) -> str | None:
        """If Abdoh just asked something ("Shut down the computer?"), the answer to it."""
        pending, self._pending = self._pending, None
        if pending is None or self._clock() > pending.until:
            return None
        if _YES.fullmatch(request):
            return pending.run()
        if _NO.fullmatch(request):
            return "Okay, I won't."
        return None  # something else: forget the question, and do that instead

    def _ask(self, question: str, run) -> Question:
        self._pending = Pending(question, run, self._clock() + CONFIRM_SECONDS)
        return Question(question)

    # ----- screens -----

    def _screens(self, request: str) -> str | None:
        computer = self.computer
        if getattr(computer, "displays", None) is None:
            return None
        displays = computer.displays
        if _WHICH_ON.fullmatch(request):
            return computer.screens_status()
        if _ALL_ON.fullmatch(request):
            return computer.screens("all")
        if _OTHERS_OFF.fullmatch(request):
            current = computer.screen_in_front()
            return computer.screens(f"only {current.number}")
        for pattern in _SCREENS_ONOFF:
            found = pattern.fullmatch(request)
            if found and displays.find(found["which"]):
                return computer.screens(f"{found['which']} {found['onoff']}")
        found = _ONLY.fullmatch(request)
        if found and any(w in request for w in _SCREEN_WORDS) and displays.find(found["which"]):
            return computer.screens(f"only {found['which']}")
        if _SCREENS_SLEEP.fullmatch(request):
            computer.power("screens_off")
            return ""
        return None

    # ----- sound and settings -----

    def _sound(self, request: str) -> str | None:
        computer = self.computer
        if _WHICH_OUTPUT.fullmatch(request):
            from abdoh.computer import short_output_name

            current = next((o for o in computer.audio_outputs() if o.default), None)
            if current is None:
                return "I can't tell which speakers are in use."
            return f"The sound comes out of {short_output_name(current.name)}."
        found = _OUTPUT.fullmatch(request)
        if found:
            name = computer.set_audio_output(found["out"] or found["out2"] or found["out3"])
            return f"Sound is coming out of {name}."
        return None

    def _settings(self, request: str) -> str | None:
        computer = self.computer
        found = _THEME.fullmatch(request)
        if found:
            computer.set_dark_mode(found["mode"] == "dark")
            return f"{found['mode'].capitalize()} mode."
        found = _THEME_OFF.fullmatch(request)
        if found:
            computer.set_dark_mode(found["mode"] != "dark")
            return f"{'Light' if found['mode'] == 'dark' else 'Dark'} mode."
        found = _NIGHT_LIGHT.fullmatch(request)
        if found:
            on = (found["on"] or found["on2"] or "on") == "on"
            computer.set_night_light(on)
            return f"Night light {'on' if on else 'off'}."
        found = _POWER_MODE.fullmatch(request)
        if found:
            mode = "efficiency" if found["saver"] else next(k for k in _POWER_MODES if found[k])
            computer.set_power_mode(mode)
            return f"Power mode: {POWER_NAMES[mode]}."
        return None

    # ----- sleep, shutdown -----

    def _power(self, request: str) -> str | None:
        computer = self.computer
        if _CANCEL_SHUTDOWN.fullmatch(request):
            if computer.cancel_shutdown():
                return "Okay, the shutdown is cancelled."
            return "No shutdown was waiting."
        sleep = _SLEEP.fullmatch(request)
        shutdown = _SHUTDOWN.fullmatch(request)
        restart = _RESTART.fullmatch(request)
        if not (sleep or shutdown or restart):
            return None
        if not self._allow_power():
            return NO_POWER
        if sleep:
            return self._ask("Put the computer to sleep?", self._sleep)
        if restart:
            return self._ask("Restart the computer?", lambda: self._shutdown(SHUTDOWN_DELAY, True))
        when = shutdown["when"] or shutdown["when2"]
        if when:
            delay = parse_duration(when)
            if delay is None:
                return "In how long should I shut down? For example: in 30 minutes."
            seconds = round(delay[0])
            if seconds >= 60:  # a timer for later (after a film): no need to ask
                return self._shutdown(seconds, False, f"in {delay[1]}s".replace("1 s", "1 "))
        return self._ask("Shut down the computer?", lambda: self._shutdown(SHUTDOWN_DELAY, False))

    def _sleep(self) -> str:
        self.computer.power("sleep")
        return ""

    def _shutdown(self, seconds: int, restart: bool, when: str = "") -> str:
        self.computer.shutdown(seconds, restart)
        what = "Restarting" if restart else "Shutting down"
        when = when or f"in {seconds} seconds"
        cancel = "cancel the restart" if restart else "cancel the shutdown"
        return f"{what} {when}. Say {cancel} to stop it."

    # ----- other programs' windows -----

    def _windows(self, request: str) -> str | None:
        computer = self.computer
        found = _SNAP.fullmatch(request)
        if found:
            computer.move_window(None, "current", found["how"])
            return ""
        found = _MOVE.fullmatch(request)
        if found and getattr(computer, "displays", None) is not None:
            app = found["app"]
            app = None if app in ("this", "it", "this window", "the window", "window") else app
            if app is None or computer.is_open(app):
                screen = computer.move_window(app, found["screen"], found["how"] or "maximized")
                return f"On {screen}."
        found = _CLOSE.fullmatch(request)
        if found and found["app"] not in ("this window", "the window", "window", "this", "it"):
            if computer.is_open(found["app"]):
                computer.close_app(found["app"])
                return ""
        found = _FOCUS.fullmatch(request)
        if found and computer.is_open(found["app"]):
            computer.focus_app(found["app"])
            return ""
        return None

    # ----- folders and the clipboard -----

    def _folders(self, request: str) -> str | None:
        found = _NEWEST.fullmatch(request)
        if found:
            folder = "downloads" if found["kind"] == "download" else "screenshots"
            return f"Opening {self.computer.open_newest(folder)}."
        found = _FOLDER.fullmatch(request)
        if found:
            self.computer.open_folder(found["folder"])
            return ""
        return None

    def _clipboard(self, request: str) -> str | None:
        if _COPY.fullmatch(request):
            text = self._last_reply()
            if not text:
                return "I haven't said anything to copy yet."
            self.computer.set_clipboard(text)
            return "Copied."
        if _READ_CLIPBOARD.fullmatch(request):
            text = " ".join(self.computer.clipboard().split())
            if not text:
                return "Your clipboard is empty."
            if len(text) > CLIPBOARD_LIMIT:
                return f"Your clipboard says: {text[:CLIPBOARD_LIMIT].rsplit(' ', 1)[0]}, and more."
            return f"Your clipboard says: {text}"
        return None
