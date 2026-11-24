"""Things Abdoh does instantly by itself, without Claude: timers and reminders, volume and
brightness, media keys, notes, quick maths, typing what you dictate, screenshots, the window in
front, locking the computer, and opening any installed app. Your own commands come first."""

import logging
import re
from datetime import datetime, timedelta

from abdoh.commands.actions import ActionError
from abdoh.commands.matcher import normalize
from abdoh.computer import _NUMBERS, parse_duration
from abdoh.desk import calculate, clock_text, parse_clock
from abdoh.system_skills import Done

log = logging.getLogger(__name__)

_POLITE = re.compile(r"^(?:(?:can|could|would) you |please )|(?: please| for me)$")

_MEDIA = {
    "volume_up": r"(?:turn )?(?:the )?volume up|turn it up|louder|(?:increase|raise) the volume",
    "volume_down": r"(?:turn )?(?:the )?volume down|turn it down|quieter"
    r"|(?:decrease|lower) the volume",
    "play_pause": r"pause|play|resume|play (?:the )?(?:music|song|video|track)"
    r"|(?:pause|stop|resume)(?: the| this| that| my)?(?: [a-z]+)? (?:music|song|video|track)",
    "next": r"next(?: song| track| one)?|skip(?: this| it)?(?: song| track)?",
    "previous": r"previous(?: song| track)?|(?:go )?back a (?:song|track)|last (?:song|track)",
}
_MEDIA_PATTERNS = {key: re.compile(rf"(?:{pattern})") for key, pattern in _MEDIA.items()}
_SOUND = r"(?:the |my )?(?:volume|sound|audio|laptop|computer|pc|speakers?)"
_MUTE = re.compile(rf"mute(?: {_SOUND})?|turn (?:the )?(?:sound|volume) off|silence")
_UNMUTE = re.compile(rf"unmute(?: {_SOUND})?|turn (?:the )?(?:sound|volume)(?: back)? on")
_LEVEL = r"(?P<level>\d{1,3}|[a-z]+(?: [a-z]+)?)(?: percent)?"
_SET = r"(?:set|change|turn|put|make|bring|raise|lower|increase|decrease|let|get)"
_VOLUME = re.compile(
    rf"(?:{_SET} )?(?:the |my )?(?:volume|sound)(?: level)?(?: up| down)? (?:to |at )?{_LEVEL}"
)
_VOLUME_MAX = re.compile(r"(?:max(?:imum)?|full) volume|volume (?:to )?(?:max(?:imum)?|full)")
_ASK_VOLUME = re.compile(r"(?:whats|what is|hows|how is) the volume|how loud is it")
_BRIGHTNESS = re.compile(
    rf"(?:{_SET} )?(?:the |my )?(?:screen )?brightness(?: up| down)? (?:to |at )?{_LEVEL}"
)
_BRIGHTER = re.compile(
    r"(?:turn |make )?(?:the |my )?(?:screen )?(?:brightness up|brighter)"
    r"|(?:increase|raise) the brightness|make (?:it|the screen) brighter"
)
_DIMMER = re.compile(
    r"(?:turn |make )?(?:the |my )?(?:screen )?(?:brightness down|dimmer)"
    r"|(?:decrease|lower|reduce) the brightness|dim (?:the |my )?screen"
    r"|make (?:it|the screen) (?:dimmer|darker)"
)
_BATTERY = re.compile(
    r"(?:whats|what is|hows|how is|check) (?:the |my )?battery(?: level| percentage| percent)?"
    r"|how much battery(?: (?:do i have|is left|is there))?(?: left)?|battery(?: level)?"
)
_TIME = re.compile(r"(?:whats|what is) the time|what time is it(?: now)?|(?:tell me )?the time")
_DATE = re.compile(
    r"(?:whats|what is) (?:the|todays) date|what day is it(?: today)?|whats today"
    r"|what is today|(?:whats|what is) the day(?: today)?"
)
_CANCEL_TIMER = re.compile(r"\b(?:cancel|stop|delete|clear|remove)\b.*\btimers?\b")
_TIMER = re.compile(r"\btimers?\b")
_REMIND = re.compile(r"remind me\b(?P<rest>.*)", re.I | re.S)
_LIST_REMINDERS = re.compile(
    r"(?:what are|whats|show|list|read)(?: me)? my reminders|do i have (?:any )?reminders"
)
_CANCEL_REMINDERS = re.compile(r"(?:cancel|delete|clear|remove) (?:all )?(?:my |the )?reminders?")
_NOTE = re.compile(
    r"^(?:(?:take|make|add|write|save)(?: down)? a (?:quick )?note|note to self|note down"
    r"|note that|make a note of)[\s,:.-]*(?:that |saying |to say |to )?(?P<text>.+)$",
    re.I | re.S,
)
_READ_NOTES = re.compile(
    r"(?:read|show|tell)(?: me)? my (?:last |latest |recent )?notes?|what are my notes"
    r"|whats in my notes"
)
_OPEN_NOTES = re.compile(r"open my notes?")
_TYPE = re.compile(r"^(?:type|dictate)[\s,:]+(?P<text>.+)$", re.I | re.S)
_SCREENSHOT = re.compile(
    r"(?:take|grab|capture|save) a screenshot|screenshot|capture (?:the|my) screen"
    r"|take a picture of (?:the|my) screen"
)
_WINDOWS = {
    "minimize": r"minimi[sz]e(?: this| the| that)?(?: window| app)?",
    "maximize": r"maximi[sz]e(?: this| the| that)?(?: window| app)?"
    r"|make (?:this|the) window (?:bigger|full screen)",
    "restore": r"restore(?: this| the| that)? window",
    "close": r"close (?:this|the|that) (?:window|app)",
    "desktop": r"show (?:me )?(?:the |my )?desktop|minimi[sz]e (?:everything|all windows)",
    "switch": r"switch (?:window|windows|app|apps)|(?:go to (?:the )?)?(?:next|other) window",
}
_WINDOW_PATTERNS = {key: re.compile(pattern) for key, pattern in _WINDOWS.items()}
_REPEAT = re.compile(
    r"repeat(?: that| it)?|say (?:that|it) again|(?:come|say) again|what did you say|pardon"
)
_HELP = re.compile(r"what can (?:you do|i say|i ask(?: you)?)|help(?: me)?|what do you do")
# Ways to end the conversation after a reply: nothing to do, and nothing more to listen for.
# "The lamp" or "the lights": all of your lamps; and the words around what you want them to do.
_LAMP_WORDS = ("lamps", "lights", "lamp", "light")
_LAMP_FILLER = re.compile(
    r"\b(?:turn|switch|set|make|change|put|the|my|to|into|at|please|colou?r|brightness|a|it|both"
    r"|all|of)\b"
)
# Abdoh's name however speech recognition wrote it ("abdo", "abdu", "abdou", "abdul").
_NAME = r"(?:(?:hey|ya) )?ab ?d(?:oh?|oo|ou|u|ul)"
_DONE = re.compile(
    r"(?:no |okay |ok )?(?:thanks|thank you|thanks a lot|thank you very much|thats all|thats it"
    r"|never mind|nevermind|nothing|no|nope|stop|cancel|goodbye|bye|okay|ok|alright|all right"
    r"|great|perfect|cool|awesome|got it|good|nice|done|thats great|thats perfect|sounds good)"
    rf"(?: (?:thanks|thank you))?(?: {_NAME})?"
)
# What you might say while Abdoh is talking: sounds, "I'm listening", and "be quiet".
_FILLER = re.compile(r"(?:(?:uh|um|umm|hmm|hm|mm|mmm|ah|er|erm|oh)\s*)+")
_BACKCHANNEL = re.compile(
    r"(?:okay|ok|yeah|yes|yep|right|i see|got it|sure|uh huh|mm hmm|mhm|wow|nice|cool|really"
    r"|oh|alright|all right|go on|continue|keep going|and|so)(?: (?:okay|ok|yeah|right|sure))?"
)
_HUSH = re.compile(
    r"(?:okay |ok )?(?:wait|hold on|one second|one sec|one moment|just a (?:second|moment)|enough"
    r"|thats enough|be quiet|quiet|shut up|stop talking|stop it|pause|shh+|hush)"
    rf"(?: (?:please|{_NAME}|a second|a moment))?"
)
# "Shut up", "I'm not talking to you": the conversation is over, now, without a word, and
# Abdoh goes back to waiting for its wake word. (Not "pause" or "stop listening": those do
# other things.)
_DISMISS = re.compile(
    r"(?:(?:no|sorry|oh|okay|ok|hey|dude|bro|please|just) )*"
    r"(?:shut up|shut it|be quiet|keep quiet|quiet|silence|stop talking|hush|shh+"
    r"|(?:(?:im|i am|i was) not|i wasnt|im not|not) talking to you"
    r"|(?:im|i am|i was) talking to (?:someone else|somebody else|my \w+|him|her|them)"
    r"|(?:that|this|it) (?:wasnt|isnt|was not|is not) (?:for|to|meant for) you"
    r"|not (?:you|for you|to you|now)|(?:nobody|no one) (?:asked|was talking to) you"
    r"|i didnt ask you|go away|leave me alone|forget it|ignore (?:that|me|it|this))"
    rf"(?: (?:please|now|ok|okay|thanks|bro|dude|man|{_NAME}))*"
)
_LOCK = re.compile(r"lock (?:my |the )?(?:computer|pc|laptop|screen|workstation)")
# One app's volume in the mixer: "lower the browser", "set spotify to 20 percent".
_APP = r"(?:the |my )?(?P<app>[a-z][a-z0-9 ]{1,30}?)(?: volume| sound| audio)?"
_APP_SET = re.compile(rf"(?:set|turn|put|change|make) {_APP} (?:to|at) {_LEVEL}")
_APP_DOWN = [
    re.compile(rf"(?:lower|turn down|decrease|reduce|quieten) {_APP}"),
    re.compile(rf"turn {_APP} down"),
    re.compile(rf"make {_APP} quieter"),
]
_APP_UP = [
    re.compile(rf"(?:raise|turn up|increase|boost) {_APP}"),
    re.compile(rf"turn {_APP} up"),
    re.compile(rf"make {_APP} louder"),
]
_APP_MUTE = re.compile(rf"mute {_APP}")
_APP_UNMUTE = re.compile(rf"unmute {_APP}")
_PLAYING = re.compile(
    r"whats playing|what is playing|(?:which|what) apps? (?:is|are) (?:playing|making sound)"
)
APP_STEP = 20
_OPEN = re.compile(r"(?:open|launch|start) (?P<app>.+)")

BRIGHTNESS_STEP = 20
HELP = (
    "I can run your own commands, set timers and reminders, take notes, do quick maths, change "
    "the volume and the brightness, open apps and websites, play things on YouTube, type what "
    "you dictate, take screenshots, and ask Claude about everything else."
)


def interruption_kind(text: str) -> str:
    """What you said while Abdoh was talking: "nothing" (no words, or "um"), "backchannel"
    ("okay", "right": Abdoh goes on), "stop" ("wait", "thanks", "stop": it goes quiet) or
    "request" (anything else: it stops and does that instead)."""
    words = normalize(text)
    if not words or _FILLER.fullmatch(words):
        return "nothing"
    if _BACKCHANNEL.fullmatch(words):
        return "backchannel"
    if _DONE.fullmatch(words) or _HUSH.fullmatch(words) or _DISMISS.fullmatch(words):
        return "stop"
    return "request"


def spoken_number(text: str) -> int | None:
    """'75', 'seventy five' or 'twenty percent' -> 75 (or 20)."""
    text = re.sub(r"\s*percent$", "", text.strip())
    if text.isdigit():
        return int(text)
    total = 0
    for word in text.split():
        if word not in _NUMBERS or word in ("a", "an"):
            return None
        total += _NUMBERS[word]
    return total if text.strip() else None


def _yours(text: str) -> str:
    """'call my mother' -> 'call your mother' (for saying a reminder back)."""
    swaps = {"my": "your", "me": "you", "i": "you", "im": "you're", "i'm": "you're", "am": "are"}
    return " ".join(swaps.get(w.lower(), w) for w in text.split())


def parse_reminder(rest: str, now: datetime | None = None) -> tuple[datetime, str, str] | None:
    """What follows "remind me": (when, what, how to say when), or None if it can't be read.

    'to call mom in 20 minutes', 'in an hour to stretch', 'at 5:30 pm to leave',
    'to take out the bins tomorrow at 8'.
    """
    now = now or datetime.now()
    rest = " ".join(rest.strip().strip(".!?").split())
    low = rest.lower()
    starts = sorted({m.start() for m in re.finditer(r"\b(?:in|at|tomorrow|tonight)\b", low)})
    ends = sorted({len(low), *(m.start() for m in re.finditer(r",| to | that ", low))})
    for start in [*reversed(starts), *starts]:  # the time is usually at the end, or the start
        for end in ends:
            if end <= start:
                continue
            when_text = low[start:end].strip()
            what = f"{rest[:start]} {rest[end:]}".strip(" ,")
            what = re.sub(r"^(?:to|that|about)\s+", "", what, flags=re.I).strip(" ,")
            if not what:
                continue
            if when_text.startswith("in "):
                duration = parse_duration(when_text)
                if duration and re.fullmatch(r"in [\w .]+", when_text):
                    return now + timedelta(seconds=duration[0]), what, f"in {_plural(duration)}"
            else:
                day = re.search(r"\b(?:tomorrow|tonight)\b", what, flags=re.I)
                if day:  # "... tomorrow at 8": the day belongs to the time, not the task
                    when_text = f"{day[0].lower()} {when_text}"
                    what = f"{what[: day.start()]} {what[day.end() :]}".strip(" ,")
                    what = re.sub(r"^(?:to|that|about)\s+", "", " ".join(what.split()), flags=re.I)
                when = parse_clock(when_text, now) if what else None
                if when:
                    return when, what, _at(when, now)
    return None


def _plural(duration: tuple[float, str]) -> str:
    _, label = duration
    return label if label.startswith("1 ") and "half" not in label else f"{label}s"


def _at(when: datetime, now: datetime) -> str:
    text = clock_text(when, now)
    return text if text.startswith(("tomorrow", when.strftime("%A"))) else f"at {text}"


class LocalSkills:
    def __init__(self, computer, last_reply=lambda: "", allow_power=lambda: True):
        from abdoh.system_skills import SystemSkills

        self.computer = computer
        self._last_reply = last_reply  # what Abdoh said last, for "repeat that"
        self.system = SystemSkills(computer, allow_power, last_reply)

    def handle(self, request: str, original: str = "") -> str | None:
        """The reply ("" = done quietly) if this is a local skill, or None to let Claude try.

        `request` is normalized text (lowercase, no punctuation, wake words removed);
        `original` is the same request as it was said (for notes, typing and sums).
        """
        request = _POLITE.sub("", request).strip()
        original = (original or request).strip()
        try:
            reply = self._handle(request, original)
        except ActionError as e:
            return str(e)
        quiet = _DONE.fullmatch(request) or _DISMISS.fullmatch(request)
        if reply == "" and not isinstance(reply, Done) and not quiet:
            return Done("")  # did something quietly (a media key, a window): the done sound
        return reply

    def _handle(self, request: str, original: str) -> str | None:
        computer = self.computer
        answer = self.system.answer(request)  # "yes" to "Shut down the computer?"
        if answer is not None:
            return answer
        if _DONE.fullmatch(request):
            return ""
        if _DISMISS.fullmatch(request):
            log.info("Told to be quiet: back to waiting for the wake word")
            return ""
        if _REPEAT.fullmatch(request):
            return self._last_reply() or "I haven't said anything yet."
        if _HELP.fullmatch(request):
            return HELP
        for handler in (
            self._sound,
            self._screen,
            self._time_and_reminders,
            self._writing,
            self._app_sound,
        ):
            reply = handler(request, original)
            if reply is not None:
                return reply
        for key, pattern in _MEDIA_PATTERNS.items():
            if pattern.fullmatch(request):
                computer.media(key)
                return ""
        for action, pattern in _WINDOW_PATTERNS.items():
            if pattern.fullmatch(request):
                computer.window(action)
                return ""
        if _LOCK.fullmatch(request):
            computer.lock()
            return ""
        reply = self.system.handle(request, original)
        if reply is not None:
            return reply
        reply = self._lamps(request)
        if reply is not None:
            return reply
        found = _OPEN.fullmatch(request)
        if found and computer.apps.find(found.group("app")):
            return Done(f"Opening {computer.open_app(found.group('app'))}.")
        return None

    def _sound(self, request: str, original: str) -> str | None:
        computer = self.computer
        if _UNMUTE.fullmatch(request):
            computer.set_muted(False)
            return ""
        if _MUTE.fullmatch(request):
            computer.set_muted(True)
            return ""
        if _VOLUME_MAX.fullmatch(request):
            return Done(f"Volume at {computer.set_volume(100)} percent.")
        if _ASK_VOLUME.fullmatch(request):
            return f"The volume is at {computer.volume()} percent."
        found = _VOLUME.fullmatch(request)
        level = spoken_number(found["level"]) if found else None
        if level is not None and level <= 100:
            return Done(f"Volume at {computer.set_volume(level)} percent.")
        return None

    def _lamps(self, request: str) -> str | None:
        """Your smart lamps (abdoh/lights.py): "turn off the lamp", "lights blue", "dim the desk
        lamp to 30 percent", "make the light warm". Only once you have lamps; anything it can't
        read is left for Claude."""
        from abdoh.lights import setting

        lamps = getattr(self.computer, "lamps", None)
        known = lamps.all() if lamps is not None else []
        if not known:
            return None
        names = {lamp.name.lower() for lamp in known} | set(_LAMP_WORDS)
        longest_first = sorted(names, key=len, reverse=True)  # "desk lamp" before "lamp"
        said = next((n for n in longest_first if re.search(rf"\b{re.escape(n)}\b", request)), None)
        if said is None:
            return None
        how = re.sub(rf"\b{re.escape(said)}\b", " ", request, count=1)
        how = " ".join(_LAMP_FILLER.sub(" ", how).split())
        if re.fullmatch(r"(?:(?:dim|dimmer|bright|brighter) )?\d{1,3}", how):
            how += "%"  # "dim the lamp to 30", "desk lamp 50"
        elif request.startswith("dim") and not how:
            how = "dim"
        try:
            setting(how, strict=True)  # all of it: "the light in the ocean film" isn't one
        except ActionError:
            return None  # "what colour is the lamp": a question for Claude
        names_set = lamps.set("all" if said in _LAMP_WORDS else said, how)
        return Done(f"{' and '.join(names_set)}: {how}.")

    def _app_sound(self, request: str, original: str) -> str | None:
        """One app's volume. Only for apps in the volume mixer: anything else ("turn the
        lights down") is left for your commands or Claude."""
        computer = self.computer
        if not hasattr(computer, "find_app_audio"):
            return None
        if _PLAYING.fullmatch(request):
            playing = computer.playing_apps()
            if not playing:
                return "Nothing is playing right now."
            return f"Playing now: {', '.join(playing)}."
        found = _APP_SET.fullmatch(request)
        if found:
            level = spoken_number(found["level"])
            if level is not None and level <= 100 and computer.find_app_audio(found["app"]):
                name = computer.set_app_volume(found["app"], level)
                return Done(f"{name} at {level} percent.")
            return None
        for patterns, step in ((_APP_DOWN, -APP_STEP), (_APP_UP, APP_STEP)):
            for pattern in patterns:
                found = pattern.fullmatch(request)
                if found and computer.find_app_audio(found["app"]):
                    name, level = computer.change_app_volume(found["app"], step)
                    return Done(f"{name} at {level} percent.")
        for pattern, muted in ((_APP_MUTE, True), (_APP_UNMUTE, False)):
            found = pattern.fullmatch(request)
            if found and computer.find_app_audio(found["app"]):
                name = computer.mute_app(found["app"], muted)
                return Done(f"{name} {'muted' if muted else 'unmuted'}.")
        return None

    def _screen(self, request: str, original: str) -> str | None:
        computer = self.computer
        found = _BRIGHTNESS.fullmatch(request)
        level = spoken_number(found["level"]) if found else None
        if level is not None and level <= 100:
            return Done(f"Brightness at {computer.set_brightness(level)} percent.")
        if _BRIGHTER.fullmatch(request):
            computer.set_brightness(min(100, computer.brightness() + BRIGHTNESS_STEP))
            return ""
        if _DIMMER.fullmatch(request):
            computer.set_brightness(max(0, computer.brightness() - BRIGHTNESS_STEP))
            return ""
        if _SCREENSHOT.fullmatch(request):
            path = computer.screenshot()
            return Done(f"Saved a screenshot in your {path.parent.name} folder.")
        if _BATTERY.fullmatch(request):
            state = computer.battery()
            if state is None:
                return "This computer doesn't have a battery."
            percent, plugged = state
            return f"The battery is at {percent} percent{' and charging' if plugged else ''}."
        return None

    def _time_and_reminders(self, request: str, original: str) -> str | None:
        computer = self.computer
        now = getattr(computer, "now", datetime.now)()
        if _TIME.fullmatch(request):
            return f"It's {clock_text(now, now)}."
        if _DATE.fullmatch(request):
            return f"It's {now:%A}, {now:%B} {now.day}."
        if _CANCEL_TIMER.search(request):
            reply = computer.timers.cancel_all()
            return Done(reply) if reply.startswith("Timer cancelled") else reply
        if _TIMER.search(request) and parse_duration(request):
            reply = computer.timer(request)
            return Done(reply) if reply.startswith("Okay,") else reply
        if _CANCEL_REMINDERS.fullmatch(request):
            count = computer.reminders.cancel_all()
            return Done("Your reminders are cancelled.") if count else "You have no reminders."
        if _LIST_REMINDERS.fullmatch(request):
            pending = computer.reminders.pending()
            if not pending:
                return "You have no reminders."
            said = [f"{text}, {_at(when, now)}" for when, text in pending[:5]]
            return f"You have {len(pending)}: " + "; ".join(said) + "."
        found = _REMIND.search(original)
        if found:
            parsed = parse_reminder(found["rest"], now)
            if parsed is None:
                return None  # Claude can work out what was meant (and use its remind action)
            when, what, said = parsed
            computer.reminders.add(when, _yours(what))
            return Done(f"Okay, I'll remind you to {_yours(what)} {said}.")
        return None

    def _writing(self, request: str, original: str) -> str | None:
        computer = self.computer
        if _READ_NOTES.fullmatch(request):
            notes = computer.notes.recent()
            if not notes:
                return "You have no notes."
            return "Your latest notes: " + "; ".join(n.rstrip(".") for n in notes) + "."
        if _OPEN_NOTES.fullmatch(request):
            computer.open_notes()
            return ""
        found = _NOTE.match(original)
        if found:
            computer.notes.add(found["text"].strip())
            return Done("Noted.")
        found = _TYPE.match(original)
        if found:
            computer.type_text(found["text"].strip())
            return ""
        return calculate(original)
