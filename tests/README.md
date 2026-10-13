# Focused validation

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
