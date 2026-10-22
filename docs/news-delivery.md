# News delivery rules

Read for `/gm` or other news work, not idea/TODO capture. Shared materiality,
runtime, credential, permission and truthfulness rules still apply.

- Morning news covers the 24 hours before the briefing job. The job's read runs
  `python scripts/goodmorning.py news --latest --as-of TIME --view sections` per
  confirmed country; stories the previous morning briefing showed are already
  removed. Label it with its as-of time; surface cache limitations only when
  material. Read `docs/news-pipeline.md` only for configuration or a failure.
- In chat, answer a news question for another window with a stateless read
  (`news --since DATE --until DATE` or `--latest`). Nothing is saved or acknowledged.
- Separate AI, world, and confirmed-country national news. An AI feed label,
  lawsuit or technology company alone is not an AI connection; omit
  unrelated/ambiguous candidates rather than inventing one. Code relevance signals
  are conservative keyword checks, not factual verification. Show material
  coverage gaps and non-publication date labels only where needed to avoid
  misleading the user. Present chosen stories with clear wording and source links;
  add helpful context without inventing facts or claiming the headlines are verified.
- If `news_additional_countries` is confirmed, read each country separately with
  explicit `--country` and label national sections. Show matching AI/world
  stories once. Do not let primary-country counts imply that additional countries
  were collected.
- Never loop on cooldowns, use `--refresh` automatically, or infer success from a
  heading. Zero stories means not collected, never "nothing happened".
- News importance is not recency, raw publisher counts or social engagement. Use
  the confirmed selection policy and inspect source/window counts and ranking
  reasons. Scores use headline/excerpt proxies and need editorial judgment: choose
  from the selected stories and wider candidates, overriding a low proxy score
  when warranted, but never fabricate citations or dates. Do not claim objective
  importance, independent verification or Twitter parity. A valid feed with no
  items in the window may have rolled over; a filled section does not prove that
  all major events were found. Prefer fewer meaningful items over quota filler.
  Label publisher opinion and first-party claims. Deduplicate events and give
  analysis/discovery its proper label rather than calling it breaking. A
  submission/update date is not a newly published article; do not re-date known
  older stories.
