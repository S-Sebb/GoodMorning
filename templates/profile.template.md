# Secretary profile

<!-- Copy to secretary/profile.md only after setup answers and the format are
confirmed. Replace empty values with user-confirmed settings. Keep city,
region, and timezone as plain key: value lines for the existing scripts.
Quoted empty strings prevent an empty field from absorbing the next line. -->

secretary_name: ""
secretary_language: ""
city: ""
region: ""
timezone: ""
work_days: ""
work_hours: ""
sleep_time: ""
secretary_tone: ""
special_needs: ""
occupations: ""
expertise_fields: ""
industry: ""
project_scope: ""
knowledge_area: ""
news_preference: ""
news_country: ""
news_additional_countries: ""
news_latest: ""
news_sources_path: ""
calendar_source: ""

## Project roots

<!-- Add one user-confirmed project per line:
- Name | absolute folder path | local or remote | agreed read/write-back scope
Remote access requires a chosen connection method and authorization first.
Never put passwords or keys here. -->

## Setup rules

- Ask for `secretary_name` as the first initialization question, before any
  location, schedule, tone or news question. It is an optional short display
  name (1-30 characters, at least one letter or number, no control characters
  or newlines). Allow skipping; older profiles without this field stay valid.
  Save the exact confirmed spelling in `secretary_name` after storage consent
  and use it for self-reference, website header/author labels and briefing
  greetings where appropriate. A later `/secretary` rename updates only this
  line and keeps all other preferences unchanged.
- For local use, ask for `secretary_language` second, before location/schedule/
  tone/news. Save the explicit language/script or bilingual preference;
  “follow my message language” is a valid confirmed setting. For browser chats,
  skip this question: replies, questions and titles follow the website language
  switch and helpers pass `--website-language CODE` without writing the local
  field.
- Use that language for all five workflows, conversation titles, setup, questions and follow-ups. It is
  independent of news-source language, national-news country, timezone and tone.
  Older profiles without this field stay valid; do not invent or force a migration.
- Ask for a qualified city (city plus country/region) or verify coordinates.
  Set region to `global` or `mainland-china` after confirming the location.
- Confirm an IANA timezone, work days/hours, sleep time, tone, and special needs.
- Invite the user to share their current occupations/roles (including multiple
  roles) and expertise/fields. Explain that this helps choose relevant topics,
  examples, and explanation depth. Both fields are optional; allow skipping.
- Ask about industry, project scope, and knowledge area as needed, without
  repeating answers already given. Do not assume expertise from a title or ask
  for employer identity, credentials, or other unnecessary private details.
- Save only confirmed context. Existing profiles without occupations or
  expertise_fields remain valid; do not force reinitialization or invent values.
- Confirm the national news country independently of city and region. Save its
  ISO code in `news_country`; verify feeds before using it. Leave
  `news_sources_path` empty for bundled feeds, or use a user-local JSON path.
- For several confirmed countries, save the primary in `news_country` and the
  remaining ISO codes in `news_additional_countries`, comma-separated. Run each
  separately; do not silently omit a country whose feeds need configuration.
- Ask whether to add separately dated latest/current developments alongside
  yesterday's digest; set `news_latest: true` only if chosen. Optional skips and
  older profiles keep the existing completed-day workflow without reinitialization.
- Agree on custom-only, external imports, or Betterbird calendar access.
  Initialize SQLite; do not create `custom_schedule.md`. Imports need review.
- Keep credentials in the environment, never in this file.
