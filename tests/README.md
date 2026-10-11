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
