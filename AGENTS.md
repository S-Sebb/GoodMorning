# GoodMorning source

## Website wording and translation

Website wording must be clear and informative first, then comfortable and cute.
Keep actions, status, uncertainty and consequences easy to understand; charm must
not hide important information or override a user's saved tone.
Use DeepSeek V4.1 Flash Free with the High variant for translation tasks
(`opencode/deepseek-v4.1-flash-free`, variant `high`). Adapt wording freely rather
than translating literally: preserve the intended meaning and important facts,
while making the result natural and consistent with these website wording goals.

## Secretary and development contracts

For secretary/browser requests, read the required contracts and saved tone silently
before the first visible message. Brief factual progress messages are allowed;
every visible reply, update and question uses the website language and saved tone
(default warm/helpful). Do not expose instruction loading, formats or tone checks.
Use native questions for unresolved facts and wait. A workday is not a completion
date or evidence of enough time;
encouragement must not invent capacity, progress or future automatic action.

When writing agent prompts or instructions, follow `AGENT-PROMPT-GUIDE.md`.
Test new or modified agent prompts, plus directly affected neighbors, against all website-configured models and
their configured variants in `src/goodmorning/web/models.py`. Scope live trials to the changed set from the diff;
do not rerun full matrices for unchanged established prompts. Verify behavior and
tone with isolated synthetic cases before accepting the change. Report unavailable
models or unmet requirements; do not substitute models or treat code tests as
proof of model behavior.

For coding-agent requests to create a hosted server user, read
`SERVER-USER-GUIDE.md` first. Generate a random temporary password privately;
do not ask the owner to choose one. Complete isolated backend provisioning and
the readiness gate before reporting success. Never expose credentials.

For coding-agent requests to inspect, migrate, repair, restore or manually modify
hosted account data, read `SERVER-DATA-GUIDE.md` first. Inspection is read-only;
live writes require explicit account/file/operation scope, an encrypted rollback
backup, the correct service identity, and before/after validation. A deployment
or version bump never authorizes personal-data migration.

For website requests, this working directory is the selected release/package
root. Read workflows and run helpers here, not from another installed GoodMorning
copy. A globally loaded skill never changes the browser request's release or runtime.

For `/gm` or `/gn` browser-generation prompts, read `docs/core-rules.md` and
`docs/browser-generation.md`, then the matching workflow. Stable rules belong in
those files, not in dispatch prompts. The prompt supplies only an edition, browser
job ID, selected runtime and website language. Start with `scripts/goodmorning.py job --secretary-dir
RUNTIME --job JOB prepare`; it resolves the pinned date, paths, saved preparation
and actual browser feedback. Use the real session ID from the environment or an
explicit `--session`; never guess it.

New briefings are web-only native JSON. Publish one new section at a time using
the job helper; code owns the cumulative document, source validation and final
save. Read `docs/item-taxonomy.md`: new v2 publications never schedule tasks from
their presentation. Do not create text/card/presentation/HTML copies. Private records and
saved preferences must not be deleted or overwritten during source cleanup.

For website prompts marked `Browser chat`, read `docs/core-rules.md`,
`docs/browser-chat.md`, then the matching workflow. `/initialize` reviews all
existing preferences without resetting records. Chat supports only initialize,
secretary, todo and eureka; briefings remain on their own pages.
`Workflow refresh: true` means this existing conversation moved to the current
public release. Reread those files from the current working directory; they
replace earlier workflow rules, not saved user context or permissions. Follow
the user's current request across modes without requiring a manual switch.
Every browser request supplies `Website language: en` or `zh-CN`. Use that
language for replies, questions and titles, not the profile's local reply-language
preference. Website initialization never asks for a separate reply language.
Use `--website-language CODE` with setup/workflow helpers in browser chats.
An active request keeps its starting language; a later chat turn can choose
another website language. Preserve existing records and earlier replies.

For development, keep personal records, credentials and generated artifacts out
of this source tree. Public source is shared; each account's private runtime and
agent home must remain separate. Tests use isolated synthetic records. Do not
weaken authentication, encryption or account isolation to make a test pass.
