# GoodMorning source

For `/gm` or `/gn` browser-generation prompts, read `docs/core-rules.md` and
`docs/browser-generation.md`, then the matching workflow. Stable rules belong in
those files, not in dispatch prompts. The prompt supplies only an edition, browser
job ID, selected runtime and website language. Start with `scripts/goodmorning.py job --secretary-dir
RUNTIME --job JOB prepare`; it resolves the pinned date, paths, saved preparation
and actual browser feedback. Use the real session ID from the environment or an
explicit `--session`; never guess it.

New briefings are web-only native JSON. Publish one new section at a time using
the job helper; code owns the cumulative document, checklist synchronization and
final save. Do not create text/card/presentation/HTML copies. Private records and
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
