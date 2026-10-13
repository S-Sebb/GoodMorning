<p align="center">
  <img src="assets/web/icons/gm.svg" width="64" alt="GoodMorning sun" />
</p>

<h1 align="center">GoodMorning</h1>

<p align="center">
  <strong>A calmer start. A clearer finish. A little space to think.</strong><br />
  Your personal AI secretary for the plans, stories, and ideas that make up your day.
</p>

<p align="center">
  <strong>English</strong> · <a href="README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <a href="#a-day-with-goodmorning">Explore</a> ·
  <a href="#inside-the-briefings">Screenshots</a> ·
  <a href="#make-it-yours">Get started</a> ·
  <a href="docs/deployment.md">Documentation</a> ·
  <a href="https://github.com/S-Sebb/GoodMorning/issues">Feedback</a>
</p>

![Morning briefing with a personal desk, daily archive, and weather cards](assets/readme/morning.png)

GoodMorning turns scattered daily information into a quiet, readable place to begin.
Check the weather, catch up on news with sources, see what is on your calendar, and
give the important work some space. In the evening, reflect on what actually happened
and look ahead—without pretending unfinished work is done.

Between briefings, your secretary is there to help you think, remember a to-do, or
catch an idea before it disappears. Built around **OpenCode and OpenChamber**, it
combines an agent-assisted workflow with a browser interface you can host yourself.

## A day with GoodMorning

**Morning · Find your bearings.** Local weather and air quality, a source-linked
news digest, appointments and important day commitments, followed by necessary
and optional steps for ongoing projects without repeated tasks. Sections appear
as they are prepared, so you can start reading
before the whole briefing is ready.

**Evening · Put the day down.** Review the progress you report, keep unfinished
work visible, and see tomorrow's schedule. Completion comes from you, not an AI guess.

**Schedule · See the shape of your week.** Reviewed appointments and dated work
share a clear Monday–Sunday view, with today highlighted and three weeks of
navigation on either side. Saved changes refresh without another AI briefing;
[content and update rules](docs/weekly-schedule.md) keep the boundaries explicit.

**Secretary · Keep a little space to think.** Talk through your plans, save to-dos
in your own words, capture ideas with Eureka, and revisit your preferences without
resetting your records. Conversations support file attachments, pasted images with
click-to-enlarge previews, and saved history.

<table>
  <tr>
    <td width="50%" valign="top"><img src="assets/readme/evening.png" alt="Evening briefing in the night palette, showing completed and partial progress" /></td>
    <td width="50%" valign="top"><img src="assets/readme/secretary.png" alt="Secretary conversation with Aria, planning focused work in a personal desk interface" /></td>
  </tr>
  <tr>
    <td align="center"><em>A clear ending to the day.</em></td>
    <td align="center"><em>A place for plans and bright ideas.</em></td>
  </tr>
</table>

<sub>Real interface, fictional demo data. The weather, plans, and conversation above are examples, not personal records or live reports.</sub>

## Inside the briefings

From the forecast to your next focused block, everything has its own place.
These close-ups use fictional data; click a screenshot to see it at full size.

![Weather detail showing temperature, rain probability, air quality, and practical advice](assets/readme/weather.png)

<table>
  <tr>
    <td width="50%" valign="top"><a href="assets/readme/news.png"><img src="assets/readme/news.png" alt="Source-linked news cards grouped into AI and research, world, and United Kingdom stories" /></a></td>
    <td width="50%" valign="top"><a href="assets/readme/schedule.png"><img src="assets/readme/schedule.png" alt="Daily agenda with appointment times, locations, preparation notes, and flexible untimed work" /></a></td>
  </tr>
  <tr>
    <td align="center"><strong>News with context.</strong><br /><em>Categories, summaries, limitations, and sources.</em></td>
    <td align="center"><strong>A schedule, not just a list.</strong><br /><em>Appointments and flexible work, clearly separated.</em></td>
  </tr>
  <tr>
    <td width="50%" valign="top"><a href="assets/readme/priorities.png"><img src="assets/readme/priorities.png" alt="Must-do and nice-to-do sections separating essential work from optional ideas" /></a></td>
    <td width="50%" valign="top"><a href="assets/readme/tomorrow.png"><img src="assets/readme/tomorrow.png" alt="Evening briefing showing tomorrow's appointments, preparation, and flexible plans in the night palette" /></a></td>
  </tr>
  <tr>
    <td align="center"><strong>Space for priorities.</strong><br /><em>Keep the essentials distinct from the possibilities.</em></td>
    <td align="center"><strong>A gentler tomorrow.</strong><br /><em>See the next day's plan before closing this one.</em></td>
  </tr>
</table>

## Thoughtful by design

- **Personal, not generic.** Choose your secretary's name, tone, avatar, and appearance.
  The website supports English and Simplified Chinese.
- **Comfortable to read.** Distinct day and night palettes, phone-friendly layouts,
  clickable sources, section navigation, and reduced-motion support.
- **Continuity without clutter.** Saved briefings, a seven-day browser archive,
  and persistent task and idea records keep useful context close.
- **You stay in control.** Generation is an explicit action. Questions and permissions
  stay visible; calendar changes and project writes require authorization.
- **Your own space.** Personal records stay separate from the source. The multi-user
  deployment supports authenticated HTTPS, encrypted storage, and isolated agent accounts.

## Make it yours

GoodMorning is currently **beta** and designed for Linux with Python 3.9+ and an
OpenCode/OpenChamber agent. It is not a standalone chatbot or an unattended daily service.

Start with the [deployment guide](docs/deployment.md), then
[guided setup](docs/initialization.md). You can use the browser pages or ask the
installed skill naturally for a morning briefing, an evening review, a to-do, or an idea capture.
Optional project access requires Node.js 22.18+.

For hosted use, read the [security and privacy boundaries](docs/website-security.md).
Self-hosting does not hide requests from the AI provider you choose.

Ideas, feedback, and focused improvements are welcome in
[GitHub Issues](https://github.com/S-Sebb/GoodMorning/issues).

## License

GoodMorning is licensed under the [MIT License](LICENSE).
Bundled [relay code](vendor/openchamber-relay/LICENSE) and
[fonts](assets/web/fonts/OFL.txt) retain their respective license notices.

---

<p align="center"><em>Less noise. More space for your day.</em></p>
