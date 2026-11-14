from abdoh.claude.reply import ACTION_HELP, clean_for_speech, speakable


def run(chunks, allowed=tuple(ACTION_HELP)):
    actions = []
    sentences = list(speakable(chunks, lambda k, a: actions.append((k, a)), allowed))
    return sentences, actions


def test_sentences_are_yielded_as_soon_as_they_end():
    seen = []
    chunks = ["Tokyo is the cap", "ital of Japan. It has ", "about fourteen million people."]
    gen = speakable(iter(chunks), lambda k, a: None)
    for sentence in gen:
        seen.append(sentence)
        if len(seen) == 1:
            assert sentence == "Tokyo is the capital of Japan."
    assert seen == ["Tokyo is the capital of Japan.", "It has about fourteen million people."]


def test_first_sentence_arrives_before_the_rest_of_the_reply():
    def chunks():
        yield "Hello there. "
        raise AssertionError("the first sentence should be yielded before reading more")

    assert next(speakable(chunks(), lambda k, a: None)) == "Hello there."


def test_action_lines_run_and_are_not_spoken():
    sentences, actions = run(
        ["ACTION open_url: https://www.python.org\n", "Opening Python's site."]
    )
    assert actions == [("open_url", "https://www.python.org")]
    assert sentences == ["Opening Python's site."]


def test_action_split_across_chunks():
    sentences, actions = run(["ACT", "ION open_app: Spot", "ify\nDone."])
    assert actions == [("open_app", "Spotify")]
    assert sentences == ["Done."]


def test_action_on_the_last_line_without_newline():
    _, actions = run(["Sure.\nACTION open_app: Notepad"])
    assert actions == [("open_app", "Notepad")]


def test_unknown_actions_are_ignored():
    sentences, actions = run(["ACTION run: format c:\nNo."])
    assert actions == []
    assert sentences == ["No."]


def test_allowed_list_is_respected():
    _, actions = run(["ACTION open_url: https://x.y\n"], allowed=("open_app",))
    assert actions == []


def test_words_starting_with_a_is_not_held_back_forever():
    sentences, _ = run(["Actually, ", "yes. Fine."])
    assert sentences == ["Actually, yes.", "Fine."]


def test_numbers_with_dots_are_not_split():
    sentences, _ = run(["Pi is about 3.14 and e is 2.72."])
    assert sentences == ["Pi is about 3.14 and e is 2.72."]


def test_markdown_and_links_are_cleaned():
    sentences, _ = run(["## Answer\n- **Tokyo** is the `capital`. See https://x.y/z for more."])
    assert sentences == ["Answer", "Tokyo is the capital.", "See the link for more."]


def test_clean_for_speech():
    assert clean_for_speech("1. One\n2. Two") == "One Two"
    assert clean_for_speech("Use ```code``` here") == "Use here"
