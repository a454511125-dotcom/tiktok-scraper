# tiktok-scraper 项目约定

TikTok 账号视频与评论元数据采集工具。Web 界面操作，浏览器自动化基于 CloakBrowser（反检测 Chromium）+ Playwright 网络拦截，不直接调用 TikTok 私有 API、不破解签名。

## 架构

```
server.py            FastAPI Web 服务，WebSocket 广播采集进度
scraper.py           视频采集核心逻辑（TikTokScraper 类）+ 评论采集入口
comment_scraper.py   评论/楼中楼解析与增量写入（被 scraper.py 引用）
timeutil.py          UTC 时间格式化工具，scraper.py 与 comment_scraper.py 共用
index.html           单文件前端，无构建步骤
cloakbrowser/        内置反检测浏览器引擎（第三方，勿改动）
scripts/             一次性/探索性脚本（候选账号核查等），非核心工具的一部分
```

`utc_str()`/`now_utc_str()` 放在独立的 `timeutil.py`，是为了避免 `scraper.py`（依赖 `comment_scraper` 的采集函数）和 `comment_scraper.py`（需要时间格式化函数）互相 import 形成循环导入。新增跨这两个模块共用的工具函数时同理，放 `timeutil.py`，不要让二者互相依赖对方。

采集原理：真实浏览器打开页面并滚动 → 触发 TikTok 内部接口（`/api/post/item_list/` 视频列表、`/api/comment/list/` 评论、`/api/comment/list/reply/` 楼中楼）→ 拦截响应体 → 解析写入 CSV。滚动即分页，不手工拼接 cursor 参数。

## 环境与运行

本项目使用 **系统 venv + pip**（`start.bat` 自动创建 `.venv` 并从 `requirements.txt` 安装），不是 uv。这是为了让非技术同事能双击 `start.bat` 一键运行；不要改成 uv 工作流。

- 手动运行：`.venv\Scripts\python.exe server.py`
- 语法检查：`.venv\Scripts\python.exe -m py_compile <file>.py`
- 无自动化测试套件；改动后用 py_compile + 手工冒烟测试（起服务、curl 关键端点）验证

### 改动采集/进度逻辑时的必测清单

2026-07-02 的交付审查中，一个 Critical 缺陷恰好藏在"测过自然完成的续传、没测停止时机"的缝隙里。此后凡是改动 CSV 写入、进度文件或停止逻辑，必须覆盖：

1. **中途停止再续传**：采集到一半点停止 → 进度文件不得包含未采完的视频 → 重跑应重采该视频且无重复数据（去重兜底）
2. **失败不标记完成**：采集出错/评论区打不开的视频不得写入 done_ids，续传时应重试
3. **进程强杀后续传**：直接杀进程 → 已 flush 的 CSV 行保留 → 重跑从断点继续

### Playwright 线程约束

Playwright sync API 与创建它的线程绑定（greenlet），跨线程调用抛 `cannot switch to a different thread` 且症状可能被 try/except 吞掉（表现为 0 cookies、浏览器进程泄漏）。规则：**同一个浏览器实例的所有操作必须在同一线程**。登录浏览器的开/关经 `server.py` 的单 worker `login_executor` 串行执行；采集浏览器的 launch 和 close 都在各自的采集线程内完成，不要把其中一半挪到别的线程。

## 数据字段与时区约定

- **所有时间字段一律 UTC**，格式 `YYYY-MM-DD HH:MM:SS`：`create_time`、`scraped_at`。写入统一用 `timeutil.utc_str()` / `timeutil.now_utc_str()`，不要用 `datetime.fromtimestamp()`（本机时区）或已弃用的 `utcfromtimestamp()`。
- 视频 CSV（`data/{account}_full.csv`）：`CSV_FIELDS`（scraper.py）定义，含 `scraped_at`。
- 评论 CSV（`data/{account}_comments.csv`）：`COMMENT_CSV_FIELDS`（comment_scraper.py）定义，按 `comment_id` 去重；`reply_to_comment_id` 为空表示一级评论，非空表示楼中楼回复的父评论 ID。
- 两类 CSV 都按主键增量去重续传（视频用 `web_video_id`，评论用 `comment_id`），断点续传是核心设计约束，改动写入逻辑时不能破坏这一点。
- **schema 变更需要走迁移**：`IncrementalCSV._migrate_schema_if_needed()` 会在打开旧文件时自动补齐缺失字段、重算 `create_time`。新增字段到 `CSV_FIELDS` 后要同步检查这个迁移函数是否需要跟着改，否则旧文件会长期缺字段。

## TikTok 视频列表分页预算（2026-07-02 插桩实测）

- TikTok 对**每次页面加载**的视频流有"吐出量预算"：实测当天约 70-85 批（每批 16 条）≈ 1100-1350 条，从列表头部从零计数、重复项也消耗预算；耗尽后**即使响应里 hasMore=True 也不再返回数据**。预算大小随时间波动（6 月曾单会话吐出近 5000 条），与浏览器无关。
- **page.reload() 即可重置预算**，无需新标签页或重启浏览器——这是 `_scrape_one` 里"每个方向做多轮 reload 循环"的依据。深度回填能否触底取决于预算波动，同一天多次重试可能都碰不到更深处，换个时段再跑往往有效。
- 停止判据必须基于"**连续 N 轮无接口响应**"而非"连续 N 轮无新数据"：断点续传要先快进跳过成百上千条已采集的重复项，期间长时间没有新增但响应持续，按"无新数据"判停会在到达前沿之前就放弃（这正是 chinanewsservice 空洞多次重跑难以推进的原因之一）。
- "最旧"排序按钮与评论 tab 同样受 hydrate 延迟影响（可达 16 秒），`_click_oldest()` 内置轮询等待并返回 bool；点击失败时该方向会静默按最新排序走，浪费一整轮预算，所以失败必须记日志。
- 账号声称的 `videoCount`（页面脚本里可提取）与实采数量的差值是判断"还有多少没采到"的依据；注意大账号可能有真实停更期，时间轴上的空洞不全是漏采（chinanewsservice 在 2020-2022 有多段 1-5 个月的真实空窗）。

## TikTok 评论页交互（2026-07-02 真机验证过）

- 视频详情页右侧面板默认显示"猜你喜欢"推荐卡片，**不是评论区**；必须先点击"评论" tab 才会触发 `/api/comment/list/` 请求。tab 按钮在 DOM 里没有 `data-e2e` 标记，靠"文本严格等于'评论'/'Comments' 且祖先带 `RightPanelHeader`/`tabbar` class"定位，逻辑在 `comment_scraper.open_comments_tab()`。
- 页面 hydrate 到该 tab 可点击**最长实测约 16 秒**，`open_comments_tab()` 内置轮询（最多 40 秒），不要把等待时间改短。
- 对整个 `page` 做 `mouse.wheel` 会滚动/切换到 feed 里的下一个视频，不会滚评论列表——评论列表是独立的可滚动容器，必须先用 `locate_comment_scroll_point()` 定位真实容器坐标再 hover+wheel。
- 楼中楼有**两类**按钮，文案不同：首次展开是`"查看 3 条回复"`（数字前后有空格）；展开后的分页加载是`"查看其它 21 条评论"`——**用"评论"不用"回复"**，每点一次只加载 3 条，需跨轮次反复点击直到取完。`_EXPAND_REPLIES_JS` 必须两者都匹配，且分页按钮不能做持久化的"已点击"标记（否则点一次就停）。嵌套节点（span/p/div 同文本）要用 `closest('button')` 归并，避免同一按钮一轮内被点四五次。
- 评论接口真实字段名已用 100 条评论量级的真实视频核验：`cid`、`aweme_id`、`text`、`create_time`、`digg_count`、`reply_comment_total`、`reply_id`、`comment_language`、`is_author_digged`、`user.uid`/`user.unique_id`/`user.nickname` 均与 `_row_from_item()` 的映射一致，无需再怀疑字段名错位。`_get()` 保留的驼峰别名是防御性兜底，不代表这些字段本身不确定。
- 已知误差：小样本实测一条应有 5 条评论的视频只抓到 4 条，属正常范围（TikTok 展示的计数可能包含被删除/待审核评论），不必因为条数对不上就怀疑抓取逻辑有 bug。

## 目录清理规则

- 探索性/一次性脚本放 `scripts/`，不要堆在根目录
- `data_backup_*/` 是迁移前的一次性备份，确认迁移无误后可以删除
- `_browser_profile2/` 是未被任何脚本引用的遗留浏览器 profile 目录（体积大），删除前找用户确认用途
