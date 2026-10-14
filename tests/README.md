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
is an opt-in **paid** DeepSeek V4.1 Flash High trial. It uses real browser routes
and fresh native V2 model sessions with copied public source and a synthetic
returning account. Native CLI discovery handles authentication; the trial never
lists unrelated sessions or copies credentials. It checks capture, follow-ups,
Schedule, evening feedback and regeneration. This is a loopback workflow trial,
not validation of public registration, HTTPS, encrypted deployment or load.
