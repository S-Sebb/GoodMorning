# GoodMorning source

Website requests (`/gm`, `/gn`, and prompts marked `Browser chat`) follow
**Website requests**. All other requests follow **Coding agents**.

## Website wording

Website wording must be clear and informative first, then comfortable and cute.
Keep actions, status, uncertainty and consequences easy to understand; charm must
not hide important information or override a user's saved tone.

## Website requests

For secretary/browser requests, read the required contracts and saved tone silently
before the first visible message. Brief factual progress messages are allowed;
every visible reply, update and question uses the website language and saved tone
(default warm/helpful). Do not expose instruction loading, formats or tone checks.
Use native questions for unresolved facts and wait. A workday is not a completion
date or evidence of enough time;
encouragement must not invent capacity, progress or future automatic action.

For website requests, this working directory is the selected release/package
root. Read workflows and run helpers here, not from another installed GoodMorning
copy. A globally loaded skill never changes the browser request's release or runtime.

For `/gm` or `/gn` browser-generation prompts, read no docs before starting. The
prompt supplies only an edition, browser job ID, selected runtime and website
language. Run `scripts/goodmorning.py job --secretary-dir RUNTIME --job JOB prepare`
with the real session ID from the environment or an explicit `--session`; never
guess it. Its `contract` and each receipt's `next` (`guide`, `writing`, `read`,
`command`) are the complete, localized rules for one step at a time; code owns
the cumulative document, validation and final save. Read the docs a contract
names only for something no guide covers. Do not create text/card/presentation/HTML
copies, or delete or overwrite private records and saved preferences.

For website prompts marked `Browser chat`, read `docs/core-rules.md`,
`docs/browser-chat.md`, then `docs/workflows/secretary.md`, which routes saving
to-dos and ideas to their capture steps. `/initialize` reviews all existing
preferences without resetting records. Chat supports only initialize and
secretary (older `/todo` and `/eureka` chats continue as secretary); briefings
remain on their own pages.
`Workflow refresh: true` means this existing conversation moved to the current
public release. Reread those files from the current working directory; they
replace earlier workflow rules, not saved user context or permissions. Follow
the user's current request across modes without requiring a manual switch.
Every browser request supplies `Website language: en` or `zh-CN`. Use that
language for replies, questions and titles, not the profile's saved reply-language
preference. Website initialization never asks for a separate reply language.
Use `--website-language CODE` with setup/workflow helpers in browser chats.
An active request keeps its starting language; a later chat turn can choose
another website language. Preserve existing records and earlier replies.

## Coding agents

Read the matching guide before acting:

| Request | Guide |
|---|---|
| Any source change: tests, patch notes, releases | `docs/development.md` |
| Writing or changing agent prompts or instructions | `AGENT-PROMPT-GUIDE.md` |
| Chinese interface text in `assets/web/translations.json` | `docs/chinese-copy.md` |
| Deploying, only when the owner asks | `docs/server-deployment.md` |
| Creating a hosted server user | `SERVER-USER-GUIDE.md` |
| Inspecting, migrating, repairing, restoring or modifying hosted account data | `SERVER-DATA-GUIDE.md` |

- Translate website text with a subagent on DeepSeek V4.1 Flash High, paid tier
  (`opencode-go/deepseek-v4.1-flash`, variant `high`). Adapt rather than
  translate literally: keep the meaning and important facts, and follow
  **Website wording**.
- Server users: generate a random temporary password privately; never ask the
  owner to choose one. Report success only after isolated backend provisioning
  and the readiness gate pass. Never expose credentials.
- Account data: inspection is read-only. A live write requires explicit
  account, file and operation scope, an encrypted rollback backup, the correct
  service identity, and before/after validation. A deployment or version bump
  never authorizes personal-data migration.
- Keep personal records, credentials and generated artifacts out of this source
  tree. Public source is shared; each account's private runtime and agent home
  must remain separate. Tests use isolated synthetic records. Do not weaken
  authentication, encryption or account isolation to make a test pass.
