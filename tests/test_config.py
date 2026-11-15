import logging

from abdoh.config import Config, load_config, setup_logging


def test_defaults_without_any_files(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = load_config(tmp_path)
    assert cfg.wake_words == ["abdoh", "hey abdoh", "ya abdoh"]
    assert cfg.match_threshold == 85
    assert cfg.allow_run is False
    assert cfg.claude.max_tokens == 4000
    assert cfg.claude.backend == "auto"
    assert cfg.app_dir == tmp_path


def test_missing_config_is_copied_from_example(app_dir):
    assert not (app_dir / "config.yaml").exists()
    cfg = load_config(app_dir)
    assert (app_dir / "config.yaml").exists()
    assert (app_dir / "commands.yaml").exists()
    assert cfg.whisper_model == "small"
    assert cfg.claude.translate_target == "English"


def test_user_values_override_defaults(app_dir):
    (app_dir / "config.yaml").write_text(
        "match_threshold: 70\nallow_run: true\nclaude:\n  model: my-model\nbogus: 1\n"
    )
    cfg = load_config(app_dir)
    assert cfg.match_threshold == 70
    assert cfg.allow_run is True
    assert cfg.claude.model == "my-model"
    assert cfg.claude.max_tokens == 4000  # default kept


def test_no_api_key(app_dir):
    assert load_config(app_dir).has_api_key is False


def test_empty_api_key_counts_as_none(app_dir):
    (app_dir / ".env").write_text("ANTHROPIC_API_KEY=\n")
    assert load_config(app_dir).has_api_key is False


def test_api_key_from_env_file(app_dir):
    (app_dir / ".env").write_text("ANTHROPIC_API_KEY=sk-test\n")
    cfg = load_config(app_dir)
    assert cfg.has_api_key is True
    assert cfg.anthropic_api_key == "sk-test"


def test_api_key_from_environment(app_dir, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env")
    assert load_config(app_dir).has_api_key is True


def test_resolve_relative_to_app_dir(tmp_path):
    cfg = Config(app_dir=tmp_path)
    assert cfg.resolve("models/x") == tmp_path / "models" / "x"


def test_setup_logging_writes_file(tmp_path):
    cfg = Config(app_dir=tmp_path, log_file="logs/abdoh.log")
    setup_logging(cfg, console=False)
    logging.getLogger("abdoh.test").info("hello log")
    for h in logging.getLogger().handlers:
        h.flush()
    assert "hello log" in (tmp_path / "logs" / "abdoh.log").read_text(encoding="utf-8")
    for h in list(logging.getLogger().handlers):
        h.close()
        logging.getLogger().removeHandler(h)


def test_unknown_claude_backend_falls_back_to_auto(app_dir):
    (app_dir / "config.yaml").write_text("claude:\n  backend: telepathy\n")
    assert load_config(app_dir).claude.backend == "auto"
