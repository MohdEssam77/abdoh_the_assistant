"""What Codoh is doing, when the user asks Abdoh (ACTION codoh_state, abdoh/codoh/report.py):
every recent chat, started by voice or on the page, whatever Abdoh's window shows."""

import json

from test_codoh_manager import World

from abdoh.codoh.report import ago, report, todo_list


def todo(engine, steps):
    todos = [{"content": text, "status": status} for text, status in steps]
    engine.on_event({"type": "tool", "id": "todo1", "name": "TodoWrite", "input": {"todos": todos}})


def test_the_report_has_what_each_chat_does(tmp_path):
    world = World(tmp_path)
    codoh = world.codoh
    older = world.chat()
    codoh.send(older, "explain the project")
    world.engines[0].on_event({"type": "text", "delta": "It's a weather app."})
    world.engines[0].on_event({"type": "done", "ok": True, "seconds": 2})
    world.clock.now += 120
    busy = world.chat()
    codoh.send(busy, "add the project to the portfolio")  # typed on the page
    engine = world.engines[1]
    engine.on_event({"type": "text", "delta": "I'll add the card, then build the site."})
    todo(engine, [("Read the projects", "completed"), ("Add the card", "in_progress"),
                  ("Build the site", "pending")])  # fmt: skip
    data = {"command": "pnpm build", "description": "Build the site"}
    engine.on_event({"type": "tool", "id": "t2", "name": "Bash", "input": data})
    engine.on_event(
        {"type": "approval", "id": "r1", "tool": "Bash", "input": data, "tool_use_id": "t2"}
    )
    text = report(codoh, "what is Codoh doing and what's left?", now=world.clock.now)
    first, second = text.split("\n\nChat 2:")
    assert first.count("Chat 1:") == 1 and '"add the project to the portfolio"' in first
    assert "Now: waiting for the user to allow or deny this: pnpm build (Build the site)" in first
    assert "Its to-do list (2 of 3 left): [done] Read the projects; [doing now] Add the card; "
    assert "[to do] Build the site" in first
    assert "User: add the project to the portfolio" in first
    assert "Codoh: I'll add the card, then build the site." in first
    assert "ran pnpm build (not done yet: waiting for the user's OK)" in first
    assert '"explain the project"' in second and "Now: finished" in second
    assert "The user's request was: \"what is Codoh doing and what's left?\"" in text


def test_no_chats_yet(tmp_path):
    world = World(tmp_path)
    assert "Codoh has no chats yet" in report(world.codoh, "what's Codoh doing?")


def test_a_question_and_an_error_are_said(tmp_path):
    world = World(tmp_path)
    codoh = world.codoh
    chat = world.chat()
    codoh.send(chat, "add the project")
    engine = world.engines[0]
    question = {"question": "Which project?", "options": [{"label": "Abdoh"}, {"label": "Quiz"}]}
    data = {"questions": [question]}
    engine.on_event({"type": "tool", "id": "q", "name": "AskUserQuestion", "input": data})
    engine.on_event({"type": "approval", "id": "r", "tool": "AskUserQuestion", "input": data})
    text = report(codoh, "status?", now=world.clock.now)
    assert (
        "waiting for the user to answer its question: Which project? (options: Abdoh, Quiz)" in text
    )
    codoh.answer(chat, [i for i in codoh.chat(chat)["items"] if i["kind"] == "approval"][0]["id"],
                 "deny")  # fmt: skip
    engine.on_event({"type": "done", "ok": False, "error": "Claude Code stopped unexpectedly."})
    assert "stopped with an error just now: Claude Code stopped unexpectedly." in report(
        codoh, "status?", now=world.clock.now
    )


def test_the_to_do_list_and_times():
    detail = json.dumps([{"text": "a", "status": "completed"}, {"text": "b", "status": "pending"}])
    items = [{"kind": "tool", "kind_of": "todo", "detail": detail}]
    assert todo_list(items) == [("a", "done"), ("b", "to do")]
    assert todo_list([]) == []
    assert (
        ago(100, 130) == "just now"
        and ago(0, 7200) == "2 hours ago"
        and ago(0, 90000) == "yesterday"
    )


def test_claude_asks_and_answers_from_the_report(tmp_path):
    from test_router import FakeBrain

    from abdoh.commands.registry import CommandRegistry
    from abdoh.config import Config
    from abdoh.router import Router

    world = World(tmp_path)
    chat = world.chat()
    world.codoh.send(chat, "fix the tests")

    class TwoAnswers(FakeBrain):
        def stream(self, prompt, image_png=None):
            self.asked.append((prompt, image_png))
            first = len(self.asked) == 1
            yield "ACTION codoh_state: what it's doing\n" if first else "It's fixing the tests."

    brain = TwoAnswers()
    router = Router(Config(app_dir=tmp_path / "abdoh"), CommandRegistry(tmp_path / "x.yaml"),
                    brain=brain)  # fmt: skip
    router.codoh = lambda: world.codoh
    reply = " ".join(router.handle("Abdoh, what is Codoh doing?"))
    assert reply == "It's fixing the tests."
    follow_up = brain.asked[1][0]
    assert follow_up.startswith("Here is what Codoh") and '"fix the tests"' in follow_up


def test_without_codoh_claude_has_no_such_action(tmp_path):
    from abdoh.claude.brain import system_prompt
    from abdoh.config import Config

    assert "ACTION codoh_state:" in system_prompt(Config())
