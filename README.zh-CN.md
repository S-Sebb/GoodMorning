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

![晨间简报，包含个人桌面、每日归档和天气卡片](assets/readme/morning.png)

GoodMorning 将零散的日常信息整理成一个安静、易读的空间，让你从容开始一天。
查看天气，阅读附有来源的新闻，了解日历安排，为重要的工作留出空间。
到了晚上，回顾实际发生的事情，再看看明天的安排——不会把尚未完成的工作当作已经完成。

在两次简报之间，你的秘书也随时可以帮你理清思路、记下待办，或在灵感消失前将它留住。
GoodMorning 围绕 **OpenCode 和 OpenChamber** 构建，将智能体辅助的工作流程
与可自行托管的浏览器界面结合起来。

## 与 GoodMorning 度过一天

**早晨 · 找到方向。** 本地天气与空气质量、附有来源链接的新闻摘要、预约和当天的重要安排，
以及正在推进的项目中必做与可选的下一步，避免重复列出任务。
各个版块准备好后会陆续呈现，不必等整份简报生成完毕，就能开始阅读。

**晚上 · 放下一天。** 回顾你反馈的进展，让未完成的工作保持可见，并查看明天的日程。
任务是否完成由你确认，而不是由 AI 猜测。

**秘书 · 留一点空间思考。** 一起梳理计划，用你自己的话保存待办，通过 Eureka 记录灵感，
也可以重新调整偏好，而不重置已有记录。
对话支持文件附件、粘贴图片、点击放大的图片预览，以及保存历史记录。

<table>
  <tr>
    <td width="50%" valign="top"><img src="assets/readme/evening.png" alt="夜间配色的晚间简报，展示已完成和部分完成的进展" /></td>
    <td width="50%" valign="top"><img src="assets/readme/secretary.png" alt="在个人桌面界面中与秘书 Aria 对话，规划专注工作" /></td>
  </tr>
  <tr>
    <td align="center"><em>为一天画上清晰的句号。</em></td>
    <td align="center"><em>安放计划与灵感的地方。</em></td>
  </tr>
</table>

<sub>真实界面，虚构的演示数据。以上天气、计划和对话仅为示例，不是个人记录或实时报告。</sub>

## 简报一览

从天气预报到下一段专注时间，每件事都有自己的位置。
以下细节截图使用虚构数据；点击截图即可查看原图。

![天气详情，包含气温、降雨概率、空气质量和实用建议](assets/readme/weather.png)

<table>
  <tr>
    <td width="50%" valign="top"><a href="assets/readme/news.png"><img src="assets/readme/news.png" alt="附有来源链接的新闻卡片，按 AI 与科研、世界和英国新闻分类" /></a></td>
    <td width="50%" valign="top"><a href="assets/readme/schedule.png"><img src="assets/readme/schedule.png" alt="每日安排，包含预约时间、地点、准备事项，以及不限定时间的灵活工作" /></a></td>
  </tr>
  <tr>
    <td align="center"><strong>新闻，也有背景。</strong><br /><em>分类、摘要、局限与来源，一目了然。</em></td>
    <td align="center"><strong>是日程，不只是清单。</strong><br /><em>固定预约与灵活工作，清楚区分。</em></td>
  </tr>
  <tr>
    <td width="50%" valign="top"><a href="assets/readme/priorities.png"><img src="assets/readme/priorities.png" alt="必做与可选版块，将必要工作和可选想法分开" /></a></td>
    <td width="50%" valign="top"><a href="assets/readme/tomorrow.png"><img src="assets/readme/tomorrow.png" alt="夜间配色的晚间简报，展示明天的预约、准备事项和灵活计划" /></a></td>
  </tr>
  <tr>
    <td align="center"><strong>给重点留出空间。</strong><br /><em>分清必须做的事与可以尝试的事。</em></td>
    <td align="center"><strong>让明天更从容。</strong><br /><em>结束今天之前，先看看明天的计划。</em></td>
  </tr>
</table>

## 用心设计

- **专属于你，而非千篇一律。** 自定义秘书的名字、语气、头像和外观。
  网站支持英语和简体中文。
- **阅读更舒适。** 独立的日间与夜间配色、适合手机的布局、可点击的来源链接、
  版块导航，以及减少动态效果的支持。
- **保留上下文，不堆积杂乱。** 已保存的简报、浏览器中的七日归档，
  以及持久保存的任务和灵感记录，让有用的信息随手可查。
- **由你掌控。** 生成内容需要你主动发起。提问和权限请求始终可见；
  修改日历或写入项目需要授权。
- **属于自己的空间。** 个人记录与源代码分开存放。多用户部署支持
  带身份验证的 HTTPS 访问、加密存储，以及彼此隔离的智能体账户。

## 开始使用

GoodMorning 目前处于 **Beta 测试阶段**，面向 Linux，需使用 Python 3.9+ 和
OpenCode/OpenChamber 智能体。它不是独立的聊天机器人，也不是无人值守的每日自动服务。

先阅读[部署指南](docs/deployment.md)，再按照[引导设置](docs/initialization.md)完成配置。
你可以使用浏览器页面，也可以用自然语言请求已安装的技能生成晨间简报、进行晚间回顾、
记录待办或捕捉灵感。可选的项目访问功能需要 Node.js 22.18+。

部署为在线服务时，请阅读[安全与隐私边界](docs/website-security.md)。
自行托管并不意味着你选择的 AI 服务提供商无法看到请求。

欢迎通过 [GitHub Issues](https://github.com/S-Sebb/GoodMorning/issues)
分享想法、反馈问题，或提出有针对性的改进。

## 许可证

GoodMorning 使用 [MIT 许可证](LICENSE)。
随项目提供的[中继代码](vendor/openchamber-relay/LICENSE)和
[字体](assets/web/fonts/OFL.txt)保留各自的许可证声明。

---

<p align="center"><em>少一点喧嚣，多一点属于你的时间。</em></p>
