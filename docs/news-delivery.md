# News delivery rules

Read for `/gm` or other news work, not idea/TODO capture. Shared materiality,
runtime, credential, permission and truthfulness rules still apply.

- Use `python scripts/goodmorning.py news --backfill`, read its manifest, then `--show DATE` only for reports
  needed now. Use candidate pages only for pending review and selected-story views
  after review; do not reprint candidate/diagnostic history. Prioritize yesterday; retain other collected dates internally
  without dumping seven days of headlines. `--status`/`--show` never fetch. Read
  `docs/news-pipeline.md` only for a historical window, configuration, or failure.
- Separate AI, world, and confirmed-country national news. An AI feed label,
  lawsuit or technology company alone is not an AI
  connection. Explain the actual AI connection from collected evidence in review
  reasons; omit unrelated/ambiguous candidates rather than inventing one. Code
  relevance signals are conservative keyword checks, not factual verification.
  Preserve retrieval notes internally; show material coverage gaps and non-publication date labels
  only where needed to avoid misleading the user. For a report you will acknowledge,
  present all its saved stories, with clear wording and source links. Add helpful
  context without inventing facts or claiming the headlines are verified. A partial
  selection or draft remains unacknowledged; do not silently call it delivered.
- If `news_additional_countries` is confirmed, collect/show each country separately
  with explicit `--country`; pass that same country on backfill/show/ack. Label
  national sections and acknowledge each exact namespace/report only after delivery.
  Show matching AI/world stories once; include any differing stories before
  acknowledging a report so every saved story is represented. Do not let
  primary-country counts imply that additional countries were collected.
- After the report has actually appeared in a user-visible message, run
  `python scripts/goodmorning.py news --ack DATE --expect REPORT_ID --session NAME`. If this interface cannot
  run tools after the final reply, leave it collected and acknowledge only on a
  later turn when prior delivery is verifiable. Never acknowledge before sending
  a report simply to avoid a second turn. Snapshot saving does not acknowledge it.
- Missing/partial reports remain unresolved. Useful partial stories may be shown
  with their gaps, but cannot be acknowledged. Never loop on cooldowns/exhausted
  attempts, use `--refresh` automatically, or infer success from a Markdown heading.
- News importance is not recency, raw publisher counts or social engagement. Use
  the confirmed selection policy and inspect source/window counts and ranking
  reasons. Scores use headline/excerpt proxies and require editorial judgment;
  do not claim objective importance, independent verification or Twitter parity.
  A valid feed with no items in the selected window may have rolled over; a filled
  section does not prove that all major events were found. Prefer fewer meaningful
  items over quota filler. Label publisher opinion and first-party claims.
- With editorial review enabled, scores only prepare candidates. Review the needed
  date's pool and commit candidate IDs with explicit importance reasons using the
  current report/batch ID. A low proxy score can be overridden with judgment, but
  citations/dates cannot be fabricated. Pending review is not ready for delivery;
  do not acknowledge it or silently replace a delivered report. Deduplicate events
  and give analysis/discovery its proper label rather than calling it breaking.
- Morning news covers the 24 hours before the briefing job, read with
  `python scripts/goodmorning.py news --latest --as-of TIME`; stories the previous
  morning briefing showed are removed. Label it with its as-of time; surface cache
  limitations only when material. Latest has no delivery ledger and must not be
  acknowledged as a historical report. A submission/update date is not a newly
  published article; do not re-date known older stories or mistake every current
  item for breaking news.
