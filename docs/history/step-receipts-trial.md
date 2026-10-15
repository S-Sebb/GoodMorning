# Step receipts for browser briefings: trial record

Question: should a browser briefing agent read the whole rulebook before it starts,
or receive the rules for one step at a time from the job helper?

Before this change, a `/gm` or `/gn` browser job read `AGENTS.md`, `core-rules`,
`browser-generation`, the workflow, `item-taxonomy`, `briefing-format` and
`reply-voice` (about 60 KB of English) before its first step. Afterwards it reads
no docs up front: `job prepare` returns a localized `contract`, and each receipt's
`next.guide` (`src/goodmorning/briefings/briefing_guides.py`) holds that step's
rules in the website language. Anything a guide does not cover goes through the
contract's escape hatch to the relevant part of `core-rules`/`item-taxonomy`.

## Method

`tests/benchmarks/briefing_tone_live.py` on synthetic accounts, real models, both
configured languages: English on Muse Spark 1.3 Contributor XHigh, Chinese on
DeepSeek V4.1 Flash High (the paid `opencode-go` endpoint, because the free tier
returned 429 under trial load). Six scenarios: empty morning with unavailable
providers, resumed checkpoint, evening feedback with regeneration, ambiguous report
attribution, and two judgment cases added for this change: vague task titles to
polish without inventing facts, and messy evening feedback mixing a partial report,
a blocker, an untracked accomplishment and a request to move a task to Monday.

Arms: **A** = `main` at `c25dceb`; **E** = this branch. Both ran the same harness.
Excluded runs: provider 503/429 failures, reads truncated by the trial CLI output
cap, and two runs (one per arm) where the agent explored the harness and sibling
runs through the shell (the trial permissions limit file tools, not shell).

## Results (final branch)

| | A | E |
|---|---|---|
| Functional pass | 20/22 | 24/24 |
| Doc reads per run | 8.0 | 0.3 |
| Tool calls per run | 41.3 | 22.8 |
| Model input tokens, all runs | 36.2M (22 runs) | 14.3M (24 runs) |

Median input tokens per scenario, E as a share of A: morning empty 0.48 en / 0.79 zh,
resume 0.21 / 0.81, vague titles 0.39 / 0.23, evening feedback 0.40 / 0.51,
ambiguous report 0.38 / 0.40, messy feedback 0.16 / 0.40.

A's two failures were judgment slips the receipts now address: cosmetic
"polish" writes to already-clear tasks, and silently ignoring the request to move
the Atlas report to Monday (A ignored it in two of four English runs across both trial rounds). E applied
or confirmed the move, recorded the partial and blocked reports, and mentioned the
untracked accomplishment in every valid run of both languages.

## What iteration changed

- First version (no section list in the init guide): openings invented an inbox review.
- Bare-noun titles ("Groceries") were left unpolished until the tasks guide named them.
- With only a generic escape hatch, DeepSeek read up to 13 docs on the messy-feedback
  case (2.7× A's tokens, English narration). Handling an untracked accomplishment
  and a clear move request inside the Today guide removed that cost.
- Agents that read Today before their writes published stale cards; the Today
  guide now orders: writes, fresh Today read, publish its blocks, then prose.
- A publish title mismatch on the latest-news section sent one run into debugging;
  receipts now carry an `input` template with the position and plan title filled in.

## Not solved

- English progress lines in Chinese runs: 2 of 12 E runs (8 lines) versus 3 of 11
  A runs (11 lines). The localized contract reduces but does not prevent it.
- One English progress line still said "Your schedule is clear" (A: two).
- Heuristic flags were reviewed by hand; one or two samples per cell is not
  statistical evidence. No live providers, public deployment or encrypted accounts.
