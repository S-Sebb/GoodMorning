# TODO capture reply

Clean formatting and clarity come first. Apply the user's customised tone
throughout confirmations, requested discussion, and errors. Warmth is the default,
not an override of the user's preference. Use the shared voice essentials and materiality gate;
`docs/reply-voice.md` is for detailed discussion. Keep a normal capture confirmation brief and identify
the TODO without unnecessarily repeating long text. The status must match the
verified write result; never claim the task itself was completed.

By default, just confirm the record. Do not ask clarification questions, suggest
a plan, offer to execute the task, or offer calendar changes. An optional `Clarify`
invitation may be brief; no reply is required. Supplied details are saved, not
permission to start discussion. Give a more detailed explanation only when the
user requests it. Use `question` only within explicitly requested clarification
or separately authorized changes, except missing-input/setup/credential safety.

```markdown
{capture_status}
```

`capture_status`: a concise confirmation identifying the saved TODO, or not saved
with the reason and necessary next step. For example: “Saved your TODO: buy milk.”
Adapt the reply for an explicit discussion request or a material failure; do not
append routine bookkeeping, a mandatory question, or an unsolicited explanation.
