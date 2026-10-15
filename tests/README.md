# Focused validation

`python tests/browser/chat_history.py /ABS/PRIVATE/PATH` checks tab-scoped secretary
restoration, the 15-minute idle-only absence reset, Resume, draft navigation warnings,
login namespace changes, outages, stale references and independent tabs. It also
checks readable always-open history at desktop/tablet/phone widths and writes
full-page previews of the selected Inset design outside the checkout.
`chat_mobile_viewport.py` checks composer access and reading/draft preservation
with simulated keyboards. These checks make no paid model calls.
`python tests/browser/scroll_rails.py /ABS/PRIVATE/PATH` checks simple, label-free
phone scrollbars on all four tabs, independent page/message dragging, keyboard
control, localization and draft preservation.

Run `python -m unittest discover -s tests -p 'test_*.py' -q` and
`node --test tests/test_projects.mjs` before a release. These checks use isolated
synthetic records. Keep distinct behavior, failure recovery, data preservation,
authentication, encryption, consent and account-isolation coverage.

Do not add tests that merely require exact instruction wording or repeat a
fixture's facts across several files. Discovery checks verify metadata and
referenced files; workflow behavior is tested through the actual helpers.
Boundary tests need enough records to cross the boundary, not thousands of
repeated records. Optional benchmarks live in `benchmarks/`; browser checks in
`browser/` are opt-in. Historical comparison experiments are not release gates.

The streaming, generation, chat and public login browser checks cover different
delivery boundaries. Public security checks require explicit deployment access
and create only synthetic accounts. Browser emulation does not prove physical
phone compatibility, real-model behavior, load capacity or backup restoration.

Canonical taxonomy coverage is in `test_task_taxonomy.py`: atomic capture,
deadline/workday separation, action identity, occurrence completion, TBC drafts,
import review, conversion recovery, source validation and explicit migration.
`python tests/browser/taxonomy.py` checks the v2 renderer in Chromium at desktop
and phone widths in English/Chinese. Optional `--screenshots /ABS/PRIVATE/PATH`
keeps synthetic visual evidence outside the checkout. These mocks test rendering,
not live-account authentication or model intent extraction.

`python tests/browser/chat_actions.py /ABS/PRIVATE/PATH` checks secretary question,
answer, permission and confirmed-change styling across all four palettes, English
and Chinese, desktop and phone widths. It measures text contrast, preserves pending
drafts, checks literal unsafe text and verifies one-shot/reduced-motion animation.
`test_chat_actions.py` covers committed receipts, retry deduplication, session
isolation, bounded/read-only projections, turn order and queue-read separation.
`python tests/browser/chat_action_ownership.py /ABS/PRIVATE/PATH` exercises the
real chat API and renderer with synthetic native-session, browser-conversation
and browser-turn receipts in all four modes, without mocked chat responses or
model calls. Unit regressions also reject ambiguous IDs shared by conversations.

`python tests/browser/schedule.py --canonical` checks the real Schedule tab with
v2 tasks, reported statuses and TBC appointments, including refresh/navigation,
Chinese, mobile layouts, source failures and no-JavaScript operation.

`python tests/benchmarks/website_live.py --output /tmp/opencode/NEW_PRIVATE_TRIAL`
is an opt-in **paid** English Muse Spark Contributor XHigh trial. It uses real browser routes
and fresh native V2 model sessions with copied public source and a synthetic
returning account. Native CLI discovery handles authentication; the trial never
lists unrelated sessions or copies credentials. It checks capture, follow-ups,
Schedule, evening feedback and regeneration. This is a loopback workflow trial,
not validation of public registration, HTTPS, encrypted deployment or load.

English browser requests route automatically to Muse Spark Contributor XHigh; session metadata
verifies the actual model/variant. `--blocked-report` checks reported blockers,
and `--ambiguity` checks that a native recurrence question precedes any record write.
Pending synthetic questions and transcripts remain available for inspection.
For this trial's preserved three-check TBC interruption, `--resume` continues the
existing secretary conversation without replaying passed captures and retains
`results-original.json`. It is not a general replay/recovery command.

`python tests/benchmarks/task_tone_live.py --output /tmp/opencode/NEW_MATRIX` runs
an opt-in **paid** Muse Spark Contributor XHigh matrix: English/Chinese, default
warm/helpful, formal and playful tones, twice each. It checks capture, follow-ups,
clarification through final save, duplicate request identities and refused-write
replies. The first default-tone case in each language also tests adoption,
rescheduling, recurrence edits, selective completion and injected conflict/lost-ack
recovery. Faults affect only the copied synthetic CLI. Two workers use separate
runtimes/sessions; this is not an encrypted-account or load-capacity test.
`--resume` skips completed cases and observes preserved in-flight requests without
resending them. Tone remains pending until actual replies/questions/errors receive
manual semantic review; keywords, emojis and passing data assertions do not prove it.
Use `--model deepseek-flash` to run the same matrix with DeepSeek V4.1 Flash Free High.
Use `--language en` or `--language zh-CN` to test a proposed language/model pairing
without changing production routing or the model selector. The default still
tests both languages. Resuming must retain the original language/model/scope.
`--strict-chat` checks that record operations have a reply, permits factual progress,
requires interval-only clarification, omits the start date from the answer,
and tests a clear recurrence with no supplied start. Extra date questions are flagged
even if the harness supplies a date to continue other coverage. These structural
checks still require manual language/tone/grounding review; they are not style scores.
The user has accepted the current visible progress style; no progress filtering is
implemented. Old quiet-only experiment results remain unchanged, and cannot be
resumed under the changed acceptance policy or silently relabeled as passes.
`--system-file PATH` is an experimental comparison: it overrides only the builtin
build agent's base prompt in the copied trial location, never global configuration
or permissions. Native inspection verifies the exact base prompt before model work;
session metadata must retain the build agent and selected model/variant. Resume
requires the same prompt hash. Do not treat this experiment as website deployment.
`--tone-only` runs a fresh six-setting follow-up after a prompt fix. Scope live validation to
new/modified prompts plus directly affected neighbors, determined from the diff, on every entry/variant in
`src/goodmorning/web/models.py`, with both behavior and tone reviewed; a missing
model or unmet requirement is incomplete validation, not permission to skip it. Use
`--model`/`--language` filters and `--tone-only` for tone-only fixes. Do not rerun full
matrices for unchanged established prompts; run them for shared prompt infrastructure or release validation.
Each task/tone matrix holds an exclusive process lock for its output directory.
After a server restart, do not assume the original runner stopped: a refused
`--resume` means it still owns the matrix. Never delete the lock to bypass it.

`python tests/benchmarks/briefing_tone_live.py --output /tmp/opencode/NEW_BRIEFING_TRIAL
--language en` runs opt-in **paid** morning/evening prompt checks through native
model sessions and real browser job/controller helpers. Run a separate new output
with `--language zh-CN` for the configured Chinese model/variant. Cases cover empty
optional positions, opted-in latest news, deliberately unavailable providers,
resuming an existing published section, exact evening completion/blocker feedback,
presentation-only regeneration and ambiguous report attribution. Provider faults
and the interrupted checkpoint are synthetic; no live providers or real accounts
are used. Command inputs, native model metadata, replies and documents are retained
for manual language/tone/grounding review. Passing assertions alone is not prompt
acceptance. Output directories are exclusively locked; this runner never replays
an existing directory or auto-answers model questions/permissions. Interrupted
work must be inspected before any continuation. These tests do not prove public
HTTPS security, encrypted isolation, real provider coverage or statistical reliability.
Each case has its own copied source and native build-agent directory policy. A
read-only native preflight verifies access to the assigned synthetic runtime and
denial of parent test artifacts/original checkout before model work. These are
permission checks, not an OS sandbox. Verified save receipts supply relative page
links; the handoff check rejects guessed hosts or another date. Initial task reads
needed to reconcile actual evening feedback are reviewed separately from collecting
later sections; regeneration has no such mutation/reconciliation allowance.
`--browser-job` section reads are owner/date/position checked; active canonical
browser actors are bound even if a model omits the flag. Rejected reads are
recorded separately from views actually returned. Helper exit codes distinguish
failed publication from a successful advance; unknown outcomes block acceptance.

`python tests/browser/briefing_model_output.py --trial /tmp/opencode/PRESERVED_MATRIX
--output /tmp/opencode/NEW_VISUAL_REVIEW` renders completed native documents and
captured pending questions in Chromium at desktop/mobile sizes. It copies synthetic
runtime data, makes no model calls and does not alter original evidence. This
checks real page rendering, not real providers or public-account security. Native
job conversation preambles are not served on briefing pages; review published
content/questions separately from preserved native-trace instruction diagnostics.
