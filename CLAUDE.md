# CLAUDE.md

Abdoh is a simple, voice-first personal assistant. `ABDOH_EPIC_3.md` is the current source of
truth: work through its stories in order. `ABDOH_EPIC.md` (v1) and `ABDOH_EPIC_2.md` are done;
their architecture still applies unless epic 3 changes it.

## Working rules

1. **One branch per story:** `story/<number>-<short-name>` (e.g. `story/04-commands-file`).
2. **Small commits** using Conventional Commits: `feat:`, `fix:`, `test:`, `docs:`, `chore:`, `refactor:`.
   Commit after each meaningful step, not one giant commit per story.
3. **Before every commit:** `ruff check . --fix && ruff format . && pytest -q`. Never commit with failing tests.
4. **When a story's acceptance criteria are met:** push the branch, merge into `main`
   (`git checkout main && git merge --no-ff story/... && git push origin main`), then start the next story.
   If a GitHub remote / `gh` CLI is available, open a PR and merge it instead.
5. **Never commit** `.env`, `config.yaml`, `commands.yaml` (user copies), or anything in `models/`.
6. **Hardware-dependent code** (mic, speakers, screen) must sit behind interfaces so tests use fakes.
   Unit tests must never need a microphone, speakers, network, or API key.
7. **Keep it simple.** No new dependencies beyond the epic's tech stack without a one-line
   justification in the commit message.
8. Update `README.md` at the end of each story if setup or usage changed.
9. If something is blocked (e.g. OS permission needed), finish everything else, write a `TODO(blocked):`
   note in the README "Known issues" section, and continue to the next story.

## Dev commands

```
python -m venv .venv && .venv\Scripts\activate   # Windows (source .venv/bin/activate elsewhere)
pip install -e .[dev]
ruff check . --fix && ruff format . && pytest -q
python -m abdoh --help
```
