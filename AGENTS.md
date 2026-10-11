# GoodMorning source

For `/gm` or `/gn` browser-generation prompts, read `docs/core-rules.md` and
`docs/browser-generation.md`, then the matching workflow. Stable rules belong in
those files, not in dispatch prompts. The prompt supplies only an edition, browser
job ID and selected runtime. Start with `scripts/goodmorning.py job --secretary-dir
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

For development, keep personal records, credentials and generated artifacts out
of this source tree. Public source is shared; each account's private runtime and
agent home must remain separate. Tests use isolated synthetic records. Do not
weaken authentication, encryption or account isolation to make a test pass.
