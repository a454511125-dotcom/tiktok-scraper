# -*- coding: utf-8 -*-
"""TikTok 视频元数据采集核心逻辑 — CloakBrowser + Playwright 网络拦截"""

import csv
import json
import os
import random
import time
import re
from urllib.parse import urlparse

import httpx

from timeutil import utc_str, now_utc_str
from comment_scraper import CommentCSV, scrape_video_comments

CSV_FIELDS = [
    "web_video_id", "desc", "create_time", "create_timestamp",
    "video_duration", "video_url", "author_id", "author_name",
    "author_nickname", "digg_count", "share_count", "comment_count",
    "play_count", "collect_count", "scraped_at",
]
# create_time / scraped_at 均为 UTC 时间（YYYY-MM-DD HH:MM:SS），非本机时区

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_SHORT_TIKTOK_HOSTS = {"vm.tiktok.com", "vt.tiktok.com"}


def _extract_first_url(raw: str) -> str:
    m = _URL_RE.search(raw.strip())
    if not m:
        return ""
    return m.group(0).rstrip("，,。.!?；;、)")


def _is_tiktok_short_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    path = parsed.path.strip("/")
    return host in _SHORT_TIKTOK_HOSTS or (
        host.endswith("tiktok.com") and path.startswith("t/")
    )


def resolve_tiktok_short_url(url: str, timeout: float = 15) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    with httpx.Client(follow_redirects=True, timeout=timeout, headers=headers) as client:
        for method in (client.head, client.get):
            try:
                resp = method(url)
                final_url = str(resp.url)
                if final_url and final_url != url:
                    return final_url
                resp.raise_for_status()
            except httpx.HTTPError:
                continue
    raise ValueError(f"短链无法解析: {url}")


def parse_account_name(raw: str) -> str:
    raw = (_extract_first_url(raw) or raw).strip().rstrip("/")
    if _is_tiktok_short_url(raw):
        raise ValueError(f"短链需要先解析: {raw}")
    m = re.search(r"@([\w.]+)", raw)
    if m:
        return m.group(1)
    parsed = urlparse(raw)
    if parsed.scheme and parsed.netloc:
        raw = parsed.path.strip("/") or parsed.netloc
    return raw.lstrip("@").split("/")[-1]


def resolve_account_name(raw: str) -> str:
    raw = raw.strip()
    url = _extract_first_url(raw)
    if url and _is_tiktok_short_url(url):
        url = resolve_tiktok_short_url(url)
        return parse_account_name(url)
    return parse_account_name(raw)


def normalize_account_names(raw_accounts: list[str]) -> list[str]:
    accounts = []
    seen = set()
    for raw in raw_accounts:
        if not raw.strip():
            continue
        name = resolve_account_name(raw)
        if name and name not in seen:
            accounts.append(name)
            seen.add(name)
    return accounts


class IncrementalCSV:
    def __init__(self, path):
        self.path = path
        self.seen_ids: set[str] = set()
        self.count = 0
        if os.path.exists(path):
            self._migrate_schema_if_needed(path)
            with open(path, encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    vid = row.get("web_video_id", "")
                    if vid:
                        self.seen_ids.add(vid)
                        self.count += 1
            self._file = open(path, "a", encoding="utf-8-sig", newline="")
            self._writer = csv.DictWriter(self._file, fieldnames=CSV_FIELDS)
        else:
            self._file = open(path, "w", encoding="utf-8-sig", newline="")
            self._writer = csv.DictWriter(self._file, fieldnames=CSV_FIELDS)
            self._writer.writeheader()

    @staticmethod
    def _migrate_schema_if_needed(path):
        """补齐旧文件缺失的字段（如 scraped_at），并把 create_time 统一重算为 UTC。"""
        with open(path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames == CSV_FIELDS:
                return
            rows = list(reader)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            writer.writeheader()
            for row in rows:
                try:
                    ts = int(row.get("create_timestamp") or 0)
                except ValueError:
                    ts = 0
                if ts:
                    row["create_time"] = utc_str(ts)
                writer.writerow({k: row.get(k, "") for k in CSV_FIELDS})
        os.replace(tmp_path, path)

    def add(self, item) -> bool:
        vid = item.get("id", "")
        if not vid or vid in self.seen_ids:
            return False
        self.seen_ids.add(vid)
        ts = int(item.get("createTime", 0))
        dt = utc_str(ts) if ts else ""
        self._writer.writerow({
            "web_video_id": vid,
            "desc": item.get("desc", ""),
            "create_time": dt,
            "create_timestamp": ts,
            "video_duration": item.get("duration", 0),
            "video_url": f"https://www.tiktok.com/@{item.get('authorName', '')}/video/{vid}",
            "author_id": item.get("authorId", ""),
            "author_name": item.get("authorName", ""),
            "author_nickname": item.get("authorNick", ""),
            "digg_count": item.get("diggCount", 0),
            "share_count": item.get("shareCount", 0),
            "comment_count": item.get("commentCount", 0),
            "play_count": item.get("playCount", 0),
            "collect_count": item.get("collectCount", 0),
            "scraped_at": now_utc_str(),
        })
        self._file.flush()
        self.count += 1
        return True

    def close(self):
        self._file.close()


def _parse_api(body_text):
    try:
        data = json.loads(body_text)
    except Exception:
        return []
    rows = []
    for item in data.get("itemList") or []:
        author = item.get("author", {})
        stats = item.get("stats", {})
        video = item.get("video", {})
        rows.append({
            "id": item.get("id", ""),
            "desc": (item.get("desc", "") or "")[:500],
            "createTime": item.get("createTime", 0),
            "duration": video.get("duration", 0),
            "authorId": author.get("id", ""),
            "authorName": author.get("uniqueId", ""),
            "authorNick": author.get("nickname", ""),
            "diggCount": stats.get("diggCount", 0),
            "shareCount": stats.get("shareCount", 0),
            "commentCount": stats.get("commentCount", 0),
            "playCount": stats.get("playCount", 0),
            "collectCount": stats.get("collectCount", 0),
        })
    return rows


class TikTokScraper:
    def __init__(self, profile_dir, output_dir, emit=None):
        self.profile_dir = profile_dir
        self.output_dir = output_dir
        self.emit = emit or (lambda t, **kw: None)
        self.browser = None
        self._stop = False
        self._login_page = None

    # ── 浏览器管理 ──

    def _launch(self):
        from cloakbrowser import launch_persistent_context
        os.makedirs(self.profile_dir, exist_ok=True)
        self.browser = launch_persistent_context(
            user_data_dir=self.profile_dir, headless=False,
        )

    def open_login(self):
        self._launch()
        self._login_page = self.browser.new_page()
        self._login_page.goto(
            "https://www.tiktok.com/login",
            wait_until="domcontentloaded", timeout=60000,
        )
        self.emit("login_opened")

    def close_login(self):
        cookies = []
        if self.browser:
            try:
                cookies = [
                    c for c in self.browser.cookies()
                    if ".tiktok.com" in c.get("domain", "")
                ]
            except Exception:
                pass
            try:
                if self._login_page:
                    self._login_page.close()
            except Exception:
                pass
            self._login_page = None
            try:
                self.browser.close()
            except Exception:
                pass
            self.browser = None
        self.emit("login_closed", cookie_count=len(cookies))
        return cookies

    # ── 采集入口 ──

    def scrape_accounts(self, accounts: list[str]):
        self._stop = False
        self._launch()
        self.emit("scrape_started", accounts=accounts)
        results = {}

        for i, name in enumerate(accounts):
            if self._stop:
                self.emit("log", msg="用户停止，跳过剩余账号")
                break
            self.emit("account_start", account=name, index=i, total=len(accounts))
            try:
                count = self._scrape_one(name)
                results[name] = count
                self.emit("account_done", account=name, count=count)
            except Exception as e:
                self.emit("account_error", account=name, error=str(e))
                results[name] = -1
                if "Target crashed" in str(e):
                    self.emit("log", msg="浏览器崩溃，尝试重启...")
                    try:
                        self.browser.close()
                    except Exception:
                        pass
                    try:
                        self._launch()
                        self.emit("log", msg="浏览器已重启")
                    except Exception as e2:
                        self.emit("log", msg=f"重启失败: {e2}")
                        break
            if not self._stop and i < len(accounts) - 1:
                time.sleep(5)

        try:
            self.browser.close()
        except Exception:
            pass
        self.browser = None
        self.emit("scrape_done", results={k: v for k, v in results.items()})

    # ── 评论采集入口 ──

    def scrape_comments_for_accounts(self, accounts: list[str]):
        """对每个账号，读取其 {account}_full.csv 中的全部视频，逐个采集评论（含楼中楼），不设数量上限"""
        self._stop = False
        self._launch()
        self.emit("comments_scrape_started", accounts=accounts)
        results = {}

        for i, name in enumerate(accounts):
            if self._stop:
                self.emit("log", msg="用户停止，跳过剩余账号")
                break
            self.emit("comments_account_start", account=name, index=i, total=len(accounts))
            try:
                count = self._scrape_comments_for_account(name)
                results[name] = count
                self.emit("comments_account_done", account=name, count=count)
            except FileNotFoundError as e:
                self.emit("comments_account_error", account=name, error=str(e))
                results[name] = -1
            except Exception as e:
                self.emit("comments_account_error", account=name, error=str(e))
                results[name] = -1
                if "Target crashed" in str(e):
                    self.emit("log", msg="浏览器崩溃，尝试重启...")
                    try:
                        self.browser.close()
                    except Exception:
                        pass
                    try:
                        self._launch()
                        self.emit("log", msg="浏览器已重启")
                    except Exception as e2:
                        self.emit("log", msg=f"重启失败: {e2}")
                        break
            if not self._stop and i < len(accounts) - 1:
                time.sleep(5)

        try:
            self.browser.close()
        except Exception:
            pass
        self.browser = None
        self.emit("comments_scrape_done", results={k: v for k, v in results.items()})

    def _scrape_comments_for_account(self, name: str) -> int:
        videos_path = os.path.join(self.output_dir, f"{name}_full.csv")
        if not os.path.exists(videos_path):
            raise FileNotFoundError(f"未找到视频列表: {videos_path}，请先采集该账号的视频")

        videos = []
        with open(videos_path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                vid = row.get("web_video_id", "")
                url = row.get("video_url", "")
                try:
                    expected = int(row.get("comment_count") or 0)
                except ValueError:
                    expected = 0
                if vid and url:
                    videos.append((vid, url, expected))

        comments_path = os.path.join(self.output_dir, f"{name}_comments.csv")
        progress_path = os.path.join(self.output_dir, f"{name}_comments_progress.json")
        writer = CommentCSV(comments_path)
        done_ids = self._load_comment_progress(progress_path)

        self.emit("log", msg=f"[{name}] 视频总数 {len(videos)}，已完成 {len(done_ids)}")

        processed = 0
        try:
            for i, (vid, url, expected) in enumerate(videos):
                if self._stop:
                    break
                if vid in done_ids:
                    continue

                failed = False
                page = self.browser.new_page()
                try:
                    new_n, tab_opened = scrape_video_comments(
                        page, vid, url, writer, should_stop=lambda: self._stop,
                    )
                except Exception as e:
                    if "Target crashed" in str(e):
                        raise
                    self.emit("log", msg=f"[{name}] 视频 {vid} 采集出错，本次不标记完成，续传时将重试: {e}")
                    new_n, tab_opened, failed = 0, False, True
                finally:
                    try:
                        page.close()
                    except Exception:
                        pass

                # 停止时正在采集的视频不标记完成，否则未采完的评论会被永久跳过；
                # 若恰好已自然采完，下次重采会被 comment_id 去重兜住，只多花时间不损数据
                if self._stop:
                    break

                if not failed and not tab_opened:
                    if expected > 0:
                        # 视频CSV记录有评论但评论区打不开：可能是临时风控/加载失败，不标记完成
                        failed = True
                        self.emit("log", msg=f"[{name}] 视频 {vid} 评论区未能打开"
                                             f"（记录有 {expected} 条评论），续传时将重试")
                    else:
                        # 采集视频时就是 0 评论：视为正常完成（评论区可能根本不渲染）
                        self.emit("log", msg=f"[{name}] 视频 {vid} 无评论，跳过")

                if not failed:
                    done_ids.add(vid)
                    self._save_comment_progress(progress_path, done_ids)

                processed += 1
                self.emit("comments_progress", account=name, video_id=vid,
                          index=i, total=len(videos), new=new_n, running_total=writer.count)

                if processed % 50 == 0:
                    rest = random.uniform(60, 120)
                    self.emit("log", msg=f"[{name}] 已连续处理 {processed} 个视频，休息 {rest:.0f} 秒")
                    time.sleep(rest)
                else:
                    time.sleep(random.uniform(3, 5))

            return writer.count
        finally:
            writer.close()

    @staticmethod
    def _load_comment_progress(path) -> set[str]:
        if not os.path.exists(path):
            return set()
        try:
            with open(path, encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()

    @staticmethod
    def _save_comment_progress(path, done_ids: set[str]):
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(sorted(done_ids), f, ensure_ascii=False)
        os.replace(tmp_path, path)

    # ── 单账号采集 ──

    # TikTok 对每次页面加载的视频流有"吐出量预算"（2026-07-02 实测约 70-85 批 ≈ 1100-1350 条，
    # 从列表头部计数、重复也计入，耗尽后即使 hasMore=True 也不再返回数据；预算大小随时间波动）。
    # reload 即可重置预算，因此每个方向做多轮"reload → 重走"循环，直到连续若干轮零新增。
    MAX_CYCLES_PER_DIRECTION = 15   # 单方向分页循环上限（防御性硬顶）
    STALL_NO_RESPONSE_ROUNDS = 15   # 连续多少轮无接口响应判定本轮预算耗尽
    MAX_ROUNDS_PER_CYCLE = 300      # 单轮滚动次数硬顶

    def _scrape_one(self, name: str) -> int:
        csv_path = os.path.join(self.output_dir, f"{name}_full.csv")
        writer = IncrementalCSV(csv_path)
        captured: list[list[dict]] = []

        def on_response(resp):
            if "/api/post/item_list/" not in resp.url:
                return
            try:
                rows = _parse_api(resp.text())
                if rows:
                    captured.append(rows)
            except Exception:
                pass

        page = self.browser.new_page()
        try:
            page.on("response", on_response)
            url = f"https://www.tiktok.com/@{name}"
            self.emit("log", msg=f"打开 {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(8)

            if writer.count > 0:
                self.emit("log", msg=f"断点续传: 已有 {writer.count} 条")

            for direction in ["newest", "oldest"]:
                if self._stop:
                    break
                # 新内容只出现在列表头部，newest 方向一轮零新增即可停；
                # oldest 方向的推进依赖预算波动，多试一轮
                max_zero_cycles = 1 if direction == "newest" else 2
                zero_cycles = 0
                dir_new = 0

                for cycle in range(1, self.MAX_CYCLES_PER_DIRECTION + 1):
                    if self._stop:
                        break
                    if cycle > 1:
                        self.emit("log", msg=f"[{name}] {direction} 第{cycle}轮分页: reload 重置预算")
                        page.reload(wait_until="domcontentloaded", timeout=60000)
                        time.sleep(8)

                    if direction == "oldest":
                        if not self._click_oldest(page):
                            self.emit("log", msg=f"[{name}] 最旧排序未能点击（页面渲染慢或无此按钮），本轮按默认排序进行")
                        time.sleep(3)

                    cycle_new = self._scroll_cycle(page, writer, captured, name, direction, cycle)
                    dir_new += cycle_new
                    self.emit("log", msg=f"[{name}] {direction} 第{cycle}轮: 新增{cycle_new}, 总计{writer.count}")

                    if cycle_new == 0:
                        zero_cycles += 1
                        if zero_cycles >= max_zero_cycles:
                            break
                    else:
                        zero_cycles = 0

                self.emit("log", msg=f"{direction}完成: 新增{dir_new}, 总计{writer.count}")

            return writer.count
        finally:
            try:
                page.close()
            except Exception:
                pass
            writer.close()

    def _scroll_cycle(self, page, writer, captured, name, direction, cycle) -> int:
        """单轮分页走查：滚动直到连续 STALL_NO_RESPONSE_ROUNDS 轮无接口响应（预算耗尽）。

        停止判据基于"是否还有响应"而非"是否有新数据"：断点续传时需要长距离快进
        跳过已采集的重复项，期间没有新增但响应持续，不能据此提前退出。
        返回本轮新增条数。
        """
        no_resp = 0
        round_num = 0
        cycle_new = 0
        blank_retries = 0

        while (no_resp < self.STALL_NO_RESPONSE_ROUNDS
               and round_num < self.MAX_ROUNDS_PER_CYCLE and not self._stop):
            round_num += 1

            if round_num % 15 == 0 or no_resp == 5:
                try:
                    video_count = page.evaluate(
                        "document.querySelectorAll('div[data-e2e=\"user-post-item\"],"
                        " div[class*=\"DivItemContainer\"],"
                        " div[class*=\"DivVideoFeed\"] > div').length"
                    )
                    page_text = page.evaluate(
                        "document.body ? document.body.innerText.substring(0, 200) : ''"
                    )
                    is_blank = (
                        video_count == 0
                        or "请刷新" in page_text or "Refresh" in page_text
                        or len(page_text.strip()) < 20
                    )
                except Exception:
                    is_blank = True

                if is_blank and blank_retries < 3:
                    blank_retries += 1
                    self.emit("log", msg=f"检测到空白页面(第{blank_retries}次)，刷新中...")
                    time.sleep(5)
                    page.reload(wait_until="domcontentloaded", timeout=60000)
                    time.sleep(8)
                    if direction == "oldest":
                        self._click_oldest(page)
                        time.sleep(3)
                    no_resp = 0
                    continue
                elif is_blank and blank_retries >= 3:
                    self.emit("log", msg=f"连续{blank_retries}次空白页面，放弃本轮")
                    break

            try:
                if round_num % 3 == 0:
                    page.keyboard.press("End")
                else:
                    page.mouse.wheel(0, 4000 + (round_num % 5) * 500)
            except Exception as e:
                if "Target crashed" in str(e):
                    raise
                break
            time.sleep(2.5 + (round_num % 3) * 0.5)

            round_batches = 0
            new_this = 0
            while captured:
                round_batches += 1
                for item in captured.pop(0):
                    if writer.add(item):
                        new_this += 1

            if round_batches == 0:
                no_resp += 1
                if no_resp % 5 == 0:
                    self.emit("log", msg=f"[{name}] {direction} 第{cycle}轮 滚动#{round_num}: "
                                         f"无响应 ({no_resp}/{self.STALL_NO_RESPONSE_ROUNDS})")
            else:
                no_resp = 0
                blank_retries = 0

            if new_this > 0:
                cycle_new += new_this
                self.emit("progress", account=name, direction=direction,
                          round=round_num, new=new_this, total=writer.count)

        return cycle_new

    def _click_oldest(self, page, timeout_s: float = 30) -> bool:
        """点击"最旧"排序 tab。页面 hydrate 完成前按钮不存在（实测可达 16 秒），
        必须轮询等待；一次性查找会静默失败导致整个方向按最新排序白跑。"""
        deadline = time.time() + timeout_s
        while time.time() < deadline and not self._stop:
            try:
                clicked = page.evaluate("""() => {
                    for (const el of document.querySelectorAll('button,span,p,div')) {
                        if (['最旧','Oldest'].includes(el.textContent.trim())) {
                            el.click(); return true;
                        }
                    }
                    return false;
                }""")
                if clicked:
                    self.emit("log", msg="已切换到最旧排序")
                    return True
            except Exception:
                pass
            time.sleep(2)
        return False

    def stop(self):
        self._stop = True
