# Saved briefing cards for OpenCode V2

This opt-in plugin adds one agent tool, `briefing_cards`. It renders an already
saved `/gm` or `/gn` snapshot as sharp, lossless editorial cards, then returns a
small attachment marker. Code expands that marker in the assistant response;
the model never reads or writes the encoded image data.

An explicit `/gm` or `/gn` request receives a short default-card-delivery
instruction. It preserves text-only overrides, duplicate rules and consent.
Normal OpenChamber chat folders require global installation, not just the
checkout's project loader; see the deployment guide.

## Agent contract

1. Complete the normal workflow and save the full text snapshot first.
2. Call `briefing_cards({"date":"YYYY-MM-DD","kind":"gm"})`, or use `gn`.
   Use the profile-local date supplied by workflow preparation.
3. Put the returned marker exactly once on its own line in the **final answer**,
   outside code fences. Keep any material warnings and a link to the saved text.
4. Do not read, transcribe or attach Base64 files. Do not acknowledge a new news
   report until visible delivery is verified. A saved render is not delivery.

If the tool reports an error, keep and present the saved text. Do not invent a
marker or fetch the briefing again. Re-displaying a completed briefing does not
authorize replacing its snapshot or marking another run.

The tool accepts no arbitrary paths or network URLs. Input schemas stay small;
ordinary conversations do not activate image rewriting. Tool receipts contain
only a short marker, counts, the saved text path and instructions.

## Deployment

See the [short deployment guide](DEPLOYMENT.md).
Copy this complete folder to a project's `.opencode/plugins/` directory, or use
`npm pack` to make a portable archive. No dependency installation is required.

Install this folder globally under `~/.config/opencode/plugins/` for ordinary
OpenChamber chats, or under one project's `.opencode/plugins/` for project-only
use. Do not register both copies. No npm dependencies are needed.
OpenCode's V2 plugin interface is structural;
its `Plugin.define` helper would return the same object unchanged.

Requires OpenCode V2, Python with Pillow/WebP support, and readable fonts.
SDK integration tests used 2.0.11; this OpenChamber deployment runs 2.0.25.
The installed Inter and TeX Gyre fonts are preferred; DejaVu Sans is a fallback.
Chinese content requires the installed Noto CJK font. The runtime defaults to
`SECRETARY_DIR` or `~/.local/share/GoodMorning/secretary`. A configured plugin
entry can override it with `options.runtime`; agents cannot change it per call.

Artifacts live under `RUNTIME/visual/DATE.KIND/SOURCE_HASH/`. They contain the
complete original source, cards, sources, a local HTML viewer and a manifest.
Directories are immutable per source hash. Existing validated renders can be
reused, including the previously approved eight-card 2026-10-10 design.

New attachment envelopes use invisible, unused Markdown reference definitions;
the earlier escaped-HTML-comment envelopes are still recognized and filtered.

Ownership receipts use OpenCode's durable plugin storage. Keep that storage and
the plugin enabled for conversations containing its images. Filters cover
primary context, summarization, compaction and title requests. They retain user
images and original text and do not edit saved history. Forked owned history is
filtered too, but only the original session can expand a prepared marker.

## Supported transport and failure boundaries

- OpenAI-compatible Chat Completions HTTP/SSE.
- OpenAI Responses HTTP/SSE and experimental WebSocket receive hooks.
- Fragmented tokens, UTF-8, SSE frames, multiline SSE data, CRLF, repeated final
  text, cancellation and bounded frames are handled.
- Unknown receipts display an unavailable-image notice. Changed assets stop
  response expansion. Missing ownership storage or damaged owned blocks stop
  model requests rather than leak encoded bytes.
- Other protocols and non-streaming HTTP are not attachment adapters. Use saved
  text rather than claim image delivery on an unsupported provider.

The final serialized HTTP/WebSocket request also has a guard that stops any
owned image block left after protocol conversion. A read-only diagnostics RPC
reports card counts and filtering/wire checks, never message bodies or headers:

```sh
opencode api post '/api/rpc/goodmorning.cards/status?location%5Bdirectory%5D=PROJECT_PATH' \
  --data '{"input":{"sessionID":"SESSION_ID"}}'
```

Use `--server` for the actual OpenChamber-connected server when it differs from
the CLI's managed background service. Encode the absolute project path in the
query. Loader changes are watched; a changed external implementation module may
need a project-location reload. Do not restart unrelated projects unnecessarily.

Removing or disabling the plugin removes its filtering protection. OpenChamber
updates cannot overwrite these project files, but OpenCode updates may change
the hook API. Verify compatibility before upgrading or disabling the plugin.
Keep receipts for as long as image-bearing history remains. Image data still
uses local storage and client bandwidth; it is not free network traffic.

The renderer preserves headings, paragraphs, list items, schedule times and
table details, warnings, news summaries and citation references. It omits
explicitly labelled duration estimates and the two known estimate phrases in
the original design. It does not broadly remove numbers, dates or durations
from news or scheduled events. It refuses oversized layouts rather than crop.

## Validation

```sh
node --test tests/test_briefing_delivery.mjs
python -m unittest discover -s tests -q
```

Production-plugin integration experiments under `/tmp/opencode/gm-plugin-lab`
used a local fake provider, the approved full eight-card payload, real agent tool
execution, host restart with a file-backed database, follow-up generation and
compaction. Both HTTP and native WebSocket passed; no encoded image bytes were
present in captured provider requests. These are not real-provider billing tests.
