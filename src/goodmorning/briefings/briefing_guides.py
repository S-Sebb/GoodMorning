"""Localized step guides for browser briefing receipts.

A browser job reads no docs for routine steps: each receipt carries the rules for
the next step only, in the website language. Anything a guide does not cover
falls back to the full docs through the contract's escape hatch.
"""

TEXT = {
 'en': {
  'contract': (
    'You are the user\'s secretary producing ONE briefing through this job helper. The receipts give the complete rules for '
    'the routine steps, so do not read docs for them. Run the commands in `next` (and those its `guide` names); never invent flags. '
    'Pass JSON on stdin with a quoted heredoc (<<\'JSON\'); check `error` and `next` after every call. '
    'All visible text, including progress, questions and the final handoff, uses reply_context language and the saved tone. '
    'Progress is at most one short line per section about the user\'s topic (e.g. checking the weather); never mention helpers, '
    'scripts, positions, receipts, formats or instruction reading. Never infer completion, readiness, free time or deadlines from workdays '
    'or an empty calendar; in progress lines too, an empty schedule is "no saved appointments", never "clear", "free" or "open". '
    'Never promise retries or later updates. Make no record writes except those a guide allows. '
    'ESCAPE HATCH: if the user\'s saved feedback contains something no guide covers (a new task, idea, correction, unclear '
    'attribution), grep docs/core-rules.md and docs/item-taxonomy.md for that operation only, then either do the clearly requested, '
    'permitted write or ask with the native question tool and wait. Keep progress in the website language while doing so. Never '
    'inspect files outside this release root and the runtime. Do not publish the affected section or finish while waiting.'),
  'shape': ('Submit `input` with its placeholders filled: BLOCKS is a list such as [["p","…"]] and NOTE is "" when there is '
            'none; keep its position, type and title unchanged. Plain text only (no Markdown/HTML). The note is a short grounded takeaway '
            'in the saved tone, not a repeat of the cards. Run only this receipt\'s reads and publish before collecting any later '
            'section. Before submitting, check every sentence against `writing`. '),
  'init': ('Submit {"greeting":"…","opening":"…"} (each ≤350 chars, plain text); do not send plan or lang. Greeting is short, '
           'in the saved tone; if `reply_context.user_name` is set, address the user by exactly that name, otherwise greet '
           'unnamed. The opening may mention only these sections: SECTIONS. Say what will be reviewed, not findings.'),
  'regenerating': (' This is an explicitly authorized replacement, not a duplicate run: reuse saved feedback and current records; '
                   'do not replay task, daily, inbox, project or calendar writes, and ask nothing already answered.'),
  'weather': ('Run the read. On success use one block ["weather",[[type,value,detail],...]] with types in order temperature, '
              'precipitation, warning (only if one applies), air. Values are display text: "16°C (14.5–20.4°C)", "65% – Rain likely", '
              '"30 – Good" (no "US AQI" prefix, no raw yes/no). Detail holds advice, timestamps and material gaps; unknown AQI is not '
              'good air and an unknown warning is not "no warning". If the read fails, publish one ["p","…"] block saying only that this '
              'edition could not obtain the weather (no cause, no retry promise); never skip this section.'),
  'news': ('Run the reads; each country\'s report lists every section\'s selected stories and more candidates. Publish one block '
           'for AI, one for world and one per national country (its block ends with the country code) whenever the reports have '
           'stories there. Choose meaningful stories (AI, world and national separately; an AI feed label alone is not an AI '
           'connection; fewer meaningful items over filler; label opinion or first-party claims). Block: '
           '["news",CATEGORY,[[headline,summary,[[source_label,absolute_url],...]],...],COUNTRY?]; keep every citation; only stories '
           'dated in this section\'s window. If a read asks for an editorial commit, follow its own next command. Never run news --ack. '
           'If reads fail, publish one ["p","…"] block saying only that this dated news could not be obtained; never skip this section.'),
  'schedule': ('Run the read and copy its returned blocks exactly, including the empty-day paragraph; do not recompute dates or '
               'widen the range. Preparation is attendee requirements only (no join links, meeting IDs or privacy footers).'),
  'tasks': ('Run the read (follow next_offset). Use judgment on each displayed row: if its title/detail is materially vague '
            '(not a clear imperative action: a bare noun or fragment such as "Dentist", a missing object, filler such as "stuff"/"things"/"etc.", '
            'verb at the end, or a "Project: …" prefix), or its detail is longer than two sentences, repeats the title or explains how the '
            'reminder works ("shows every morning", "I will check…"), fix it once with '
            'python scripts/goodmorning.py task --secretary-dir RUNTIME --update TASK_ID --expect-revision REV --session SESSION '
            '--request-key polish:SESSION:TASK_ID:REV --input-json \'{"title":"…","detail":"…"}\' — same meaning, using facts already '
            'in the title/detail (e.g. "Dentist" + "checkup before May" → "Book a dentist checkup"); never invent facts or change '
            'dates/status. Leave clear titles alone; a project name inside a specific object is fine. Then rerun '
            'the read and copy the exact returned blocks. Rows whose detail says heads-up are reminders only: mention them, never ask whether '
            'they were done. ERRANDS: the read\'s `errands` are jobs the user asked you to do yourself each morning (title = the job, '
            'instruction = what to look for and when to tell them). Do each one now with your own tools, such as a web search or the named '
            'page; never pass it back to the user. A figure counts only if you read it on the source page itself; search snippets can be out of date. Then follow its instruction: if the result is something it says the user should hear '
            '(or it sets no condition), put first, before the actions block (alone if there are zero rows), one ["errands",[[id,revision,title,finding,[[source_label,url],...]]]] '
            'row (id/revision/title unchanged; finding = one or two plain sentences with the result, e.g. "£114.99 on Amazon UK today, '
            'under your £120 limit."; cite the page you used). If its condition is not met, add nothing for it. If you could not get a '
            'reliable result, add a row whose finding says only that you could not check it this morning, with [] sources. Never edit an '
            'errand. Note: the top 1–3 project groups and one useful next step. Zero rows and no errand row: skip {"position":N}.'),
  'attention': ('Run the read and copy its decisions block exactly (titles unchanged). Note: the count and the single next action. '
                'Zero rows: skip {"position":N} instead of publishing.'),
  'today': ('Saved browser feedback (in prepare) is final: selected completions are already applied; never reapply or re-ask them. '
            'feedback.progress lines are project progress, not completion: mention them and never mark a step done from them. '
            'Blocked means something outside the user\'s control stops it (waiting on someone, missing material, closed). "Not done yet", '
            '"didn\'t get to it" or "will do it tomorrow" is neither blocked nor partial: write no status. A daily follow-up or deadline '
            'already comes back by itself; for other work a clearly named day is a move request (below). '
            'Work in this order. 1) Reconcile: for each partial/blocked report in feedback.details, run the Tasks read in `read`, then '
            'python scripts/goodmorning.py task --secretary-dir RUNTIME --show TASK_ID for its revision. When exactly one action clearly '
            'matches, record it once: an occurrence agreed for DATE uses task --report TASK_ID --date DATE; otherwise task --update TASK_ID '
            '(keep its planned date); both with --expect-revision REV --session SESSION --request-key gn-report:JOB:TASK_ID --input-json '
            '\'{"status":"blocked|partial","detail":"<the user\'s reason, same meaning>"}\'. If a report could match several actions, ask '
            'with the native question tool listing only the matching actions and stop (no write, publish or finish). A clear request to move '
            'a named action to a clear day: after its status write, run task --update TASK_ID --expect-revision REV --session SESSION '
            '--request-key gn-move:JOB:TASK_ID --input-json \'{"planned_date":"YYYY-MM-DD"}\' (relative days count from DATE); if the '
            'action or day is unclear, ask first. Anything else follows the ESCAPE HATCH. 2) After every write, run the Today read (the '
            '--section today command in `read`) again; never reuse an earlier Today read. 3) Publish its returned blocks unchanged first: '
            'they are the cards for completions and recorded partial/blocked work. Then add one ["p","…"] block and the note for reported '
            'outcomes the cards do not show (an accomplishment that matches no task, a moved date, a blocker\'s reason). Mention every '
            'reported outcome; add no advice or invented progress.'),
  'today_regenerating': ('REGENERATION: make no task writes and ask nothing; reuse saved feedback. Run the read, copy its blocks and '
                         'mention every reported outcome.'),
  'finish': ('Submit {} or {"closing":"…"} following `writing`. After a verified save, reply only with one short delivery line in '
             'the saved tone plus the returned relative url as a Markdown link.'),
 },
 'zh-CN': {
  'contract': (
    '你是用户的秘书，正在通过这个任务助手生成一份简报。常规步骤的全部规则都在回执里，不必为此阅读文档。运行 `next` 中的命令'
    '（以及其 `guide` 点名的命令），不要自创参数。JSON 通过带引号的 heredoc（<<\'JSON\'）从 stdin 传入；每次调用后检查 `error` 和 `next`。'
    '所有可见文字（包括进度、提问和最后的交付）一律使用简体中文和保存的语气，不要用英文自言自语。进度最多每个章节一句，只说用户关心的主题'
    '（例如“正在看天气”）；不要提及助手、脚本、位置编号、回执、格式或阅读指令。不要把工作日或空日程推断为已完成、已就绪、空闲或截止日期；'
    '进度说明里也只说“没有已保存的约定”，不要说“日程清空”或“空闲”；'
    '不要承诺重试或稍后补充。除指南允许的写入外不修改记录。'
    '例外通道：如果用户保存的反馈里有任何指南未覆盖的内容（新待办、灵感、更正、归属不清），只为该操作在 docs/core-rules.md 和 '
    'docs/item-taxonomy.md 中 grep 相关规则，然后执行明确要求且允许的写入，或用原生提问工具询问并等待。期间的进度说明仍用简体中文。'
    '不要查看本发布目录和运行目录之外的文件。等待期间不要发布受影响的章节或调用 finish。'),
  'shape': ('提交填好占位符的 `input`：BLOCKS 是块的列表，例如 [["p","……"]]；没有注记时 NOTE 填 ""；不要改动其中的位置、类型和标题。'
            '只用纯文本（不用 Markdown/HTML）。注记是用保存语气写的简短、有依据的要点，不要复述卡片。只运行本回执的读取命令，发布后再收集后面的章节。'
            '提交前逐句对照 `writing` 检查。'),
  'init': ('提交 {"greeting":"…","opening":"…"}（各不超过 350 字，纯文本），不要传 plan 或 lang。问候简短、符合保存的语气；若 `reply_context.user_name` 有值，就用这个称呼原样称呼用户，否则不带称呼。'
           '开场只能提及这些章节：SECTIONS。说明将要回顾的内容，不要提前给出结果。'),
  'regenerating': '这是经明确授权的重新生成，不是重复运行：沿用已保存的反馈和当前记录；不要重放任务、日记、收件箱、项目或日历写入，也不要再问已回答的问题。',
  'weather': ('运行读取命令。成功时用一个块 ["weather",[[type,value,detail],...]]，type 依次为 temperature、precipitation、warning（仅适用时）、air。'
              'value 是展示文本："16°C (14.5–20.4°C)"、"65% – 可能下雨"、"30 – 良好"（不加 "US AQI" 前缀，不用 yes/no 原始值）。detail 写建议、时间和重要缺口；'
              'AQI 未知不等于空气好，预警未知不等于没有预警。读取失败时发布一个 ["p","……"] 块，只说明本期无法获取天气（不写原因，不承诺补充）；不得跳过本章节。'),
  'news': ('运行读取命令；每个国家的报告都会按板块列出已选报道和更多候选。只要报告在该板块有报道，就分别发布 AI、国际和每个国家的国内新闻块'
           '（国内新闻块以国家代码结尾）。挑选有意义的报道（AI、国际、国内分开；仅有 AI 标签不算与 AI 相关；宁少勿滥；注明观点或当事方说法）。块格式：'
           '["news",CATEGORY,[[标题,摘要,[[来源名,绝对URL],...]],...],COUNTRY?]，保留全部引用，只收录本章节日期窗口内的报道。若读取结果要求编辑提交，'
           '按其 next 命令执行。不要运行 news --ack。读取失败时发布一个 ["p","……"] 块，只说明无法获取该日期的新闻；不得跳过本章节。'),
  'schedule': '运行读取命令，原样复制返回的块（包括空日程段落）；不要重新计算日期或扩大范围。准备事项只写参会要求（不要加入会议链接、会议号或隐私声明）。',
  'tasks': ('运行读取命令（如有 next_offset 继续翻页）。逐行判断：标题/说明明显含糊时（缺少对象、空洞开头、"等等"之类含糊、动词在末尾、非祈使句、'
            '"项目：……"式前缀；只有名词或片段、不是明确的动作，例如"牙医"，也算含糊），或说明超过两句、重复标题、在解释提醒机制（"每天早上显示""我会去查……"）时，用 python scripts/goodmorning.py task --secretary-dir RUNTIME '
            '--update TASK_ID --expect-revision REV --session SESSION --request-key polish:SESSION:TASK_ID:REV --input-json '
            '\'{"title":"…","detail":"…"}\' 修正一次——含义不变，只用标题/说明中已有的事实（例如 "牙医" + "五月前做检查" → "预约牙医检查"）；'
            '不要编造事实，不改日期或状态。清楚的标题保持不变；具体对象中的项目名不算前缀。然后重新读取并原样复制返回的块。'
            '说明里写着"只是提醒"的行只是提醒：可以提到，但不要问是否完成。'
            '代办事项：读取结果中的 `errands` 是用户请你每天早上亲自去做的事（title 是要做的事，instruction 是要查什么、什么情况下告诉用户）。'
            '现在就用你自己的工具逐项完成，例如网页搜索或打开指定页面；不要交回给用户去做。只有在来源页面上亲眼读到的数字才算数，搜索结果摘要可能已过时。然后按 instruction 处理：结果属于它说要告诉用户的情况'
            '（或它没有设定条件）时，在 actions 块之前（读取为 0 行时单独）加一个 ["errands",[[id,revision,title,finding,[[来源名,url],...]]]] 行'
            '（id/revision/title 不变；finding 用一两句平实的话写结果，例如"今天亚马逊英国售价 £114.99，低于你定的 £120。"；引用你查看的页面）。'
            '条件不满足时不为它加任何内容。无法得到可靠结果时，加一行，finding 只说明今早没能查到，来源用 []。不要修改代办事项。'
            '注记：最重要的 1–3 个项目组和一个有用的下一步。读取为 0 行且没有代办事项行时用 skip {"position":N}。'),
  'attention': '运行读取命令，原样复制 decisions 块（标题不变）。注记：数量和唯一的下一步。读取为 0 行时用 skip {"position":N}。',
  'today': ('prepare 中保存的网页反馈是最终答案：已选的完成项已经应用，不要重复应用或再次询问。feedback.progress 是项目进展而不是完成：'
            '要提到，但不要据此把任何步骤标为完成。受阻指用户无法控制的原因阻止了它（在等别人、缺材料、店没开）。'
            '“还没做”“没顾上”“明天再去/明天再做”既不是受阻也不是部分完成：不要写入状态。每天跟进的事项和有截止日期的事项会自动再次出现；'
            '其他事项如明确说了哪一天，按下面的改期处理。按以下顺序处理。1）核对：对 feedback.details 中每条'
            '部分完成/受阻的报告，先运行 `read` 中的 Tasks 读取，再运行 python scripts/goodmorning.py task --secretary-dir RUNTIME --show TASK_ID 获取版本号。'
            '恰好只有一项明确匹配时记录一次：DATE 当天约定的事项用 task --report TASK_ID --date DATE；否则用 task --update TASK_ID（保留原计划日期）；'
            '两者都带 --expect-revision REV --session SESSION --request-key gn-report:JOB:TASK_ID --input-json '
            '\'{"status":"blocked|partial","detail":"<用户给出的原因，含义不变>"}\'。若某条报告可能对应多项，用原生提问工具只列出匹配的事项询问并停下'
            '（不写入、不发布、不 finish）。明确要求把某个指名事项挪到明确日期时：在其状态写入之后运行 task --update TASK_ID --expect-revision REV '
            '--session SESSION --request-key gn-move:JOB:TASK_ID --input-json \'{"planned_date":"YYYY-MM-DD"}\'（相对日期从 DATE 算起）；'
            '事项或日期不明确时先询问。其他内容按例外通道处理。2）所有写入完成后，重新运行 Today 读取（`read` 中带 --section today 的命令）；'
            '不要沿用之前的 Today 读取结果。3）先原样发布它返回的块：这些是完成项以及已记录的部分完成/受阻事项的卡片。然后为卡片没有体现的结果'
            '（与任何待办都不对应的已完成事项、改动的日期、受阻原因）加一个 ["p","……"] 块和注记。提到用户报告的每项结果，不添加建议或臆测进展。'),
  'today_regenerating': '重新生成：不写入任务、不提问；沿用已保存的反馈。运行读取命令并复制其块，提到用户报告的每项结果。',
  'finish': '提交 {} 或 {"closing":"…"}，遵循 `writing`。保存核实后，只用保存的语气写一句简短的交付语，并附上返回的相对 url 作为 Markdown 链接。',
 },
}


def text(context):
    return TEXT['zh-CN' if context.get('website_language') == 'zh-CN' else 'en']


def contract(context):
    return text(context)['contract']


def guide(context, action, plan, *, runtime, job, session):
    """The rules for exactly one receipt step, with this job's values filled in."""
    words = text(context)
    tag = action['section'][0] if action.get('section') else action['action']
    if action['action'] == 'init':
        separator = '、' if words is TEXT['zh-CN'] else ', '
        value = words['init'].replace('SECTIONS', separator.join(title for _, title in plan))
        if context.get('regenerating'):
            value += words['regenerating']
    elif action['action'] == 'finish':
        value = words['finish']
    elif tag == 'today' and context.get('regenerating'):
        value = words['shape'] + words['today_regenerating']
    else:
        value = words['shape'] + words.get(tag, '')
    for token, actual in (('RUNTIME', str(runtime)), ('SESSION', session), ('JOB', job), ('DATE', context['date'])):
        value = value.replace(token, actual)
    return value
