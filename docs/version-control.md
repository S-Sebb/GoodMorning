# Version control

Rules for coding agents changing this repository. The owner is the only reviewer.

## Terms

- **Primary checkout**: the repository folder itself (`git worktree list`, first
  line). It always has `main` checked out.
- **Worktree**: a second checkout made with `git worktree add`. OpenChamber's
  "New worktree" and OpenCode's `worktree_create` both make ordinary local git
  worktrees under `~/.local/share/opencode/worktree/<project>/<name>`. Git
  tracks them in the primary checkout's `.git`; GitHub never sees them.
- **GitHub** sees only pushed branches and pull requests (PRs). There is no
  GitHub worktree feature.

## Rules

- `main` is the only long-lived branch and is what gets deployed. It changes
  only by merging a PR. Never commit on `main`, merge into `main` locally, or push
  to `main`.
- Never edit source in the primary checkout. Use it to read, deploy, and do server
  or account work. Update it only with `git pull --ff-only`. If a task already
  edited files there, move the session to a new worktree with OpenChamber
  `session.moveToWorktree` before committing; the changes move with it.
- One task means one session, one worktree, one branch and one PR. Name the
  worktree `<task>` and the branch `openchamber/<task>`. Never reuse a worktree or
  branch for another task, and never switch branches inside a worktree.
- One PR holds one change. Put unrelated fixes or cleanup in their own task.
- Settle product decisions with the owner in the session before coding: new or
  removed UI, changed defaults, wording, ordering. Do not make them inside a PR.
- Feature PRs never edit `assets/web/patch-notes.json` or the version. Patch
  notes belong to the deploy (see `docs/server-deployment.md`).
- Never commit `.env`, credentials, private records, `.openchamber/`
  screenshots or generated artifacts. A new worktree contains no ignored files
  (`.env`, `dist/`, caches); do not copy secrets into it.

## Allowed without asking

Creating your own worktree and branch; committing; rebasing your own branch;
pushing it (use `--force-with-lease` after a rebase); opening and updating its PR.

## Owner's explicit request required

Merging a PR; deploying; deleting a worktree or branch you did not create, or one
with unmerged commits or uncommitted changes; force-pushing any branch other than
your own task branch; rewriting `main` history; changing GitHub settings.

## Steps

1. **Start.** Use OpenChamber's New worktree, or `session.moveToWorktree` for
   the current session; both create branch `openchamber/<task>` from `main`.
   OpenCode `worktree_create` instead leaves a detached HEAD: run
   `git switch -c openchamber/<task>` in it before editing. Confirm with
   `git status -sb` that you are on your task branch, based on current
   `origin/main`.
2. **Work.** Commit small, focused commits on the task branch.
3. **Sync.** `git fetch origin && git rebase origin/main`. Never merge `main`
   into the task branch. On conflicts, keep both sides' intent; if that is
   unclear, stop and ask the owner.
4. **Test** after the final rebase, in the worktree:
   - focused tests for the changed behavior;
   - `python -m unittest discover -s tests -p 'test_*.py' -q`;
   - `node --test tests/test_projects.mjs`;
   - affected `tests/browser/*.py` suites and prompt trials required by
     `AGENTS.md`.

   Do not open a PR with failing tests. If a failure is unrelated and also fails
   on `origin/main`, report it in the PR instead of fixing it there.
5. **Open the PR.** Push the branch with `git push -u origin openchamber/<task>`,
   then run `gh pr create --base main`. The body has three parts:
   - **What and why**: user-visible before and after, in plain words.
   - **Validation**: exact commands and results, plus what was not verified.
   - **Risks**: data, security, rollback; write "None" with a reason.

   Link the PR to the session, then report the PR URL to the owner and stop.
6. **Review.** The owner reviews the PR. Make requested changes on the same
   branch and push; do not open a new PR.
7. **Merge**, only when the owner asks for that PR. CI (`Validate`) must be
   green, and the branch must be rebased on current `origin/main`; if `main`
   moved, repeat steps 3–4 and push. Then run `gh pr merge <N> --squash`.
   GitHub deletes the remote branch.
8. **Clean up** right after merging or abandoning:
   1. Remove the worktree (OpenChamber, or `git worktree remove <path>`).
   2. Run `git worktree prune`.
   3. Delete the local branch with `git branch -D openchamber/<task>`. Use `-D`,
      because `-d` does not recognize squash merges. Check first with
      `gh pr view <N>` that the PR merged.
   4. In the primary checkout, run `git pull --ff-only`.

   OpenChamber/OpenCode worktree removal deletes the folder only; it keeps the
   branch.

## Done means

The PR is merged and CI is green; the worktree, local branch and remote branch
are gone; and the primary checkout's `main` equals `origin/main`. When stopping
before that, report which of these are still pending.
