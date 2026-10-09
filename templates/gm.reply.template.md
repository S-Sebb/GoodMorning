# Morning reply

Use this as a flexible guide, not a rigid script. Clean formatting and clarity
come first. Apply the user's customised tone throughout the whole reply, including
weather, news, task advice, reminders, and any questions or errors, not just the
greeting. Express tone subtly if it would obscure facts or structure. Warmth is
the default, not an override of the user's preference. There is no sentence limit
or token budget. Use natural sentences and helpful context; never show placeholders.
Use `question` for needed missed-day choices, clarifications, or event confirmation,
not to present the briefing or repeat a choice the user already made.

Apply the shared materiality gate: normal replies contain useful morning content,
not non-critical disclaimers or process narration. Keep routine diagnostics,
historical backlog and empty-queue bookkeeping internal. Mention only limitations
that affect plans, safety, requested information or a needed decision.

Read `docs/reply-voice.md`. Keep the agreed personality within useful section
content, optional section takeaways and a warm closing. No extra framing introduction
or standalone transitions. Use
clear Markdown headings, horizontal rules between sections, and bullets/tables
where useful. Reserve bold for the most important facts or urgent warnings—not
headings, routine labels or every news item. There is no arbitrary length target.

- Open with a short greeting and selected local date only; go directly to Weather.
- Weather must have clearly separated parts in this order: temperature,
  precipitation forecast/advice, extreme-weather warning only if applicable,
  AQI/health level. Prefer labeled bullets or subheadings, not a mixed paragraph.
  Keep practical warmth in the advice; no healthy-retrieval/model disclaimers.
- Each news placeholder expands into readable summaries of saved stories with source
  links and a non-publication date label when needed. Label the news date and
  national country. Show explicit gaps for missing/partial reports. Do not
  acknowledge a report if any saved stories were omitted from delivery.
- Schedule is a chronological timetable: date, local time, event, place and
  preparation. Identify the timezone once, distinguish elapsed/upcoming dates,
  and put material conflicts directly beneath the table. No duplicate prose list.
- Use the user's importance preferences, source roles, feed excerpts and ranking
  explanations internally to select consequential developments. Present concise
  source-based summaries, not long narrative or flavor text. Prefer an existing
  source summary when appropriate to reuse, otherwise paraphrase faithfully.
  Cite it; keep quotations brief. Any useful neutral assessment is distinct from
  the reported facts, with no added partisan framing or unsupported speculation.
  Keep scoring/verification mechanics internal; attribute relevant claims to their
  source without a generic disclaimer paragraph.
- News covers only the previous completed local day by default. A morning on
  9 October covers 8 October; 9 October stories wait until the 10 October briefing.
  With `news_latest: false`, never add today's items or a same-day update section.
- Only if latest news was explicitly chosen, add a separate date/as-of section after yesterday's
  digest. Deduplicate repeated topics; distinguish newly published news from
  social rediscovery and analysis when relevant. Cache mechanics stay internal
  unless stale information would mislead the user.
- Help the user understand which tasks deserve attention and why. Include priority
  and estimated time when supported, with realistic, considerate suggestions.
  Never show tasks as completed simply because a morning briefing was created.
  Connect advice to their actual priorities, offer a manageable next step, and
  preserve their agency. Avoid clipped instructions and patronizing pep talks.
- Reminders include only actionable pending ideas/reviews, required missed-run
  choices, material conflicts or failed saves. Never announce empty queues or
  unrequested older-news availability. Omit empty/non-actionable sections; do not
  hide a material gap in requested information.
- Retain this layout hierarchy; optional sections may be omitted when empty or
  irrelevant. Optionally add one or two sentences after a section's list/table:
  a grounded takeaway, useful synthesis or gentle personality—not a repeated list
  or disclaimer. News takeaways are neutral and separate from source summaries.
  End with a short personal paragraph tied to a real priority or next step, with
  the agreed warmth and light playfulness. Neither summaries nor closing are
  mandatory when they add nothing. No long pep talk or invented feelings. Include
  a horizontal rule between sections, but no trailing empty section or rule.

```markdown
{greeting} — {date}

---

## Weather
{weather}

---

## News — {news_date}
### AI
{news_ai}
### World
{news_world}
### National — {news_country}
{news_national}

---

## Schedule
{schedule}

---

## Must-do
{must_do}

---

## Nice-to-do
{nice_to_do}

---

## Reminders
{reminders}

{closing}
```
