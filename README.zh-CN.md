<p align="center">
  <img src="assets/web/icons/gm.svg" width="64" alt="GoodMorning 太阳" />
</p>

<h1 align="center">GoodMorning</h1>

<p align="center">
  自托管的 AI 秘书：一份早报、一次晚间回顾、一份日程，<br />
  还有一个替你存着待办和灵感的对话。
</p>

<p align="center">
  <a href="README.md">English</a> · <strong>简体中文</strong>
</p>

![滚动浏览早报：带逐小时图表的天气、新闻、待办任务和提醒](assets/readme/morning-tour.gif)

## 它能做什么

你的计划散在日历、笔记应用和旧对话里，每天早上你都要亲手拼回去。
GoodMorning 把它们收在同一份记录里，再由一个 AI 智能体把这份记录
变成每天的两份简报：

- **早报：** 带逐小时图表的天气、过去 24 小时的新闻、今天的约定、
  今天的待办，以及需要你拿主意的事。
- **晚报：** 你完成了什么、还有什么没做完，以及明天。可选章节显示
  持仓盈亏、追番更新和游戏特惠。
- **日程：** 你的日历和带日期的待办，可以按周或按天看。
- **来信：** 每到周日晚上，一封回顾这一周的信：你完成的事、坚持的习惯、
  记下的灵感和下周的安排，留着随时回头翻看。
- **秘书：** 一个对话，用来保存待办、灵感、习惯和差事，
  遇到不清楚的地方会先问你。

它只呈现你保存的内容。它不会自己标记完成、挪动日期，也不会凭空造出
一条待办：没做完的事会留在原处，直到你说一声。

## 告诉你的秘书

![在秘书对话里输入一句话；回复存下了一条周期任务和一条灵感](assets/readme/secretary-chat.gif)

像对人说话那样写就行。一条消息可以装下好几件事，每件都会按对应的
类型存下来：

- 带日期、截止时间，或两者都有的**待办**。
- 像“每周二和周六”这样的**习惯**，可以带例外。
- **灵感**：在你决定采用之前，它一直只是灵感。
- 只是**提个醒**的事和**参考备注**，都不用打勾。
- **差事**，比如“每天早上看看这个价格”，只有结果正是你想听的时候，
  才会出现在简报里。

页面上浮动的提问按钮能在任何页面打开同一个对话。你可以附加文件和图片。

## 早报

![天气卡片，带逐小时气温、降雨和空气质量图表](assets/readme/weather.png)

<table>
  <tr>
    <td width="50%" valign="top"><a href="assets/readme/news.png"><img src="assets/readme/news.png" alt="按分类分组的新闻卡片，每条都有摘要和来源链接" /></a></td>
    <td width="50%" valign="top"><a href="assets/readme/tasks.png"><img src="assets/readme/tasks.png" alt="按日期和项目分组的待办，标出截止时间，可选的事单独放" /></a></td>
  </tr>
  <tr>
    <td align="center">过去 24 小时的新闻，附来源，已经看过的会跳过。</td>
    <td align="center">待办按日期和项目分组，标出截止时间，可选的事单独放。</td>
  </tr>
</table>

章节写到哪里就显示到哪里，所以整份简报还没写完，你就能开始读。
同步日历（一个公开的 `.ics` 链接）里的变更会自动应用，提醒会把每一条
各说一次。

## 晚报

<table>
  <tr>
    <td width="50%" valign="top"><a href="assets/readme/evening.png"><img src="assets/readme/evening.png" alt="星空配色下的晚报，显示一条待办的部分进展" /></a></td>
    <td width="50%" valign="top"><a href="assets/readme/stocks.png"><img src="assets/readme/stocks.png" alt="持仓盈亏章节，含 A 股和美股持仓、当日盈亏和总计" /></a></td>
  </tr>
</table>

晚报写完后，一段简短的回顾会逐条过一遍今天到期的待办，再问有没有
提前完成的事。只有你的回答会改动待办，猜测不会。

## 日程

![周视图，约定在上、带日期的待办在下，其中有一个时间还没确定的看牙预约](assets/readme/weekly-schedule.png)

日程页直接读取你保存的记录：不调用 AI，也不生成计划。时间还不确定的
约定会照实标出来。

## 外观

![同一个页面在曙光、晨空、草方块、星空、城市灯光和野餐下的样子](assets/readme/color-schemes.gif)

选**柔和**或**像素**样式，再分别选日间配色和夜间配色，每台设备各自
保存。你可以给秘书挑形象、起名字，决定它怎么跟你说话。整个网站都有
英语和简体中文。

## 在手机上

<table>
  <tr>
    <td align="center" valign="top"><img src="assets/readme/morning-mobile.png" width="240" alt="手机尺寸屏幕上的早报" /></td>
    <td align="center" valign="top"><img src="assets/readme/secretary-mobile.png" width="240" alt="手机尺寸屏幕上的秘书对话" /></td>
  </tr>
</table>

网站在手机上也能用。[Android 应用](docs/android-app.md)
（beta，[发布版本](https://github.com/S-Sebb/GoodMorning/releases)）另外提供：

- **小组件：** 今天、这一周、简报、新闻、天气、秘书对话，还有一张
  速记便签，之后可以让秘书帮你归类。
- **通知**：简报准备好、回复写完、秘书需要你回答，或者有安排即将
  开始时都能收到。早报和晚报也各有提醒：到了你选定的时间，如果当天
  那份还没准备好，就会提醒你。浏览器也能收到。

## 开始使用

GoodMorning 还在 **beta**。它不是独立的聊天机器人，需要：

- **Linux**，以及 **Python 3.14+**，
- 一个能访问模型的 **[OpenCode](https://opencode.ai)/OpenChamber** 智能体
  （英文请求用 Muse Spark，中文请求用 DeepSeek V4.1 Flash），
- **Node.js 22.18+**，只在可选的项目访问时用。

1. 按[部署指南](docs/deployment.md)安装 `goodmorning` 技能。
   浏览器查看器见[浏览器指南](docs/browser-delivery.md)；
   公开托管还需要完成[安全设置](docs/website-security.md)。
2. 在浏览器里打开**初始化**。秘书会问你的偏好、位置和集成，
   可选项都可以先放着。
3. 在早报或晚报页面准备一份简报，或者直接开始对话。

天气、模型估算的空气质量以及新闻都需要访问外部 HTTPS，但不需要
API 密钥。

## 隐私

- 个人记录存放在你自己的运行目录里，不在这份源码树中。
- 托管部署支持 HTTPS 登录、加密存储和彼此独立的账户。
- 自托管也挡不住 AI 服务提供商看到请求，加密也不会对服务器的管理员
  隐藏运行中的数据。详见[安全边界](docs/website-security.md)。

## 更多

[事项类型与时间](docs/item-taxonomy.md) ·
[日程](docs/weekly-schedule.md) ·
[每周来信](docs/weekly-letters.md) ·
[网站对话](docs/browser-chat.md) ·
[项目访问](docs/project-access.md) ·
[源码结构](docs/project-structure.md) ·
[问题反馈](https://github.com/S-Sebb/GoodMorning/issues)

截图使用虚构数据，由[演示工具](tests/browser/readme_demo.py)生成，
没有调用任何模型。

## 许可证

[MIT](LICENSE)。随项目提供的中继代码（[许可证](vendor/openchamber-relay/LICENSE)）
和字体（[正文字体](assets/web/fonts/OFL.txt)、
[像素字体](assets/web/fonts/pixel-fonts-OFL.txt)）保留各自的许可证；
主题图片另有[素材来源说明](docs/theme-asset-credits.md)。
