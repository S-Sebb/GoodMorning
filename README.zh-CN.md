<p align="center">
  <img src="assets/web/icons/gm.svg" width="64" alt="GoodMorning 太阳图标" />
</p>

<h1 align="center">GoodMorning</h1>

<p align="center">
  <strong>从容开启一天，清晰收尾，留一点空间思考。</strong><br />
  你的专属 AI 秘书，陪你整理一天中的计划、见闻与灵感。
</p>

<p align="center">
  <a href="README.md">English</a> · <strong>简体中文</strong>
</p>

<p align="center">
  <a href="#与-goodmorning-度过一天">探索</a> ·
  <a href="#简报一览">界面截图</a> ·
  <a href="#开始使用">开始使用</a> ·
  <a href="docs/deployment.md">文档</a> ·
  <a href="https://github.com/S-Sebb/GoodMorning/issues">反馈</a>
</p>

![曙光主题的晨间简报，包含山谷背景、个人桌面、每日归档和天气卡片](assets/readme/morning.png)

GoodMorning 将天气、新闻、预约、待办与灵感，整理到一个安静的空间里。
早晨读一份简报，白天随时查看一周的计划，晚上再如实回顾今天发生的事情。

在两次简报之间，你的秘书可以帮你理清思路、记下待办，或在灵感消失前将它留住。
GoodMorning 围绕 **OpenCode 和 OpenChamber** 构建，将个人 AI 工作流程
与可自行托管的浏览器界面结合起来。**早报、晚报、日程、秘书**四个标签页，
让一天中需要的信息各有归处，也随手可查。

## 与 GoodMorning 度过一天

**早晨 · 找到方向。** 天气、新闻、日程、待办、提醒，以熟悉的顺序展开：
本地天气与空气质量、昨天附有来源的新闻、接下来的预约、已保存的行动，以及需要你决定的事情。
待办按工作日期和项目分组，标题清晰具体，必要工作与可选事项也有区分。
各个版块准备好后会陆续呈现，不必等整份简报生成完毕，就能开始阅读。

**晚上 · 放下一天。** 记录完成的工作、部分进展和遇到的阻碍，再看看明天的预约与已约定的待办。
未完成的工作仍然可见，但不会悄悄被移到另一天。任务是否完成由你确认，而不是由 AI 猜测。

**日程 · 一周安排，一目了然。** 实时的周一至周日视图，上方是预约，下方是按日期安排的待办，
突出显示今天，并可前后浏览三周。周期任务、已反馈的进展，以及日期已确认但时刻待定的预约，
都有自己的位置。保存的变更会自动刷新，无需再次调用 AI；这里展示已有记录，而不是生成新的周计划。
详见[每周日程指南](docs/weekly-schedule.md)。

**秘书 · 留一点空间思考。** 一段对话就够了：存个待办、记条灵感、安排这一周，或者改改偏好。
新用户完成设置前只会看到初始化；设置完成后，秘书就是唯一的聊天入口。
每次回复都会说明存成了待办还是灵感；拿不准你是想记下来还是马上去做时，秘书会先问你。
文件附件、粘贴图片、Markdown 回复与历史对话，让细节不易丢失。
提问、已提交的回答和已确认的变更，都有清晰、柔和高亮的卡片呈现。

<table>
  <tr>
    <td width="50%" valign="top"><img src="assets/readme/evening.png" alt="星空主题的晚间简报，回顾已反馈的进展" /></td>
    <td width="50%" valign="top"><img src="assets/readme/secretary.png" alt="暖色主题中与秘书 Aria 对话，展示已保存的待办与灵感卡片，以及高亮的提问和回答" /></td>
  </tr>
  <tr>
    <td align="center"><em>为一天画上清晰的句号。</em></td>
    <td align="center"><em>安放计划与灵感的地方。</em></td>
  </tr>
</table>

<sub>当前界面，虚构的演示数据。天气、新闻、计划和对话仅为示例，不是个人记录或实时报告；制作截图没有调用 AI 模型或外部集成。</sub>

## 简报一览

从天气预报到下一步行动，每件事都有自己的位置。
以下细节截图使用当前布局和虚构数据；点击即可查看原图。
**待办**按日期和项目整理行动，**提醒**则单独呈现待审核的内容与需要决定的事情。

![天气详情，包含气温、降雨概率、空气质量和实用建议](assets/readme/weather.png)

<table>
  <tr>
    <td width="50%" valign="top"><a href="assets/readme/news.png"><img src="assets/readme/news.png" alt="附有来源链接的新闻卡片，按 AI 与科研、世界和英国新闻分类" /></a></td>
    <td width="50%" valign="top"><a href="assets/readme/schedule.png"><img src="assets/readme/schedule.png" alt="接下来的预约，包含时间、地点、准备事项，以及标记为时刻待定的牙医预约" /></a></td>
  </tr>
  <tr>
    <td align="center"><strong>新闻，也有背景。</strong><br /><em>分类、摘要、局限与来源，一目了然。</em></td>
    <td align="center"><strong>是日程，不只是清单。</strong><br /><em>时间、准备事项，还有如实保留的未知。</em></td>
  </tr>
  <tr>
    <td width="50%" valign="top"><a href="assets/readme/priorities.png"><img src="assets/readme/priorities.png" alt="待办按日期与项目分组，显示 Atlas 项目的共同截止日期及可选的个人事项" /></a></td>
    <td width="50%" valign="top"><a href="assets/readme/tomorrow.png"><img src="assets/readme/tomorrow.png" alt="星空主题的晚间日程，展示接下来的设计评审与时刻尚未确认的牙医预约" /></a></td>
  </tr>
  <tr>
    <td align="center"><strong>给重点留出空间。</strong><br /><em>按日期与项目分组，不重复堆放细节。</em></td>
    <td align="center"><strong>让明天更从容。</strong><br /><em>提前看看安排，不悄悄挪动未完成的工作。</em></td>
  </tr>
</table>

**知道哪里需要你。** 待审核的邀请会点明与哪条已确认的预约重叠，
让你带着具体信息做决定，而不是只看到一条含糊的提醒。

![提醒点明待审核的规划工作坊与已确认的设计评审之间的时间冲突](assets/readme/reminders.png)

**这一周，随手可查。** 上方是预约，下方是按日期安排的待办，已反馈的进展也留在视图里。
每周日程读取已保存的计划，不会请 AI 替你编排时间。

![暖色主题的每周日程，展示预约、时刻待定的牙医安排、项目待办、部分进展与已完成事项](assets/readme/weekly-schedule.png)

## 添一点风景

还是那个安静的工作空间，窗外可以换一片风景。晨空为白天添上云朵与飞鸟，
星空让夜晚多一点安静。在手机上，阅读和消息输入也各有位置。

<table>
  <tr>
    <td width="50%" valign="top"><a href="assets/readme/morning-sky.png"><img src="assets/readme/morning-sky.png" alt="晨空主题，以真实云层照片与飞鸟作为晨间简报背景" /></a></td>
    <td width="50%" valign="top"><a href="assets/readme/evening.png"><img src="assets/readme/evening.png" alt="星空主题，以深色夜空、点点星光与弯月作为晚间简报背景" /></a></td>
  </tr>
  <tr>
    <td align="center"><strong>晨空。</strong><br /><em>看一朵云，缓一口气。</em></td>
    <td align="center"><strong>星空。</strong><br /><em>一天结束，留一片安静的夜空。</em></td>
  </tr>
  <tr>
    <td align="center" valign="top"><a href="assets/readme/morning-mobile.png"><img src="assets/readme/morning-mobile.png" width="240" alt="手机尺寸的晨空主题简报，带紧凑日期导航与版块按钮" /></a></td>
    <td align="center" valign="top"><a href="assets/readme/secretary-mobile.png"><img src="assets/readme/secretary-mobile.png" width="240" alt="手机尺寸的秘书对话，展示待办与灵感卡片，底部保留消息输入框" /></a></td>
  </tr>
  <tr>
    <td align="center"><em>小屏幕，也能好好读早报。</em></td>
    <td align="center"><em>聊着聊着，也有地方接着说。</em></td>
  </tr>
</table>

<sub><a href="tests/browser/readme_demo.py">演示截图工具</a>使用隔离的虚构记录、真实的本地查看器与模拟对话，重现这些界面。</sub>

## 计划如实，心里有数

- **预约不是待办。** 需要出席或预留时间的安排归入日程，要完成的行动归入待办；
  尚未决定要做的事，仍然只是灵感。截止日期不会自动占用某个工作日，日历空白也不代表你有空。
- **记住节奏，而不是堆积欠账。** 可以保存已约定的每周、每隔若干天或指定日期的任务规则，
  包括已确认的例外与受支持的触发条件。完成情况按实际发生的日期记录，不会打乱原有周期。
  这些提醒出现在简报中，并非无人值守的推送通知服务。
- **提醒有缘由。** 到期的审核、更新或取消的日历事项，以及尚未解决的决定，与普通工作分开呈现。
  待审核的日历记录会点明时间重叠的预约，让你知道哪里需要留意。
- **简报呈现计划，不替你作主。** 生成或重新生成简报，不会创建任务、分配日期或标记完成。
  含糊的日程请求会先澄清再保存；导入的日历内容须经审核才成为已确认安排，写入项目也需要授权。

[事项与时间规则](docs/item-taxonomy.md)详细说明了这些边界。

## 用心设计

- **专属于你，而非千篇一律。** 自定义秘书的名字、语气和头像。
  网站各处支持英语和简体中文；切换界面语言不会改写已有记录或之前的回复。
- **选一片喜欢的风景。** 日间可选经典、暖色、晨空或曙光，夜间可选经典、星空、
  城市灯光或午夜紫。日间与夜间独立选择，按账号保存。云朵与飞鸟、山谷与溪流，
  或轻轻闪烁的星空、映着城市灯光的港湾，为页面添一点氛围，主题图片无需请求第三方服务。
- **手机上也舒适。** 自适应布局、随输入扩展的消息框、点击放大的图片、版块导航、
  阅读进度与减少动态效果的支持，让阅读和对话始终处在中心。
- **保留上下文，不堆积杂乱。** 已保存的简报、七日归档选择器、持久保存的待办与灵感，
  以及历史对话，让有用的信息随手可查。七日范围只是浏览窗口，不是记录删除期限。
- **进度始终看得见。** 小书桌活动窗口在不同标签页中显示进行中、排队中和等待回答的工作，
  并带你返回原来的页面。刷新会恢复同一份简报或对话；秘书工作时，也能发送后续消息调整方向。
  待回答的问题和授权请求会保留，直到你回应。
- **按语言自动选择模型。** 英文请求使用 Muse Spark 1.3 Contributor XHigh，中文请求使用
  DeepSeek V4.1 Flash High（付费档），无需模型选择器。运行中的请求保留原模型。
  站内更新说明告诉你有哪些变化，已打开的页面不会自行刷新而丢掉未发送的草稿。
- **属于自己的空间。** 个人记录与公开源码分开存放。在线部署支持带身份验证的 HTTPS、
  加密存储和彼此独立的智能体账户。私人消息不会保存到浏览器本地存储中。

## 开始使用

GoodMorning 目前处于 **Beta 测试阶段**，面向 **Linux**，需要 **Python 3.14+** 和
**OpenCode/OpenChamber 智能体**。
可选的本地或已配对远程项目访问需要 **Node.js 22.18+**。
它不是独立的聊天机器人，也不是无人值守的每日自动服务。

1. **先安顿好空间。** 按照[手动部署指南](docs/deployment.md)安装 `goodmorning` 技能。
   [浏览器指南](docs/browser-delivery.md)介绍仅监听本机回环地址的查看器；
   公开的 HTTPS 服务还需要单独完成[安全与账户配置](docs/website-security.md)。
   仅打开这个仓库，不会安装技能，也不会自动准备好可用账户。
2. **认识你的秘书。** 在浏览器中打开初始化，或请已安装的技能帮助设置。
   [引导初始化](docs/initialization.md)会保存你确认的偏好与权限，可选集成可以保留为待验证。
    以后可以请秘书逐项回顾设置，而不重置已有记录。
3. **准备好了，再开始。** 在早报或晚报页面发起简报，查看日程，或在秘书页面开始对话。
   使用已安装的技能时，也可以用自然语言请求晨间简报、晚间回顾、记录待办或捕捉灵感。
   `/gm`、`/gn`、`/secretary`、`/todo` 和 `/eureka` 是工作流程名称，并非单独安装的斜杠命令。

天气和新闻需要访问外部 HTTPS 服务。常规天气、模型估算的空气质量，以及 RSS/Hacker News
采集无需额外的 API 密钥。新闻默认覆盖**所保存时区中的昨天**，包括 AI、世界及所选国家的新闻；
当天更新需要主动选择启用。内容覆盖与服务可用性可能不完整，附有来源也不等于经过独立事实核查。

自行托管并不意味着你选择的 AI 服务提供商无法看到请求，加密存储也不会对可信的服务器管理员隐藏
运行中的数据。托管个人信息前，请先阅读[安全与隐私边界](docs/website-security.md)。

想进一步了解，可以查看[网站对话](docs/browser-chat.md)、[每周日程](docs/weekly-schedule.md)、
[经授权的项目访问](docs/project-access.md)和[源码结构](docs/project-structure.md)。
部署验证使用隔离的虚构记录，不使用你的个人运行目录。

欢迎通过 [GitHub Issues](https://github.com/S-Sebb/GoodMorning/issues)
分享想法、反馈问题，或提出有针对性的改进。

## 许可证

GoodMorning 使用 [MIT 许可证](LICENSE)。
随项目提供的[中继代码](vendor/openchamber-relay/LICENSE)和
[字体](assets/web/fonts/OFL.txt)保留各自的许可证声明。
主题图片另有[素材来源说明](docs/theme-asset-credits.md)。

---

<p align="center"><em>少一点喧嚣，多一点属于你的时间。</em></p>
