# Development and releases

Project-specific rules for coding agents. The general worktree, branch and pull
request (PR) workflow comes from the user's global agent instructions. Here:
default branch `main`, CI workflow `Validate`, squash merges only.

## Python

uv manages Python everywhere. `.python-version` pins 3.14; install it with
`uv python install 3.14`. Run Python through
`uv run --no-project --with-requirements requirements/browser.txt python ...`,
never a system interpreter. The live server's setup is in
`docs/server-deployment.md`.

## Tests

Run from the task worktree after the final rebase. Local runs use `/tmp/opencode`
as the fixture root when it exists; set `GM_TEST_TMPDIR` to use another.

1. Every PR:
   - focused tests for the changed behavior, added or updated in the same PR;
   - `uv run --no-project --with-requirements requirements/browser.txt python -m unittest discover -s tests -p 'test_*.py' -q`;
   - `node --test tests/test_projects.mjs`.
2. Browser-visible changes: also run the `tests/browser/*.py` suites for the
   changed pages, listed in `tests/README.md`, with private artifact
   directories outside the checkout.
3. Prompts that website agents read: also run the live model trials required by
   `AGENT-PROMPT-GUIDE.md`.
4. Changes to `assets/web/patch-notes.json`: also run the validation under
   [Patch notes](#patch-notes).

5. Changes under `android/`: also run `./gradlew test assembleRelease` and an
   emulator check, as described in `docs/android-app.md`.

Put the exact commands and results in the PR's Validation section. CI repeats
step 1 on every PR; it does not replace steps 2–5.

## Releases

Website releases are below. Android APKs are released separately, only when the
owner asks; see `docs/android-app.md`.

One deployment is one release: one version and one patch note covering
everything merged into `main` since the previous deployment. Feature PRs never
edit `assets/web/patch-notes.json` or the version.

`deploy/release.py` tags every deployment `deploy/<RELEASE-NAME>` on the deployed
commit. The release contents are
`git log --oneline <latest deploy/ tag>..origin/main`.

When the owner asks to deploy:

1. Deploy what is merged on `origin/main`. Do not merge open PRs unless the
   owner names them; list them in your report. If the range is empty, stop:
   there is nothing to deploy.
2. If the owner asked for a silent update, skip to step 5: no patch note, and
   the version stays the same.
3. Create the release worktree `release-<version>` and write the patch note
   (below) covering every user-visible change in the range. Read each merged
   PR's description.
4. Open the PR `Release <version>`. The deploy request authorizes merging this
   PR once CI passes, and only this PR.
5. In the primary checkout, run `git pull --ff-only`, then
   `uv run --no-project python deploy/release.py` (see `docs/server-deployment.md`),
   and report its summary.

The release closes when its PR merges. Anything merged later belongs to the
next release. Never edit the note of a version that went live. If a deployment
fails before going live, fix the note for that version through a new PR.

## Patch notes

Website users read them in the in-app Patch notes panel. Write for them, not for
developers, following the website wording rules in `AGENTS.md`.

Prepend one entry to `assets/web/patch-notes.json` and keep older entries
unchanged:

```json
{"version": "0.46.0", "date": "2026-10-16", "author": "GoodMorning agent",
 "title_en": "Schedule summaries", "title_zh": "日程小结",
 "changes": [
  {"category": "Added",
   "en": ["Schedule sections now start with a short summary of your day."],
   "zh": ["日程章节开头会先帮你小结一下这一天。"]},
  {"category": "Fixed",
   "en": ["The maintenance page shows its normal styling again."],
   "zh": ["维护页面又能正常显示样式啦。"]}]}
```

- **version**: `0.minor.patch` from the latest note. Increase minor and reset
  patch to 0 when the release adds, changes or removes something users can see.
  Otherwise increase patch. Never reuse a version.
- **date**: the deployment date (`YYYY-MM-DD`). **author**: `GoodMorning agent`.
- **title**: the main change in a few words; at most one emoji.
- **categories**, in this order, omitting empty ones: `Added`, `Changed`,
  `Fixed`, `Removed`, `Security`, `Notes`. Use `Notes` only for an apology or for
  something users must do. Do not use `Documentation` or `Tests`; older entries
  keep them.
- **bullets**: one per user-visible change, one sentence, about 25 words at
  most. Say what the user sees now, in the present tense ("Evening Tasks now…").
  Leave out internal work (tests, CI, agent instructions, refactors, deployment
  steps). If nothing in the release is user-visible, ask the owner whether to
  ship it silently. Never name files, functions, model IDs or internal terms such
  as preflight, packing, queue receipts or reservations.
- **zh**: one bullet for each English bullet, in the same order. Adapt, do not
  translate literally: follow the translation rule in `AGENTS.md` and
  `docs/chinese-copy.md`. Plain text only, no HTML or Markdown. Each title and
  each language's complete note fits within 2000 characters.

Validate before opening the release PR:

```sh
uv run --no-project --with-requirements requirements/browser.txt python -c "import sys;sys.path.insert(0,'src');from goodmorning.web.release import patch_notes;notes=patch_notes();assert notes;print(notes[0]['version'])"
uv run --no-project --with-requirements requirements/browser.txt python -m unittest discover -s tests -p test_release.py -q
```

An invalid file shows users no notes at all, so both checks must pass.
