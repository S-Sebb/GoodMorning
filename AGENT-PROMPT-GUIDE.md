# Writing agent prompts

Write the shortest instructions that fully define the intended behavior.

- State the task, required inputs, permitted scope, and expected result.
- Use direct language, consistent terms, and ordered steps. Define conditions,
  defaults, and decision priorities so the same inputs lead to the same actions.
- Separate required actions, optional actions, and prohibitions. Make permission
  requirements explicit; do not leave consequential choices to the agent's judgment.
- Specify what to do when inputs are missing, instructions conflict, or an action
  fails. Define when to ask, stop, or retry; never encourage guessing or duplicate writes.
- Define completion and how to verify it. Specify the output format when it matters;
  do not allow success claims without evidence.
- Require the secretary to match the user's saved tone as closely as possible
  from the first visible message through confirmations, questions, progress and
  errors. Default to warm and helpful when no tone is saved. Preserve clarity,
  accuracy and safety; neither brevity nor failure handling should flatten the
  chosen voice into generic receipts. Review actual replies, not keywords alone.
- Remove repetition, filler, and unnecessary explanation—not essential constraints.
  For complex tasks, add one or two short examples that illustrate the rules
  without introducing exceptions.
- Coding-agent instructions (the **Coding agents** section of `AGENTS.md` and the
  guides it lists) get no model trials. Instead, verify that every command, path
  and tool behavior they describe works as written.
- For prompts that website agents read, test only new or modified prompts, plus directly affected neighbors, in each
  website language on the model and variant that language uses in production (`for_language` in
  `src/goodmorning/web/models.py`): today English on Muse Spark, Chinese on DeepSeek Flash. Never run cross pairs
  (English on DeepSeek, Chinese on Muse Spark); no user can reach them. Trial scripts pick the production model
  when `--model` is omitted. Determine the changed set from the diff against its merge-base;
  do not rerun the full matrix for unchanged established prompts. Use synthetic normal, ambiguous and
  failure cases for the changed behavior; verify actual actions, outputs and the user's tone. Retest fixes
  on every affected model and preserve evidence. Run the full matrix only for shared prompt infrastructure
  or release validation. Unavailable models or unresolved
  behavior mismatches mean validation is incomplete, not a pass.
