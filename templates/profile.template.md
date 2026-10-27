# Secretary profile

<!-- Copy to secretary/profile.md only after setup answers and the format are
confirmed. Replace empty values with user-confirmed settings. Keep city,
region, and timezone as plain key: value lines for the existing scripts.
Quoted empty strings prevent an empty field from absorbing the next line. -->

secretary_name: ""
user_name: ""
birthday: ""
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
news_country: ""
news_additional_countries: ""
holiday_countries: ""
news_sources_path: ""
calendar_source: ""
anime_updates: ""
anime_source: ""
anime_account: ""
anime_titles: ""
game_sales: ""
game_country: ""
game_account: ""
game_threshold: ""
game_titles: ""
stock_report: ""
stock_holdings: ""
weekly_letter: ""

## Project roots

<!-- Add one user-confirmed project per line:
- Name | absolute folder path | local or remote | agreed read/write-back scope
Remote access requires a chosen connection method and authorization first.
Never put passwords or keys here. -->

## Setup rules

Website Initialize chats ask only their code-led steps (`docs/initialization.md`);
these rules guide preference changes in Secretary chats and setup elsewhere.

- Ask for `secretary_name` as the first initialization question, before any
  location, schedule, tone or news question. It is an optional short display
  name (1-30 characters, at least one letter or number, no control characters
  or newlines). Allow skipping; older profiles without this field stay valid.
  Save the exact confirmed spelling in `secretary_name` after storage consent
  for assistant self-reference and website labels, not the user's name.
  A later `/secretary` rename updates only this
  line and keeps all other preferences unchanged.
- Ask second, alone, what the secretary should call the user. Same optional
  rules; any name or form of address. Save the exact spelling in `user_name`
  after storage consent; when empty, greet the user unnamed.
- Ask third, alone and skippable, for the user's birthday so the briefing can
  celebrate it. Save only month and day as `birthday: "MM-DD"` (“13 February”
  is `"02-13"`); never store a year or age, even when given. Older profiles
  without this field stay valid; never infer it from calendar occasions.
- Never ask for `secretary_language`: replies, questions and titles follow the
  website language switch and helpers pass `--website-language CODE` without
  writing this field.
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
- Ask, alone, which public holidays to show, independently of city and news
  countries; `holiday_countries` follows `docs/workflows/secretary.md`.
- Agree on custom-only events or a published calendar link (`.ics`).
  Initialize SQLite; do not create `custom_schedule.md`. Imports apply directly.
- Do not ask about anime during setup. The `anime_*` lines are set only when the
  user asks for new-episode updates (`docs/workflows/secretary.md`). Likewise the
  `game_*` lines, only when the user asks for game-sale updates.
- Offer the night briefing's stock gain/loss once during setup (optional);
  the `stock_*` lines follow `docs/workflows/secretary.md`.
- Keep credentials in the environment, never in this file.
