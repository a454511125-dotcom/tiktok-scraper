# TikTok 视频数据采集工具

基于反检测浏览器的 TikTok 视频与评论元数据采集工具。通过 Web 界面操作，支持批量账号采集、评论与楼中楼回复采集、断点续传、实时进度显示。

## 采集原理

工具启动一个经过反检测处理的 Chromium 浏览器（[CloakBrowser](https://github.com/CloakHQ/CloakBrowser)），模拟真实用户访问 TikTok 账号主页并滚动页面。在滚动过程中，自动拦截 TikTok 内部 API 返回的视频数据，提取元数据后实时写入 CSV 文件。

每个账号分两个方向采集：
- **最新 → 最旧**：从最新视频开始向下滚动
- **最旧 → 最新**：切换到"Oldest"排序标签，从最早视频开始

两个方向合并去重后可覆盖账号的全部历史视频。

评论采集则对某账号已采集到的每条视频，打开视频页滚动评论区、展开楼中楼回复，同样通过拦截接口响应获取数据，不设数量上限。

## 采集字段

### 视频（`data/{账号}_full.csv`）

| 字段 | 说明 |
|------|------|
| web_video_id | 视频 ID |
| desc | 视频描述文本（截取前 500 字符） |
| create_time | 发布时间，UTC（YYYY-MM-DD HH:MM:SS） |
| create_timestamp | 发布时间（Unix 时间戳） |
| video_duration | 视频时长（秒） |
| video_url | 视频页面链接 |
| author_id | 作者 ID |
| author_name | 作者用户名 |
| author_nickname | 作者昵称 |
| digg_count | 点赞数 |
| share_count | 分享数 |
| comment_count | 评论数 |
| play_count | 播放数 |
| collect_count | 收藏数 |
| scraped_at | 采集时间，UTC（YYYY-MM-DD HH:MM:SS） |

### 评论（`data/{账号}_comments.csv`）

| 字段 | 说明 |
|------|------|
| comment_id | 评论 ID |
| video_id | 归属视频 ID，对应视频 CSV 的 web_video_id |
| reply_to_comment_id | 楼中楼回复的父评论 ID；为空表示一级评论 |
| text | 评论原文 |
| create_time | 发布时间，UTC（YYYY-MM-DD HH:MM:SS） |
| create_timestamp | 发布时间（Unix 时间戳） |
| digg_count | 评论点赞数 |
| reply_count | 该评论收到的回复数 |
| comment_language | TikTok 标注的评论语言 |
| is_author_liked | 视频作者是否点赞了该评论 |
| user_id | 评论者用户 ID（原始 ID，未脱敏） |
| user_unique_id | 评论者用户名 |
| user_nickname | 评论者昵称 |
| video_url | 视频页面链接 |
| scraped_at | 采集时间，UTC（YYYY-MM-DD HH:MM:SS） |

> **时区说明**：所有时间字段统一为 UTC。2026-07-02 之前采集的历史视频数据曾使用本机时区（UTC+8）记录 `create_time`，已在本次更新中自动迁移为 UTC；`scraped_at` 字段为本次同步新增，历史行留空（采集时未记录）。

> **评论采集提示**：字段解析已用真实视频核验通过（含楼中楼），单条视频从打开页面到评论区加载完成最长可能需要约 40 秒（TikTok 页面 hydrate 较慢），属正常现象，不是卡死。

## 环境要求

- **操作系统**：Windows 10/11（64 位）
- **Python**：3.10 或更高版本
  - 下载地址：https://www.python.org/downloads/
  - 安装时务必勾选 **Add Python to PATH**
- **网络**：能正常访问 TikTok（首次运行需下载约 200MB 浏览器文件）

## 快速开始

### 1. 启动

双击 `start.bat`，首次运行会自动完成：
- 创建 Python 虚拟环境
- 安装所有依赖
- 下载反检测浏览器

完成后自动启动 Web 服务，终端会显示：

```
浏览器访问 http://localhost:8000
```

### 2. 登录 TikTok

打开 http://localhost:8000 ，点击「打开登录浏览器」，会弹出一个浏览器窗口。在窗口中手动登录 TikTok 账号，登录成功后回到网页点击「登录完成」。

登录状态保存在 `_browser_profile/` 目录中，下次使用无需重复登录。

### 3. 采集数据

在文本框中输入要采集的 TikTok 账号，每行一个，支持以下格式：

```
https://www.tiktok.com/@cgtneurope
https://www.tiktok.com/t/ZPxxxxxxxx/
https://vm.tiktok.com/ZMxxxxxxxx/
@cgtnofficial
chinadailyofficial
```

点击「开始采集」，工具会依次采集每个账号的全部视频数据。页面实时显示采集进度。

### 4. 下载数据

采集完成后，在页面底部的「数据文件」区域点击「下载」获取 CSV 文件。文件也保存在项目的 `data/` 目录中。

### 5. 采集评论（含楼中楼回复）

完成某账号的视频采集后，该账号会出现在「评论采集」区域的账号列表中。勾选一个或多个账号，点击「开始采集评论」。

工具会对账号下的**全部视频**逐条打开视频页，采集全部一级评论和楼中楼回复，不设数量上限。因此耗时较长：一条评论数百的视频约需 1-2 分钟，热门视频（评论上万）可能需要十几分钟；账号视频总数越多，总耗时越长，大账号建议分批勾选、分次运行。中断后重新开始会自动跳过已采集完成的视频。

## 项目结构

```
tiktok-scraper/
├── start.bat              # 一键启动脚本
├── server.py              # Web 服务端（FastAPI）
├── scraper.py             # 视频采集核心逻辑 + 评论采集入口
├── comment_scraper.py     # 评论/楼中楼解析与增量写入
├── timeutil.py            # UTC 时间格式化工具
├── index.html             # Web 前端界面
├── cloakbrowser/          # 内置反检测浏览器引擎
├── data/                  # 采集数据输出目录
├── scripts/               # 探索性/一次性脚本（非核心工具）
├── _browser_profile/      # 浏览器登录状态（运行时生成）
├── requirements.txt       # Python 依赖
├── pyproject.toml         # 项目配置
└── README.md
```

## 常见问题

**Q: 采集中途浏览器崩溃怎么办？**

已采集的数据实时保存在 CSV 文件中，不会丢失。重新点击「开始采集」，工具会自动跳过已有数据，从断点处继续。评论采集同理，按视频粒度记录进度。

**Q: 能采集到多少条数据？**

取决于账号的视频总量。TikTok 对每次页面加载能吐出的视频量有内部限额（实测约 1100-1350 条，且随时间波动），工具会在每个方向上自动多轮刷新重试，直到连续两轮都没有新数据为止。对于发布量数千条的大账号，一次运行通常能覆盖大部分历史；如果仍有缺口（可对照账号主页显示的视频总数判断），换个时间段重新运行同一账号即可继续推进——已采数据会自动去重，不会重复。

**Q: 登录状态过期怎么办？**

如果采集时遇到数据异常或无法获取数据，点击「重新登录」重复登录流程即可。注意：采集进行中无法重新登录，需先停止采集。

**Q: 能从局域网内的其他设备访问吗？**

不能，服务默认只绑定本机 `127.0.0.1`，仅本机浏览器可访问，避免局域网内他人误操作或下载数据。

**Q: 能同时采集多个账号吗？**

工具按队列依次采集输入的所有账号。由于共用一个浏览器实例，不支持同时并行采集多个账号。

**Q: 如何在其他电脑上使用？**

将整个 `tiktok-scraper` 文件夹复制到目标电脑，确保已安装 Python 3.10+，双击 `start.bat` 即可。首次运行会自动安装依赖。`_browser_profile/` 目录中的登录状态不可跨机器迁移，需要在新电脑上重新登录。

## 许可协议

本工具采集逻辑为自由使用。内置的 CloakBrowser 遵循其 [MIT 许可证](LICENSE-CloakBrowser) 和 [二进制许可证](BINARY-LICENSE-CloakBrowser.md)。
