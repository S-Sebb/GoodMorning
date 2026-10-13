# Simplified Chinese interface copy

This guide governs the Chinese side of `assets/web/translations.json`: the keys are
English source strings and the values are the `zh-CN` interface text. Read it before
adding or changing a Chinese string. User-authored content is never run through this
catalog, so briefings and chats keep the language the user actually wrote.

## The one rule

Translate the *feeling*, not the words. Most catalog entries are atmosphere
(hints, empty states, greetings, little encouragements). Their English is casual
and warm, so the Chinese must read casual and warm too—not like a manual. A line
that is accurate but stiff has already failed the job it was written for.

## Three kinds of string

1. **Flavor copy** — empty states, mode taglines, welcome and closing lines. Rewrite
   freely. Keep the meaning and the energy; drop word-for-word correspondence.
2. **Neutral labels** — buttons, section titles, field names. Keep them short and
   instantly readable. A light touch is fine; do not get cute where a label must be
   scanned in a hurry.
3. **Important information** — errors, security, permissions, limits, save and
   delivery results, anything the user must act on. Meaning, scope and next step
   must be exact. You may soften the wording, but never the facts. Do not invent
   reassurance, hide a failure, or blur an uncertain outcome.

When a string is both important and friendly (for example a failed save), keep the
clarity and add only a small warmth. Prefer "没能保存，再试一次吧" over either a
cold "保存失败" or a careless "别担心，没事的".

## Voice: warm and gently playful

- Write like a kind assistant talking to one person. Use "你", never "您".
- A soft particle now and then ("呀" "吧" "哦" "啦" "呢") adds warmth. One per
  sentence at most. Stacked particles read as baby talk and hurt trust.
- Avoid four-character idioms and officialese ("一目了然", "留有余地",
  "尚未安排处理日期"). They sound like a government form, not a friend.
- Prefer verbs and short clauses over long noun stacks. "把它变成你喜欢的样子"
  beats "让此空间更符合你的偏好".
- Do not over-promise, flatter, or pretend to feel. No "一定会成功", no "我相信你
  可以的", no invented emotion about empty data.
- Keep flirting out of it. Warm is not flirty, and this file is product copy.

## Do not translate literally

Recompose the sentence the way a Chinese speaker would actually say it.

| English source | Stiff (avoid) | Natural (prefer) |
|---|---|---|
| A little space to plan. | 一起理清计划。 | 一起把小计划理一理。 |
| Your week, at a glance. | 一周安排，一目了然。 | 这一周，一眼看清。 |
| Keep that spark. | 留住这一刻的灵感。 | 趁灵感还热乎，先记下来。 |
| No story was told by you for this day. | 这一天你没有讲述故事。 | 这一天，你还没讲你的故事。 |
| Let the past pages stay as they are. | 就让过去的页面保持原样吧。 | 过去的页面，就让它们安静待着吧。 |

## Mechanics

- Never change a catalog key, and never edit user-visible content to match a key.
- Keep every placeholder exactly as written, including its name: `{date}`, `{count}`,
  `{name}`, `{position}`, `{mode}`, `{language}`. The value may move it to a place
  that reads naturally in Chinese.
- Keep the file valid JSON: two-space indent, UTF-8, no trailing commas, one
  trailing newline. It must round-trip through `json.dumps(..., ensure_ascii=False,
  indent=2)`.
- Some strings are asserted in tests (limits, security text, key labels). Update the
  test expectation in the same change when the wording shifts, and only when the
  meaning is unchanged.

## Terms

Keep these consistent across the catalog: 秘书 (secretary), 简报 (briefing),
约定 (appointment), 待办 (to-do), 灵感 (eureka/idea), 初始化 (initialize),
日程 (schedule), 章节 (section), 形象 (avatar), 更新日志 (patch notes).
