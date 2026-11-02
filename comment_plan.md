# TikTok 评论采集功能方案

> 2026-07-02 起草，同日实施完成。原「待定决策」（第八节）已由用户拍板：**视频不抽样、评论不设上限、含楼中楼、保留原始用户 ID**——即全量采集，不做第七节里设想的"一期/二期"分阶段。第三、五、七节涉及筛选参数与分期的内容已不适用于最终实现，保留仅作历史参考；实际 API/字段设计以 `comment_scraper.py`、`scraper.py`、`CLAUDE.md` 为准。

## 一、可行性

现有工具的原理是：真实浏览器打开页面 → 滚动触发 TikTok 内部 API → 拦截响应写入 CSV。评论采集完全复用这条路线：

- 打开视频页（`video_url` 已在现有 CSV 中）后，评论区由 `https://www.tiktok.com/api/comment/list/` 接口分页加载，每页约 20 条；
- 楼中楼回复走 `https://www.tiktok.com/api/comment/list/reply/`，需逐条点击"View replies"触发；
- 滚动评论面板即可触发下一页请求，与现有视频列表的滚动逻辑同构。

无需破解 X-Bogus 签名（直接 HTTP 请求评论 API 才需要），无新增依赖。

**实施第一步是抓一条真实响应核验字段结构**（下表字段名基于 TikTok Web API 的已知结构，以实际抓包为准）。

## 二、数据字段

输出文件：`data/{account}_comments.csv`，按 `comment_id` 去重。

| 字段 | 来源 | 说明 |
|------|------|------|
| comment_id | cid | 评论唯一 ID |
| video_id | aweme_id | 归属视频，可与 `{account}_full.csv` 关联 |
| text | text | 评论原文 |
| create_time / create_timestamp | create_time | 与视频 CSV 同口径（见方案第六节时区说明） |
| digg_count | digg_count | 评论点赞数 |
| reply_count | reply_comment_total | 该评论收到的回复数 |
| user_id / user_unique_id / user_nickname | user.* | 评论者信息 |
| reply_to_comment_id | reply_id | 楼中楼归属；一级评论为空 |
| comment_language | comment_language | TikTok 标注的评论语言（跨语言研究有用） |
| is_author_liked | is_author_digged | 视频作者是否赞了该评论 |
| video_url | 拼接 | 来源 URL（规范要求） |
| scraped_at | 本地生成 | 采集时间（规范要求） |

## 三、架构与文件改动

| 文件 | 改动 |
|------|------|
| `comment_scraper.py`（新建） | `CommentCSV` 类（仿 `IncrementalCSV`）、`_parse_comment_api()`、`scrape_video_comments(page, video)` 滚动+拦截逻辑 |
| `scraper.py` | `TikTokScraper` 增加 `scrape_comments(videos, config)` 入口，复用 `_launch()` 与浏览器崩溃重启逻辑 |
| `server.py` | 新增 `POST /api/comments/scrape`（参数见下）、复用 `is_scraping` 锁与 WebSocket 事件 |
| `index.html` | 新增第 5 卡片「评论采集」：下拉选择已有 `*_full.csv` → 显示视频数与预计耗时 → 筛选参数 → 开始/停止 |

### 请求参数设计

```json
{
  "source_file": "bbcnews_full.csv",
  "max_comments_per_video": 500,
  "min_comment_count": 10,      // 跳过评论数低于此值的视频
  "date_from": "2025-01-01",    // 可选，按视频发布时间筛选
  "date_to": null,
  "top_n": null                 // 可选，只采 comment_count 最高的 N 条视频
}
```

### 断点续传

- `data/{account}_comments_progress.json` 记录已完成的 `video_id` 集合；
- CSV 内按 `comment_id` 去重（防止单视频中断后重采产生重复）；
- 重跑时跳过已完成视频，从中断视频继续。

## 四、速率与风控

- 视频间隔 3–5 秒随机；评论区滚动间隔 1.5–2.5 秒（与现有视频采集一致）；
- 每采完 50 个视频休息 60–120 秒；
- 评论接口比视频列表接口更敏感，建议用小号登录采集；
- 部分视频评论关闭或仅好友可见（`comment_count > 0` 但接口返回空），记入日志跳过，不视为错误。

## 五、耗时估算（决定抽样策略）

单视频成本 ≈ 页面加载 8–10 秒 + 每 20 条评论一次滚动（约 2 秒）：

| 视频评论量 | 单视频耗时 |
|-----------|-----------|
| ≤ 100 条 | 约 20–30 秒 |
| 500 条 | 约 1–1.5 分钟 |
| 5000 条（大热门） | 约 10 分钟以上 |

当前 data/ 目录共约 **25,600 条视频**。全量采集所有视频的评论需连续运行两周以上，不现实。因此筛选参数（时间范围、min_comment_count、top_n、单视频上限）是方案的核心，需结合研究设计确定抽样框。

## 六、随此功能一并修复的存量问题

1. 视频与评论 CSV 均补充 `scraped_at` 采集时间字段（爬虫规范要求）；
2. `create_time` 统一注明时区口径：现为运行机器本地时区（UTC+8），建议改为 UTC 并在 README 注明，跨国账号对比时避免日期错位；
3. `_scrape_one` 的 `page` / `writer` 移入 try/finally，异常时不再泄漏文件句柄；
4. `server.py`：采集中禁止 `/api/login`（当前会覆盖运行中的实例导致失控）；服务绑定改 `127.0.0.1`。

## 七、分期

- **一期**：一级评论全量字段 + 筛选 + 断点续传 + UI（本方案主体，预计新增 300–400 行）；
- **二期（可选）**：楼中楼回复采集。成本高（需逐条点击展开），仅当研究需要互动结构（谁回复谁）时再做；一期的 `reply_count` 已可支撑参与度分析。

## 八、待定决策（实施前确认）

1. **抽样策略**：按什么标准筛选视频？（时间窗口 / 评论数阈值 / 热门 top-N / 全量）——研究设计问题，需用户定；
2. **单视频评论上限**：建议默认 500，热门视频评论的长尾部分信息增量有限；
3. **是否需要楼中楼**：默认一期不做；
4. **脱敏**：建议采集时保留原始用户 ID（去重与可溯源需要），论文与公开数据集层面再做匿名化处理。
