# -*- coding: utf-8 -*-
"""TikTok 评论采集核心逻辑（含楼中楼回复）— 复用 scraper.py 的浏览器/拦截机制

评论接口与视频列表接口（/api/post/item_list/）的字段命名约定不完全一致，
且未经真实抓包逐字段核验，_get() 对关键字段做了多别名兜底。首次实跑时
建议先用 1-2 个视频核对 CSV 是否符合预期，再批量采集。
"""

import csv
import json
import os
import re
import time

from timeutil import utc_str, now_utc_str

COMMENT_CSV_FIELDS = [
    "comment_id", "video_id", "reply_to_comment_id", "text",
    "create_time", "create_timestamp", "digg_count", "reply_count",
    "comment_language", "is_author_liked",
    "user_id", "user_unique_id", "user_nickname",
    "video_url", "scraped_at",
]


def _get(d: dict, *keys, default=""):
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return default


class CommentCSV:
    """按 comment_id 去重的增量写入器，语义同 scraper.IncrementalCSV"""

    def __init__(self, path):
        self.path = path
        self.seen_ids: set[str] = set()
        self.count = 0
        if os.path.exists(path):
            with open(path, encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    cid = row.get("comment_id", "")
                    if cid:
                        self.seen_ids.add(cid)
                        self.count += 1
            self._file = open(path, "a", encoding="utf-8-sig", newline="")
            self._writer = csv.DictWriter(self._file, fieldnames=COMMENT_CSV_FIELDS)
        else:
            self._file = open(path, "w", encoding="utf-8-sig", newline="")
            self._writer = csv.DictWriter(self._file, fieldnames=COMMENT_CSV_FIELDS)
            self._writer.writeheader()

    def add(self, row: dict) -> bool:
        cid = row.get("comment_id", "")
        if not cid or cid in self.seen_ids:
            return False
        self.seen_ids.add(cid)
        self._writer.writerow(row)
        self._file.flush()
        self.count += 1
        return True

    def close(self):
        self._file.close()


def _row_from_item(item: dict, video_id: str, video_url: str) -> dict:
    user = item.get("user") or {}
    ts_raw = _get(item, "create_time", "createTime", default=0)
    try:
        ts = int(ts_raw or 0)
    except (TypeError, ValueError):
        ts = 0
    reply_to = str(_get(item, "reply_id", "replyId", default="") or "")
    if reply_to == "0":
        reply_to = ""
    return {
        "comment_id": str(_get(item, "cid", "comment_id", "commentId", default="")),
        "video_id": video_id,
        "reply_to_comment_id": reply_to,
        "text": item.get("text", "") or "",
        "create_time": utc_str(ts) if ts else "",
        "create_timestamp": ts,
        "digg_count": _get(item, "digg_count", "diggCount", default=0),
        "reply_count": _get(item, "reply_comment_total", "replyCommentTotal", "reply_count", default=0),
        "comment_language": _get(item, "comment_language", "commentLanguage", default=""),
        "is_author_liked": _get(item, "is_author_digged", "isAuthorDigged", "is_author_liked", default=False),
        "user_id": str(_get(user, "uid", "id", "userId", default="")),
        "user_unique_id": _get(user, "unique_id", "uniqueId", default=""),
        "user_nickname": _get(user, "nickname", "nickName", default=""),
        "video_url": video_url,
        "scraped_at": now_utc_str(),
    }


def parse_comment_response(body_text: str, video_id: str, video_url: str) -> list[dict]:
    """解析 /api/comment/list/ 或 /api/comment/list/reply/ 的响应体，返回统一格式的行列表"""
    try:
        data = json.loads(body_text)
    except Exception:
        return []
    items = data.get("comments") or []
    return [_row_from_item(item, video_id, video_url) for item in items]


# 真机核验的两类按钮文案（2026-07-02）：
#   首次展开：  "查看 3 条回复"（数字前后有空格）
#   分页加载：  "查看其它 21 条评论"（注意是"评论"不是"回复"，且每点一次加载一批）
# 分页按钮不能做持久标记：需要跨轮次反复点击直到该楼回复取完（文案里的数字会递减）。
# 通过 closest('button') 归并嵌套节点（span/p/div 同文本），避免同一按钮一轮内被点多次。
_EXPAND_REPLIES_JS = r"""() => {
    let clicked = 0;
    const seen = new Set();
    const re = /^(View\s*\d+\s*(more\s*)?repl(y|ies)|View\s*\d+\s*more$|(查看|展开)\s*\d+\s*条回复|查看其[它他]\s*\d+\s*条(评论|回复))/i;
    for (const el of document.querySelectorAll('span, p, div, button')) {
        const t = (el.textContent || '').trim();
        if (!t || t.length > 40 || !re.test(t)) continue;
        const btn = el.closest('button') || el;
        if (seen.has(btn)) continue;
        seen.add(btn);
        try {
            btn.click();
            clicked++;
        } catch (e) {}
    }
    return clicked;
}"""


def expand_visible_replies(page) -> int:
    """点击当前可见的"查看更多回复"按钮，触发楼中楼接口请求"""
    try:
        return page.evaluate(_EXPAND_REPLIES_JS)
    except Exception:
        return 0


# 真机抓包确认：视频页右侧面板默认显示"猜你喜欢"推荐，评论需先点"评论" tab 才会加载；
# 页面 hydrate 完成前该 tab 不可点击，需轮询等待（实测最长约 16 秒）
_OPEN_COMMENTS_TAB_JS = r"""() => {
    const spans = Array.from(document.querySelectorAll('*')).filter(el => {
        if (el.textContent.trim() !== '评论' && el.textContent.trim() !== 'Comments') return false;
        if (el.children.length !== 0) return false;
        if (!el.closest('[class*="RightPanelHeader"], [class*="tabbar"], [class*="TabBar"]')) return false;
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
    });
    for (const span of spans) {
        const btn = span.closest('button') || span.parentElement;
        if (btn) { btn.click(); return true; }
    }
    return false;
}"""


def open_comments_tab(page, timeout_s: float = 40, poll_interval: float = 2) -> bool:
    """点击右侧面板的"评论" tab，切出评论列表（默认显示的是"猜你喜欢"推荐）。

    返回是否点击成功；超时未点中不抛异常，调用方按 0 条评论处理即可。
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            if page.evaluate(_OPEN_COMMENTS_TAB_JS):
                return True
        except Exception:
            pass
        time.sleep(poll_interval)
    return False


# 评论列表容器是页面内独立滚动的区域，而非整页滚动；整页滚轮会切到 feed 里的下一个视频。
# 通过"可滚动 + 位于视口右半边"定位真实容器，而非猜固定坐标百分比。
_FIND_COMMENT_SCROLL_POINT_JS = r"""() => {
    const vw = window.innerWidth;
    const all = Array.from(document.querySelectorAll('div'));
    const el = all.find(el =>
        el.scrollHeight > el.clientHeight + 100 &&
        el.clientHeight > 300 &&
        el.getBoundingClientRect().left > vw * 0.5
    );
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return [r.left + 50, r.top + 100];
}"""


def locate_comment_scroll_point(page):
    """返回评论列表容器内一点的 (x, y) 坐标，供 mouse.move + wheel 使用；找不到则回退到经验坐标"""
    try:
        point = page.evaluate(_FIND_COMMENT_SCROLL_POINT_JS)
        if point:
            return point[0], point[1]
    except Exception:
        pass
    vw = page.evaluate("window.innerWidth")
    vh = page.evaluate("window.innerHeight")
    return vw * 0.78, vh * 0.5


def scrape_video_comments(page, video_id: str, video_url: str, writer: CommentCSV,
                           should_stop, max_idle_rounds: int = 25) -> tuple[int, bool]:
    """打开视频页，滚动评论区并展开楼中楼回复，全量拦截写入 writer；不设置数量上限。

    返回 (本次新增评论条数, 评论tab是否成功打开)。tab 打开失败通常意味着页面
    hydrate 失败或评论区不可用，调用方应据此决定是否将该视频标记为已完成。
    """
    captured: list[str] = []

    def on_response(resp):
        # 覆盖一级评论 /api/comment/list/ 与楼中楼回复 /api/comment/list/reply/
        if "/api/comment/list/" not in resp.url:
            return
        try:
            captured.append(resp.text())
        except Exception:
            pass

    page.on("response", on_response)
    page.goto(video_url, wait_until="domcontentloaded", timeout=60000)
    time.sleep(5)

    tab_opened = open_comments_tab(page)
    if not tab_opened:
        return 0, False

    # 把鼠标移到评论列表容器内，让后续滚轮事件命中评论区而非切换到 feed 里的下一个视频
    try:
        x, y = locate_comment_scroll_point(page)
        page.mouse.move(x, y)
    except Exception:
        pass

    new_count = 0
    no_new = 0
    round_num = 0

    while no_new < max_idle_rounds and not should_stop():
        round_num += 1
        try:
            page.mouse.wheel(0, 1200)
        except Exception as e:
            if "Target crashed" in str(e):
                raise
            break
        expand_visible_replies(page)
        time.sleep(1.5)

        round_new = 0
        while captured:
            body = captured.pop(0)
            for row in parse_comment_response(body, video_id, video_url):
                if writer.add(row):
                    round_new += 1

        if round_new > 0:
            new_count += round_new
            no_new = 0
        else:
            no_new += 1

    return new_count, True
