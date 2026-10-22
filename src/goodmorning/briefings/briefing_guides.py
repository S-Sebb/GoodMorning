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
            'in the saved tone, not a repeat of the cards. `results` holds this section\'s reads, already run for you (command, exit, '
            'output); do not run them again unless this guide says so. Before submitting, check every sentence against `writing`. '),
  'init': ('Submit {"greeting":"…","opening":"…"} (each ≤350 chars, plain text); do not send plan or lang. Greeting is short, '
           'in the saved tone. If `reply_context.user_name` is set, the greeting may call the user by exactly that name, or by none; '
           'it is the only place in the briefing for the name, so never use it in the opening, notes or progress. The opening may mention only these sections: SECTIONS. Say what will be reviewed, not findings.'),
  'regenerating': (' This is an explicitly authorized replacement, not a duplicate run: reuse saved feedback and current records; '
                   'do not replay task, daily, inbox, project or calendar writes, and ask nothing already answered.'),
  'weather': ('On a successful read use one block ["weather",[[type,value,detail],...]] with types in order temperature, '
              'precipitation, warning (only if one applies), air. Values are display text: "16°C (14.5–20.4°C)", "65% – Rain likely", '
              '"30 – Good" (no "US AQI" prefix, no raw yes/no). Detail holds advice, timestamps and material gaps; unknown AQI is not '
              'good air and an unknown warning is not "no warning". If the read fails, publish one ["p","…"] block saying only that this '
              'edition could not obtain the weather (no cause, no retry promise); never skip this section.'),
  'news': ('Each country\'s read in `results` lists every section\'s selected stories and more candidates from the 24 hours before '
           'this section\'s as-of time; stories the previous morning briefing showed are already removed. Publish one block '
           'for AI, one for world and one per national country (its block ends with the country code) whenever the reads have '
           'stories there. Choose meaningful stories (AI, world and national separately; an AI feed label alone is not an AI '
           'connection; fewer meaningful items over filler; label opinion or first-party claims). Block: '
           '["news",CATEGORY,[[headline,summary,[[source_label,absolute_url],...]],...],COUNTRY?]; keep every citation; only stories '
           'from these reads. Call them the past day\'s news, not yesterday\'s or breaking news. '
           'If reads fail, publish one ["p","…"] block saying only that the news could not be obtained; never skip this section.'),
  'schedule': ('Copy the read\'s returned block exactly, including the empty-day paragraph; do not recompute dates or '
               'widen the range. Preparation is attendee requirements only (no join links, meeting IDs or privacy footers).'),
  'tasks': ('Copy every page\'s rows (while next_offset is not null, rerun the read\'s command with --offset N). Make no record writes; ids, dates, '
            'status and revisions stay exactly as returned. Copy each row\'s title and detail exactly: they are the wording saved with the item. '
            'Only rows whose id is in the read\'s `fallback` list have no saved wording, and those you must check: if the title is vague, a '
            'fragment, not an imperative action, overlong or awkward, reword it for display as a clear imperative with a specific object, '
            'same meaning, no new facts, keeping names, numbers and project terms (e.g. "Dentist" + "checkup before May" → "Book a '
            'dentist checkup"), and whenever the detail holds more than one sentence or any of your own notes, rewrite its free text as at '
            'most one short sentence the user acts on, keeping any number, limit, place or contact they need (empty only when nothing '
            'like that remains), leaving out '
            'your own notes (how the reminder works, "I will check…", reminder dates or "tomorrow", "keep open until…", progress logs, IDs, '
            'remembered values); keep every code label ("Heads-up…", "Project:", "Optional", "Priority:", "Due:", "Soft target:", "Daily '
            'follow-up…", "Preparation for…", "Reminder trigger…", "Not reminded…") unchanged and in place. Rows whose '
            'detail says heads-up are reminders only: mention them, never ask whether they were done. ERRANDS: the read\'s `errands` are '
            'jobs the user asked you to do yourself each morning (title = the job, instruction = what to look for and when to tell them, '
            'extra = notes recorded with the user, last = your result from the latest earlier morning, or null). Do each one now with your '
            'own tools, such as a web search or the named page; never pass it back to the user. A figure counts only if you read it on the '
            'source page itself; search snippets can be out of date. Compare only with values in last or extra; never invent an earlier '
            'one. Put first, before the actions block (alone if there are zero rows), one ["errands",[[id,revision,title,finding,'
            '[[source_label,url],...],note],...]] block with a row for every errand (id/revision unchanged; title as given, reworded like a fallback row only when the errand\'s worded is false). note, always: what you '
            'found or why it failed, dated, for the next morning (e.g. "2026-10-16: £139.99 on the Amazon UK product page"). finding, what '
            'the user sees: one or two plain sentences with the result when the instruction says they should hear it or sets no '
            'condition (e.g. "£114.99 on Amazon UK today, under your £120 limit."); "" when its condition is not met, which hides the '
            'row; and when you could not get a reliable result, what you tried and why it failed, and that they can change the source '
            'with you in chat. Cite the page you used or tried, or []. Note: the top 1–3 project groups and one useful next step. '
            'Zero rows and no errands: skip {"position":N}.'),
  'attention': ('Copy the read\'s decisions block exactly (titles unchanged). Note: the count and the single next action. '
                'Zero rows: skip {"position":N} instead of publishing.'),
  'today': ('Saved browser feedback (in prepare) is final: selected completions are already applied; never reapply or re-ask them. '
            'feedback.progress lines are project progress, not completion: mention them and never mark a step done from them. '
            'A plan in feedback.details or feedback.progress that names a clear day for a step ("the day after tomorrow, check growth") is scheduling (step 1). '
            'Blocked means something outside the user\'s control stops it (waiting on someone, missing material, closed). "Not done yet", '
            '"didn\'t get to it" or "will do it tomorrow" is neither blocked nor partial: write no status. A daily follow-up or deadline '
            'already comes back by itself; for other work a clearly named day is a move request (below). '
            'Work in this order. 1) Reconcile: for each partial/blocked report in feedback.details, use the Tasks read in `results`, then '
            'python scripts/goodmorning.py task --secretary-dir RUNTIME --show TASK_ID for its revision. When exactly one action clearly '
            'matches, record it once: an occurrence agreed for DATE uses task --report TASK_ID --date DATE; otherwise task --update TASK_ID '
            '(keep its planned date); both with --expect-revision REV --session SESSION --request-key gn-report:JOB:TASK_ID --input-json '
            '\'{"status":"blocked|partial","detail":"<the user\'s reason, same meaning>"}\'. If a report could match several actions, ask '
            'with the native question tool listing only the matching actions and stop (no write, publish or finish). A clear request to move '
            'a named action to a clear day: after its status write, run task --update TASK_ID --expect-revision REV --session SESSION '
            '--request-key gn-move:JOB:TASK_ID --input-json \'{"planned_date":"YYYY-MM-DD"}\' (relative days count from DATE); if the '
            'action or day is unclear, ask first. A plan for a named action on a clear day needs no status report: run only that move; '
            'a step planned for that day only if a condition holds ("if there are enough cells, do X") still moves, and the note states the condition. '
            'A planned step matching no saved action: save it once with python scripts/goodmorning.py task --secretary-dir RUNTIME --session SESSION --request-key gn-plan:JOB:N --add --input-json '
            '\'{"raw":"<the user\'s words>","task":{"title":"…","project":"<its project>","planned_date":"YYYY-MM-DD","timezone":"<profile timezone>",'
            '"detail":"<any condition the user gave, e.g. only if enough cells>"}}\'. '
            'Progress without a clear day schedules nothing. Anything else follows the ESCAPE HATCH. 2) After any write, rerun the Today read\'s command (the '
            '--section today entry in `results`); never reuse a Today read from before a write. 3) Publish its returned block unchanged first (none when it is null): '
            'they are the cards for completions and recorded partial/blocked work. Then add one ["p","…"] block and the note for reported '
            'outcomes the cards do not show (an accomplishment that matches no task, a moved date or newly planned step, a blocker\'s reason). Mention every '
            'reported outcome; add no advice or invented progress.'),
  'anime': ('New episodes of the user\'s shows that aired since the previous night briefing. If the read succeeded and its `block` '
            'is not null, publish that block exactly as returned (rows, titles, numbers, dates and covers are code-owned; never '
            'translate, reorder or add rows). NOTE: one short, lively line in the saved tone inviting the user to unwind with them. If '
            '`block` is null, publish one ["p","…"] block instead: a short, lively line in the saved tone saying no new episodes came out '
            'since the last night briefing, with NOTE "". If the read failed, publish one ["p","…"] block saying only that new episodes '
            'could not be checked this time (no cause, no retry promise). Never skip this section.'),
  'games': ('Steam games the user follows that are on sale right now at or above their chosen discount. If the read succeeded and its '
            '`block` is not null, publish that block exactly as returned (rows, names, discounts, prices, end dates and covers are '
            'code-owned; never translate, reorder or add rows). NOTE: one short, lively line in the saved tone about the deals. If `block` '
            'is null, publish one ["p","…"] block instead: a short, lively line in the saved tone saying none of the followed games is on '
            'sale at the chosen discount tonight, with NOTE "". If the read failed, publish one ["p","…"] block saying only that game '
            'sales could not be checked this time (no cause, no retry promise). Never skip this section.'),
  'stocks': ('The day\'s gain or loss on the user\'s saved stock holdings, for each market\'s latest closed session (A-shares today; US '
             'stocks usually the previous night). If the read succeeded and its `block` is not null, publish that block exactly as returned '
             '(rows, names, shares and prices are code-owned; never translate, reorder, round or add rows). NOTE: one short line in the saved '
             'tone with each market\'s day result from `markets`, named by its `market` label (amount with ¥ or $, and percent); kind about a loss, never '
             'alarming. If `not_found` lists codes, add one ["p","…"] block naming those codes and saying their prices could not be found. If the read '
             'failed, publish one ["p","…"] block saying only that stock prices could not be checked this time (no cause, no retry '
             'promise). Never skip this section.'),
  'today_regenerating': ('REGENERATION: make no task writes and ask nothing; reuse saved feedback. Copy the read\'s block (none when it is null) and '
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
            '只用纯文本（不用 Markdown/HTML）。注记是用保存语气写的简短、有依据的要点，不要复述卡片。`results` 里是本章节已替你运行好的读取结果（command、exit、output）；除非本指南要求，不要再次运行。'
            '提交前逐句对照 `writing` 检查。'),
  'init': ('提交 {"greeting":"…","opening":"…"}（各不超过 350 字，纯文本），不要传 plan 或 lang。问候简短、符合保存的语气；若 `reply_context.user_name` 有值，问候里可以原样用这个称呼，也可以不称呼；整份简报只有问候可以出现这个称呼，开场、注记和进度里都不要用。'
           '开场只能提及这些章节：SECTIONS。说明将要回顾的内容，不要提前给出结果。'),
  'regenerating': '这是经明确授权的重新生成，不是重复运行：沿用已保存的反馈和当前记录；不要重放任务、日记、收件箱、项目或日历写入，也不要再问已回答的问题。',
  'weather': ('读取成功时用一个块 ["weather",[[type,value,detail],...]]，type 依次为 temperature、precipitation、warning（仅适用时）、air。'
              'value 是展示文本："16°C (14.5–20.4°C)"、"65% – 可能下雨"、"30 – 良好"（不加 "US AQI" 前缀，不用 yes/no 原始值）。detail 写建议、时间和重要缺口；'
              'AQI 未知不等于空气好，预警未知不等于没有预警。读取失败时发布一个 ["p","……"] 块，只说明本期无法获取天气（不写原因，不承诺补充）；不得跳过本章节。'),
  'news': ('`results` 中每个国家的读取结果都会按板块列出本章节截止时间前 24 小时内的已选报道和更多候选，上一期晨间简报已展示的报道已被去除。'
           '只要读取结果在该板块有报道，就分别发布 AI、国际和每个国家的国内新闻块'
           '（国内新闻块以国家代码结尾）。挑选有意义的报道（AI、国际、国内分开；仅有 AI 标签不算与 AI 相关；宁少勿滥；注明观点或当事方说法）。块格式：'
           '["news",CATEGORY,[[标题,摘要,[[来源名,绝对URL],...]],...],COUNTRY?]，保留全部引用，只收录这些读取结果中的报道。称之为过去一天的新闻，'
           '不要说成昨天的新闻或突发新闻。读取失败时发布一个 ["p","……"] 块，只说明无法获取新闻；不得跳过本章节。'),
  'schedule': '原样复制读取返回的块（包括空日程段落）；不要重新计算日期或扩大范围。准备事项只写参会要求（不要加入会议链接、会议号或隐私声明）。',
  'tasks': ('复制每一页返回的行（next_offset 不为 null 时，用读取结果的 command 加 --offset N 再运行一次）。不写入任何记录：id、日期、状态和 revision 必须与返回的完全一致。'
            '原样复制每一行的标题和说明：它们是和事项一起保存的措辞。只有 id 在读取结果 `fallback` 列表里的行没有保存的措辞，这些行你必须逐一检查：标题含糊、只是片段、'
            '不是祈使句、过长或别扭时，为展示改写成清楚的祈使句，带具体对象，含义不变，不添加事实，保留名称、数字和项目用语（例如 "牙医" + "五月前做检查" → '
            '"预约牙医检查"）；说明只要超过一句或夹着你自己的笔记，就必须把自由文字改写成至多一句用户据此行动的话，保留用户需要的数字、价格线、地点或联系方式（只有这类信息都没有时才留空），去掉你自己的笔记（提醒机制、"我会去查……"、提醒日期或"明天"、"确认后再关闭"、'
            '进度记录、ID、记下的数值）；代码标签（"只是提醒……"、"项目："、"可选"、"优先级："、"截止："、"弹性目标日期："、"每天跟进……"、"为……准备"、'
            '"提醒触发……"、"……不提醒"等）原样保留在原位。'
            '说明里写着"只是提醒"的行只是提醒：'
            '可以提到，但不要问是否完成。代办事项：读取结果中的 `errands` 是用户请你每天早上亲自去做的事（title 是要做的事，instruction 是要查什么、'
            '什么情况下告诉用户，extra 是和用户一起记下的笔记，last 是你最近一次早上的结果，没有则为 null）。现在就用你自己的工具逐项完成，例如网页搜索'
            '或打开指定页面；不要交回给用户去做。只有在来源页面上亲眼读到的数字才算数，搜索结果摘要可能已过时。只和 last 或 extra 里的数值比较，绝不编造'
            '以前的数值。在 actions 块之前（读取为 0 行时单独）放一个 ["errands",[[id,revision,title,finding,[[来源名,url],...],note],...]] 块，'
            '每个代办事项一行（id/revision 不变；标题照抄，只有该代办事项的 worded 为 false 时才按上面 fallback 行的规则改写）。note 必填：查到了什么或为什么失败，带日期，留给下一个早上（例如"2026-10-16：亚马逊英国商品页 '
            '£139.99"）。finding 是用户看到的内容：instruction 说要告诉用户（或没有设定条件）时，用一两句平实的话写结果（例如"今天亚马逊英国售价 £114.99，'
            '低于你定的 £120。"）；条件不满足时为 ""，该行不显示；无法得到可靠结果时，用平实的话说明你试了什么、为什么没成功，并说明可以在聊天里和你商量'
            '换个来源。引用你查看或尝试的页面，没有就用 []。注记：最重要的 1–3 个项目组和一个有用的下一步。读取为 0 行且没有代办事项时用 skip {"position":N}。'),
  'attention': '原样复制读取返回的 decisions 块（标题不变）。注记：数量和唯一的下一步。读取为 0 行时用 skip {"position":N}。',
  'today': ('prepare 中保存的网页反馈是最终答案：已选的完成项已经应用，不要重复应用或再次询问。feedback.progress 是项目进展而不是完成：'
            '要提到，但不要据此把任何步骤标为完成。feedback.details 或 feedback.progress 中给某个步骤说了明确日期的计划（“后天看细胞生长情况”）属于排期，按第 1 步处理。受阻指用户无法控制的原因阻止了它（在等别人、缺材料、店没开）。'
            '“还没做”“没顾上”“明天再去/明天再做”既不是受阻也不是部分完成：不要写入状态。每天跟进的事项和有截止日期的事项会自动再次出现；'
            '其他事项如明确说了哪一天，按下面的改期处理。按以下顺序处理。1）核对：对 feedback.details 中每条'
            '部分完成/受阻的报告，先查看 `results` 中的 Tasks 读取结果，再运行 python scripts/goodmorning.py task --secretary-dir RUNTIME --show TASK_ID 获取版本号。'
            '恰好只有一项明确匹配时记录一次：DATE 当天约定的事项用 task --report TASK_ID --date DATE；否则用 task --update TASK_ID（保留原计划日期）；'
            '两者都带 --expect-revision REV --session SESSION --request-key gn-report:JOB:TASK_ID --input-json '
            '\'{"status":"blocked|partial","detail":"<用户给出的原因，含义不变>"}\'。若某条报告可能对应多项，用原生提问工具只列出匹配的事项询问并停下'
            '（不写入、不发布、不 finish）。明确要求把某个指名事项挪到明确日期时：在其状态写入之后运行 task --update TASK_ID --expect-revision REV '
            '--session SESSION --request-key gn-move:JOB:TASK_ID --input-json \'{"planned_date":"YYYY-MM-DD"}\'（相对日期从 DATE 算起）；'
            '事项或日期不明确时先询问。给指名事项定了明确日期的计划不需要先写状态，只做这一次改期；'
            '带条件的步骤（“细胞量足够就做 X”）同样改到那天，并在注记里写明条件。'
            '计划中的步骤没有对应的已保存事项时，用 python scripts/goodmorning.py task --secretary-dir RUNTIME --session SESSION --request-key gn-plan:JOB:N --add --input-json '
            '\'{"raw":"<用户原话>","task":{"title":"……","project":"<所属项目>","planned_date":"YYYY-MM-DD","timezone":"<档案时区>",'
            '"detail":"<用户给的条件，例如细胞量足够才做>"}}\' 保存一次。没有明确日期的进展不排期。其他内容按例外通道处理。2）有写入时，完成后重新运行 Today 读取（`results` 中带 --section today 的命令）；'
            '不要沿用写入之前的 Today 读取结果。3）先原样发布它返回的块（为 null 时没有）：这些是完成项以及已记录的部分完成/受阻事项的卡片。然后为卡片没有体现的结果'
            '（与任何待办都不对应的已完成事项、改动的日期或新排的步骤、受阻原因）加一个 ["p","……"] 块和注记。提到用户报告的每项结果，不添加建议或臆测进展。'),
  'anime': ('这是用户在追的番剧自上次晚间简报以来更新的剧集。读取成功且 `block` 不为 null 时，原样发布该块（行、标题、集数、日期和封面都由代码生成；'
            '不要翻译、调整顺序或增加行）。注记：用保存的语气写一句简短、活泼的话，邀请用户放松追番。`block` 为 null 时改为发布一个 ["p","……"] 块：'
            '用保存的语气写一句简短、活泼的话，说明自上次晚间简报以来没有新剧集，注记为 ""。读取失败时发布一个 ["p","……"] 块，只说明这次没能查到新剧集'
            '（不写原因，不承诺补充）。不得跳过本章节。'),
  'games': ('这是用户关注的 Steam 游戏中，此刻折扣达到其设定幅度的特惠。读取成功且 `block` 不为 null 时，原样发布该块（行、名称、折扣、价格、截止时间和封面'
            '都由代码生成；不要翻译、调整顺序或增加行）。注记：用保存的语气写一句简短、活泼的话说说这些特惠。`block` 为 null 时改为发布一个 ["p","……"] 块：'
            '用保存的语气写一句简短、活泼的话，说明今晚关注的游戏都没有达到设定折扣，注记为 ""。读取失败时发布一个 ["p","……"] 块，只说明这次没能查到游戏特惠'
            '（不写原因，不承诺补充）。不得跳过本章节。'),
  'stocks': ('这是用户保存的持仓在各市场最近一个已收盘交易日的当日盈亏（A 股是今天，美股通常是前一晚）。读取成功且 `block` 不为 null 时，原样发布该块'
             '（行、名称、股数和价格都由代码生成；不要翻译、调整顺序、取整或增加行）。注记：用保存的语气写一句简短的话，依据 `markets` 说出各市场当日结果，市场用 `market` 的名称'
             '（金额带 ¥ 或 $，再加百分比）；亏损时语气体贴，不要制造紧张。`not_found` 列出代码时，再加一个 ["p","……"] 块点名这些代码，说明没能查到它们的价格。'
             '读取失败时发布一个 ["p","……"] 块，只说明这次没能查到股票价格（不写原因，不承诺补充）。不得跳过本章节。'),
  'today_regenerating': '重新生成：不写入任务、不提问；沿用已保存的反馈。复制读取返回的块（为 null 时没有），提到用户报告的每项结果。',
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
