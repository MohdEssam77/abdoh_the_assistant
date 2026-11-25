"""Your ChatGPT plan through "Sign in with ChatGPT" (story 109, GitHub issue #2): the sign-in's
checks, the tokens kept safe and refreshed, the models, signing out, and the brain's streamed
answers and failures. No network: OpenAI is faked, and the ID tokens are signed here."""

import base64
import hashlib
import json
import random
import sys
import time
from urllib.parse import parse_qs, urlparse

import pytest

from abdoh.claude import chatgpt
from abdoh.claude.brain import BrainError, make_brain
from abdoh.claude.chatgpt import (
    API,
    APP_NAME,
    FIRST_CLIENT,
    PLAN_SCOPE,
    REVOKE_URL,
    SCOPES,
    TOKEN_URL,
    Account,
    ChatGPTBrain,
    Session,
    SignIn,
    SignInError,
    verify_id_token,
)
from abdoh.config import Config

# ----- a small RSA key, made here, to sign ID tokens like OpenAI does -----


def _prime(bits, rng):
    while True:
        n = rng.getrandbits(bits) | (1 << (bits - 1)) | 1
        if all(pow(a, n - 1, n) == 1 for a in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)):
            return n


def _key():
    rng = random.Random(109)
    e = 65537
    while True:
        p, q = _prime(384, rng), _prime(384, rng)
        phi = (p - 1) * (q - 1)
        if p != q and phi % e:
            return p * q, e, pow(e, -1, phi)


N, E, D = _key()


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


JWK = {
    "kty": "RSA",
    "kid": "test-key",
    "n": b64url(N.to_bytes((N.bit_length() + 7) // 8, "big")),
    "e": b64url(E.to_bytes(3, "big")),
}


def sign(claims: dict, kid="test-key", alg="RS256") -> str:
    head = b64url(json.dumps({"alg": alg, "kid": kid}).encode())
    body = b64url(json.dumps(claims).encode())
    size = (N.bit_length() + 7) // 8
    digest = chatgpt._SHA256_INFO + hashlib.sha256(f"{head}.{body}".encode()).digest()
    padded = b"\x00\x01" + b"\xff" * (size - 3 - len(digest)) + b"\x00" + digest
    signature = pow(int.from_bytes(padded, "big"), D, N).to_bytes(size, "big")
    return f"{head}.{body}.{b64url(signature)}"


def claims(nonce, client="client-abdoh-1", **extra):
    return {"iss": "https://auth.openai.com", "aud": client, "sub": "user-1",
            "email": "you@example.com", "exp": time.time() + 3600, "nonce": nonce,
            **extra}  # fmt: skip


# ----- OpenAI, faked -----


class Response:
    def __init__(self, status=200, data=None, lines=()):
        self.status_code = status
        self._data = data if data is not None else {}
        self._lines = list(lines)
        self.text = json.dumps(self._data)

    def json(self):
        return self._data

    def read(self):
        return self.text.encode()

    def iter_lines(self):
        yield from self._lines

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpenAI:
    """Answers each call with the next prepared response for that URL; records the calls."""

    def __init__(self):
        self.answers: dict[str, list[Response]] = {}
        self.calls: list[tuple[str, str, dict]] = []

    def answer(self, url, *responses):
        self.answers.setdefault(url, []).extend(responses)

    def _next(self, url):
        queue = self.answers.get(url) or []
        if not queue:
            raise AssertionError(f"nothing prepared for {url}")
        return queue.pop(0)

    def post(self, url, data=None, **kw):
        self.calls.append(("POST", url, data or {}))
        return self._next(url)

    def get(self, url, headers=None, **kw):
        self.calls.append(("GET", url, headers or {}))
        return self._next(url)

    def stream(self, method, url, json=None, headers=None):
        self.calls.append((method, url, {"json": json, "headers": headers}))
        return self._next(url)

    def close(self):
        pass


def scramble(data: bytes) -> bytes:
    return bytes(b ^ 0x5A for b in data)  # stands in for Windows' encryption


def account(tmp_path) -> Account:
    return Account(tmp_path / "chatgpt", protect=scramble, unprotect=scramble)


def token_answer(
    nonce, scope=SCOPES, refresh="refresh-1", access="access-1", client="client-abdoh-1"
):  # noqa: E501
    return {"access_token": access, "refresh_token": refresh, "token_type": "Bearer",
            "expires_in": 3600, "scope": scope,
            "id_token": sign(claims(nonce, client))}  # fmt: skip


def signed_in(tmp_path, scope=SCOPES, expires_in=3600) -> Account:
    acc = account(tmp_path)
    acc.update(client_id="client-abdoh-1", email="you@example.com", subject="user-1")
    acc.save_tokens({"access_token": "access-1", "refresh_token": "refresh-1", "id_token": "",
                     "expires_at": time.time() + expires_in, "scopes": scope.split()})  # fmt: skip
    return acc


# ----- what's kept on this computer -----


def test_this_installation_has_one_lasting_id(tmp_path):
    acc = account(tmp_path)
    host = acc.host_id()
    assert host.startswith("urn:uuid:") and acc.host_id() == host
    assert account(tmp_path).host_id() == host


def test_the_tokens_are_kept_encrypted_and_signing_out_keeps_the_client(tmp_path):
    acc = signed_in(tmp_path)
    raw = (tmp_path / "chatgpt" / "tokens.bin").read_bytes()
    assert b"access-1" not in raw and acc.tokens()["access_token"] == "access-1"
    assert b"access" not in (tmp_path / "chatgpt" / "account.json").read_bytes()
    assert acc.connected and acc.plan_usage
    acc.clear_tokens()
    assert not acc.connected and acc.tokens() is None
    assert acc.info()["client_id"] == "client-abdoh-1"  # kept, for connecting again


@pytest.mark.skipif(sys.platform != "win32", reason="Windows' own encryption (DPAPI)")
def test_windows_encrypts_the_tokens_for_this_user():
    secret = b'{"access_token": "abc"}'
    sealed = chatgpt._protect(secret)
    assert sealed != secret and b"abc" not in sealed
    assert chatgpt._unprotect(sealed) == secret


# ----- the ID token -----


def test_a_good_id_token_is_accepted():
    found = verify_id_token(sign(claims("n1")), "client-abdoh-1", "n1", [JWK])
    assert found["sub"] == "user-1" and found["email"] == "you@example.com"


@pytest.mark.parametrize(
    "token, client, nonce",
    [
        (sign(claims("other")), "client-abdoh-1", "n1"),  # another sign-in's
        (sign(claims("n1")), "client-someone-else", "n1"),  # for another app
        (sign(claims("n1", iss="https://evil.example")), "client-abdoh-1", "n1"),
        (sign(claims("n1", exp=time.time() - 3600)), "client-abdoh-1", "n1"),  # out of date
        (sign(claims("n1"), kid="unknown"), "client-abdoh-1", "n1"),
        (sign(claims("n1"), alg="none"), "client-abdoh-1", "n1"),
        (sign(claims("n1"))[:-6] + "AAAAAA", "client-abdoh-1", "n1"),  # changed signature
        ("not.a.token", "client-abdoh-1", "n1"),
    ],
)
def test_a_wrong_id_token_is_refused(token, client, nonce):
    with pytest.raises(SignInError):
        verify_id_token(token, client, nonce, [JWK])


# ----- signing in -----


def first_sign_in(tmp_path, openai=None):
    openai = openai or FakeOpenAI()
    sign_in = SignIn(account(tmp_path), http=openai, open_browser=lambda url: None)
    url = sign_in.authorize_url(1455)
    return sign_in, openai, {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


def test_the_first_sign_in_registers_abdoh(tmp_path):
    sign_in, _, query = first_sign_in(tmp_path)
    assert query["client_id"] == FIRST_CLIENT and query["agent_name_hint"] == APP_NAME
    assert query["ext_agent_host_id"].startswith("urn:uuid:")
    assert query["redirect_uri"] == "http://127.0.0.1:1455/auth/callback"
    assert PLAN_SCOPE in query["scope"].split() and query["resource"] == API
    assert query["response_type"] == "code" and query["code_challenge_method"] == "S256"
    expected = b64url(hashlib.sha256(sign_in._verifier.encode()).digest())
    assert query["code_challenge"] == expected  # PKCE
    assert query["state"] and query["nonce"] and query["state"] != query["nonce"]


def test_signing_in_again_uses_abdohs_own_client(tmp_path):
    signed_in(tmp_path).clear_tokens()
    sign_in = SignIn(account(tmp_path), http=FakeOpenAI(), open_browser=lambda url: None)
    query = parse_qs(urlparse(sign_in.authorize_url(1455)).query)
    assert query["client_id"] == ["client-abdoh-1"] and "agent_name_hint" not in query
    assert query["login_hint"] == ["you@example.com"]


def come_back(sign_in, query, client="client-abdoh-1"):
    params = {"state": sign_in._state, **query}
    if client:
        params["client_id"] = client
    from urllib.parse import urlencode

    return sign_in.callback(f"/auth/callback?{urlencode(params)}")


def test_a_finished_sign_in_is_checked_and_kept(tmp_path):
    sign_in, openai, query = first_sign_in(tmp_path)
    openai.answer(TOKEN_URL, Response(data=token_answer(query["nonce"])))
    openai.answer(chatgpt.JWKS_URL, Response(data={"keys": [JWK]}))
    status, page = come_back(sign_in, {"code": "the-code", "scope": SCOPES})
    assert status == 200 and "connected" in page
    assert sign_in.state == "done" and sign_in.plan_usage and sign_in.first
    _, url, form = openai.calls[0]
    assert url == TOKEN_URL and form == {
        "grant_type": "authorization_code", "client_id": "client-abdoh-1", "code": "the-code",
        "code_verifier": sign_in._verifier, "redirect_uri": "http://127.0.0.1:1455/auth/callback",
        "resource": API,
    }  # fmt: skip
    acc = account(tmp_path)
    assert acc.plan_usage and acc.info()["email"] == "you@example.com"
    assert (
        acc.info()["client_id"] == "client-abdoh-1" and acc.tokens()["refresh_token"] == "refresh-1"
    )


def test_a_stranger_coming_back_changes_nothing(tmp_path):
    sign_in, openai, _ = first_sign_in(tmp_path)
    status, _ = sign_in.callback("/auth/callback?code=x&state=forged&client_id=c")
    assert status == 400 and sign_in.state == "waiting" and openai.calls == []
    assert sign_in.callback("/favicon.ico")[0] == 404


def test_saying_no_stops_without_asking_for_tokens(tmp_path):
    sign_in, openai, _ = first_sign_in(tmp_path)
    status, page = come_back(sign_in, {"error": "access_denied"}, client=None)
    assert status == 400 and sign_in.state == "failed" and "didn't allow" in sign_in.error
    assert openai.calls == [] and not account(tmp_path).connected


def test_a_registration_without_a_client_id_is_incomplete(tmp_path):
    sign_in, openai, _ = first_sign_in(tmp_path)
    come_back(sign_in, {"code": "the-code"}, client=None)
    assert sign_in.state == "failed" and openai.calls == []


def test_another_apps_client_id_is_refused(tmp_path):
    signed_in(tmp_path).clear_tokens()
    sign_in = SignIn(account(tmp_path), http=FakeOpenAI(), open_browser=lambda url: None)
    sign_in.authorize_url(1455)
    come_back(sign_in, {"code": "the-code"}, client="client-of-another-app")
    assert sign_in.state == "failed"


def test_without_plan_permission_it_is_connected_but_cant_use_the_plan(tmp_path):
    sign_in, openai, query = first_sign_in(tmp_path)
    openai.answer(TOKEN_URL, Response(data=token_answer(query["nonce"], scope="openid email")))
    openai.answer(chatgpt.JWKS_URL, Response(data={"keys": [JWK]}))
    come_back(sign_in, {"code": "the-code"})
    acc = account(tmp_path)
    assert sign_in.state == "done" and not sign_in.plan_usage
    assert acc.connected and not acc.plan_usage


def test_a_rejected_code_fails_the_sign_in(tmp_path):
    sign_in, openai, _ = first_sign_in(tmp_path)
    openai.answer(TOKEN_URL, Response(400, {"error": "invalid_grant"}))
    come_back(sign_in, {"code": "old-code"})
    assert sign_in.state == "failed" and not account(tmp_path).connected


# ----- the session -----


def test_a_fresh_token_is_used_as_it_is(tmp_path):
    openai = FakeOpenAI()
    assert Session(signed_in(tmp_path), openai).access_token() == "access-1"
    assert openai.calls == []


def test_a_token_about_to_run_out_is_refreshed_and_the_refresh_token_rotates(tmp_path):
    acc = signed_in(tmp_path, expires_in=30)
    openai = FakeOpenAI()
    fresh = {"access_token": "access-2", "refresh_token": "refresh-2", "expires_in": 3600,
             "scope": SCOPES}  # fmt: skip
    openai.answer(TOKEN_URL, Response(data=fresh))
    assert Session(acc, openai).access_token() == "access-2"
    assert openai.calls[0][2] == {"grant_type": "refresh_token", "client_id": "client-abdoh-1",
                                  "refresh_token": "refresh-1", "resource": API}  # fmt: skip
    kept = acc.tokens()
    assert kept["refresh_token"] == "refresh-2" and kept["expires_at"] > time.time() + 3000


@pytest.mark.parametrize("code", ["invalid_grant", "refresh_token_reused", "refresh_token_expired"])
def test_a_refresh_that_is_refused_means_connecting_again(tmp_path, code):
    acc = signed_in(tmp_path, expires_in=0)
    openai = FakeOpenAI()
    openai.answer(TOKEN_URL, Response(400, {"error": code}))
    with pytest.raises(BrainError, match="Connect again"):
        Session(acc, openai).access_token()
    assert not acc.connected and acc.info()["client_id"] == "client-abdoh-1"


def test_openai_being_down_keeps_the_tokens(tmp_path):
    acc = signed_in(tmp_path, expires_in=0)
    openai = FakeOpenAI()
    openai.answer(TOKEN_URL, Response(503, {"detail": "unavailable"}))
    with pytest.raises(BrainError, match="couldn't reach"):
        Session(acc, openai).access_token()
    assert acc.connected


def test_the_models_are_the_listed_ones_in_openais_order(tmp_path):
    openai = FakeOpenAI()
    openai.answer(f"{API}/models", Response(data={"models": [
        {"slug": "gpt-6.2-sol", "display_name": "GPT-6.2 Sol", "visibility": "list"},
        {"slug": "internal", "display_name": "Hidden", "visibility": "hide"},
        {"slug": "gpt-6-mini", "display_name": "GPT-6 mini", "visibility": "list"},
    ]}))  # fmt: skip
    found = Session(signed_in(tmp_path), openai).models()
    assert found == [{"id": "gpt-6.2-sol", "name": "GPT-6.2 Sol"},
                     {"id": "gpt-6-mini", "name": "GPT-6 mini"}]  # fmt: skip
    assert openai.calls[0][2]["Authorization"] == "Bearer access-1"


def test_disconnecting_revokes_the_session_and_forgets_the_tokens(tmp_path):
    acc = signed_in(tmp_path)
    openai = FakeOpenAI()
    openai.answer(REVOKE_URL, Response(200))
    assert Session(acc, openai).sign_out() is True
    assert openai.calls[0][2] == {"token": "refresh-1", "token_type_hint": "refresh_token",
                                  "client_id": "client-abdoh-1"}  # fmt: skip
    assert not acc.connected


def test_disconnecting_while_openai_is_down_still_forgets_the_tokens(tmp_path):
    acc = signed_in(tmp_path)
    openai = FakeOpenAI()
    openai.answer(REVOKE_URL, Response(503))
    assert Session(acc, openai).sign_out() is False
    assert not acc.connected


# ----- the brain -----


def events(*items) -> list[str]:
    return [f"data: {json.dumps(item)}" for item in items]


def delta(text):
    return {"type": "response.output_text.delta", "delta": text}


COMPLETED = {"type": "response.completed", "response": {"status": "completed"}}


def brain(tmp_path, openai, scope=SCOPES, model="gpt-6.2-sol"):
    cfg = Config(app_dir=tmp_path)
    cfg.claude.chatgpt_model = model
    acc = signed_in(tmp_path, scope=scope)
    return ChatGPTBrain(cfg, Session(acc, openai), http=openai)


def test_a_streamed_answer(tmp_path):
    openai = FakeOpenAI()
    lines = ["event: response.output_text.delta"] + events(
        delta("It's "), delta("sunny."), COMPLETED
    )
    openai.answer(f"{API}/responses", Response(lines=lines))
    assert "".join(brain(tmp_path, openai).stream("Weather?")) == "It's sunny."
    sent = openai.calls[0][2]["json"]
    assert sent["store"] is False and sent["stream"] is True and sent["model"] == "gpt-6.2-sol"
    assert "Abdoh" in sent["instructions"]
    assert (
        sent["input"][0]["role"] == "user"
        and sent["input"][0]["content"][0]["type"] == "input_text"
    )
    assert not any(item.get("role") == "system" for item in sent["input"])
    assert "max_output_tokens" not in sent and "temperature" not in sent  # the plan refuses them


def test_a_screenshot_goes_along_as_an_image(tmp_path):
    openai = FakeOpenAI()
    openai.answer(f"{API}/responses", Response(lines=events(delta("A list."), COMPLETED)))
    list(brain(tmp_path, openai).stream("What's this?", b"\x89PNG"))
    content = openai.calls[0][2]["json"]["input"][0]["content"]
    assert content[1]["type"] == "input_image"
    assert content[1]["image_url"].startswith("data:image/png;base64,")


def say(b, prompt="Hi"):
    out = []
    with pytest.raises(BrainError) as e:
        for piece in b.stream(prompt):
            out.append(piece)
    return "".join(out), str(e.value)


def test_the_usage_limit_mid_answer(tmp_path):
    openai = FakeOpenAI()
    limit = {"code": "subscription_sharing_usage_limit_exceeded"}
    failed = {"type": "response.failed", "response": {"error": limit}}
    openai.answer(f"{API}/responses", Response(lines=events(delta("Well"), failed)))
    said, error = say(brain(tmp_path, openai))
    assert said == "Well" and error == chatgpt.LIMIT


def test_an_incomplete_or_cut_off_answer_is_said_to_be_so(tmp_path):
    openai = FakeOpenAI()
    incomplete = {"type": "response.incomplete",
                  "response": {"incomplete_details": {"reason": "max_output_tokens"}}}  # fmt: skip
    openai.answer(f"{API}/responses", Response(lines=events(delta("Half"), incomplete)))
    assert say(brain(tmp_path, openai)) == ("Half", chatgpt.INCOMPLETE)
    openai.answer(f"{API}/responses", Response(lines=events(delta("Half"))))  # no ending
    assert say(brain(tmp_path, openai)) == ("Half", chatgpt.CUT_OFF)


@pytest.mark.parametrize(
    "status, body, said",
    [
        (429, {"error": {"code": "subscription_sharing_usage_limit_exceeded"}}, chatgpt.LIMIT),
        (403, {"error": {"code": "subscription_sharing_user_not_eligible"}}, chatgpt.NOT_ELIGIBLE),
        (503, {"error": {"code": "subscription_sharing_usage_unavailable"}}, chatgpt.BUSY),
        (503, {"detail": "routing unavailable"}, chatgpt.BUSY),
    ],
)
def test_refusals_before_the_answer(tmp_path, status, body, said):
    openai = FakeOpenAI()
    openai.answer(f"{API}/responses", Response(status, body))
    assert say(brain(tmp_path, openai))[1] == said


def test_a_rejected_token_is_refreshed_once(tmp_path):
    openai = FakeOpenAI()
    openai.answer(f"{API}/responses", Response(401, {"detail": "expired"}),
                  Response(lines=events(delta("OK"), COMPLETED)))  # fmt: skip
    openai.answer(TOKEN_URL, Response(data={"access_token": "access-2", "expires_in": 3600}))
    assert "".join(brain(tmp_path, openai).stream("Hi")) == "OK"
    headers = [
        c[2]["headers"]["Authorization"] for c in openai.calls if c[1].endswith("/responses")
    ]
    assert headers == ["Bearer access-1", "Bearer access-2"]


def test_without_plan_permission_nothing_is_sent(tmp_path):
    openai = FakeOpenAI()
    assert say(brain(tmp_path, openai, scope="openid email"))[1] == chatgpt.NO_PLAN_USAGE
    assert openai.calls == []


def test_without_a_chosen_model_the_first_listed_is_used(tmp_path):
    openai = FakeOpenAI()
    openai.answer(f"{API}/models", Response(data={"models": [{"slug": "gpt-6.2-sol"}]}))
    openai.answer(f"{API}/responses", Response(lines=events(delta("OK"), COMPLETED)))
    list(brain(tmp_path, openai, model="").stream("Hi"))
    assert openai.calls[-1][2]["json"]["model"] == "gpt-6.2-sol"


# ----- choosing it -----


def test_chosen_or_automatic(tmp_path):
    cfg = Config(app_dir=tmp_path)
    no_code = lambda path: None  # noqa: E731
    assert make_brain(cfg, find_code=no_code) is None  # not connected
    signed_in(tmp_path)
    assert isinstance(make_brain(cfg, find_code=no_code), ChatGPTBrain)  # automatic, last
    assert not isinstance(make_brain(cfg, find_code=lambda p: "claude.exe"), ChatGPTBrain)
    cfg.claude.backend = "chatgpt"
    assert isinstance(make_brain(cfg, find_code=lambda p: "claude.exe"), ChatGPTBrain)


def test_automatic_waits_for_plan_permission(tmp_path):
    cfg = Config(app_dir=tmp_path)
    signed_in(tmp_path, scope="openid email")
    assert make_brain(cfg, find_code=lambda path: None) is None
    cfg.claude.backend = "chatgpt"  # chosen: it then says what to do
    assert isinstance(make_brain(cfg, find_code=lambda path: None), ChatGPTBrain)


def test_the_settings_card_sees_no_secrets(tmp_path, monkeypatch):
    from abdoh.claude import setup

    cfg = Config(app_dir=tmp_path)
    cfg.claude.backend = "chatgpt"
    signed_in(tmp_path)
    shown = setup.claude_state(cfg, find=lambda p: None)
    assert shown["using"] == "chatgpt" and shown["connected"]
    assert shown["chatgpt"]["email"] == "you@example.com" and shown["chatgpt"]["plan_usage"]
    assert "access-1" not in json.dumps(shown) and "refresh-1" not in json.dumps(shown)
