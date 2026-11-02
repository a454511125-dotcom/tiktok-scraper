# -*- coding: utf-8 -*-
"""TikTok 数据采集工具 — Web 服务端"""

import asyncio
import csv
import glob
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

_BOOTSTRAP_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_VENV_PYTHON = os.path.join(_BOOTSTRAP_BASE_DIR, ".venv", "Scripts", "python.exe")
if (
    __name__ == "__main__"
    and os.path.exists(_VENV_PYTHON)
    and os.path.abspath(sys.executable).lower() != os.path.abspath(_VENV_PYTHON).lower()
):
    os.execv(_VENV_PYTHON, [_VENV_PYTHON, __file__, *sys.argv[1:]])

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel
import uvicorn

from scraper import TikTokScraper, normalize_account_names

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
PROFILE_DIR = os.path.join(BASE_DIR, "_browser_profile")

ws_clients: set[WebSocket] = set()
main_loop: asyncio.AbstractEventLoop | None = None
scraper_instance: TikTokScraper | None = None
is_scraping = False

# 登录浏览器的打开和关闭必须在同一个线程执行：Playwright sync API 与创建它的线程
# 绑定（greenlet），跨线程调用会抛 "cannot switch to a different thread"。
# 单 worker 线程池保证所有登录操作复用同一个常驻线程。
login_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="login")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global main_loop
    main_loop = asyncio.get_running_loop()
    os.makedirs(DATA_DIR, exist_ok=True)
    yield


app = FastAPI(lifespan=lifespan)


# ── WebSocket 广播 ──

async def _broadcast(msg: dict):
    dead = set()
    # 迭代快照：send_json 的 await 期间可能有客户端连接/断开修改集合
    for ws in list(ws_clients):
        try:
            await ws.send_json(msg)
        except Exception:
            dead.add(ws)
    ws_clients -= dead


def emit(event_type: str, **data):
    msg = {"type": event_type, **data}
    if main_loop and main_loop.is_running():
        asyncio.run_coroutine_threadsafe(_broadcast(msg), main_loop)


def _count_csv_rows(path: str) -> int:
    """按 CSV 记录数计数，而非物理行数（字段中可能包含换行符）"""
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            return sum(1 for _ in csv.reader(f)) - 1
    except Exception:
        return 0


# ── 请求模型 ──

class ScrapeRequest(BaseModel):
    accounts: list[str]


class CommentScrapeRequest(BaseModel):
    accounts: list[str]


# ── 路由 ──

@app.get("/")
async def index():
    return FileResponse(os.path.join(BASE_DIR, "index.html"), media_type="text/html")


@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)


@app.get("/api/status")
async def status():
    has_profile = False
    if os.path.exists(PROFILE_DIR):
        has_profile = any(f for f in os.listdir(PROFILE_DIR) if not f.startswith("."))
    return {"logged_in": has_profile, "scraping": is_scraping}


@app.post("/api/login")
async def start_login():
    global scraper_instance
    if is_scraping:
        return JSONResponse({"error": "采集进行中，无法重新登录"}, 400)
    if scraper_instance is not None:
        return JSONResponse({"error": "登录浏览器已打开，请在窗口中登录后点击「登录完成」"}, 400)
    scraper_instance = TikTokScraper(PROFILE_DIR, DATA_DIR, emit=emit)

    def run():
        try:
            scraper_instance.open_login()
        except Exception as e:
            emit("error", msg=f"启动浏览器失败: {e}")

    login_executor.submit(run)
    return {"status": "launching"}


@app.post("/api/login/done")
async def finish_login():
    global scraper_instance
    if is_scraping:
        return JSONResponse({"error": "采集进行中"}, 400)
    if not scraper_instance or not scraper_instance.browser:
        return JSONResponse({"error": "浏览器未启动"}, 400)

    def run():
        global scraper_instance
        try:
            cookies = scraper_instance.close_login()
            emit("login_done", cookie_count=len(cookies))
        except Exception as e:
            emit("error", msg=f"关闭浏览器失败: {e}")
        scraper_instance = None

    login_executor.submit(run)
    return {"status": "closing"}


@app.post("/api/scrape")
async def start_scrape(req: ScrapeRequest):
    global scraper_instance, is_scraping
    if is_scraping:
        return JSONResponse({"error": "正在采集中"}, 400)
    if scraper_instance is not None:
        return JSONResponse({"error": "登录浏览器打开中，请先完成登录"}, 400)

    # 先占用采集锁再 await：短链解析最长十几秒，期间事件循环可处理并发请求，
    # 若不先置位，双击"开始采集"会启动两个浏览器争抢同一 profile
    is_scraping = True
    try:
        accounts = await asyncio.to_thread(normalize_account_names, req.accounts)
    except ValueError as e:
        is_scraping = False
        return JSONResponse({"error": str(e)}, 400)
    if not accounts:
        is_scraping = False
        return JSONResponse({"error": "请输入至少一个账号"}, 400)

    scraper_instance = TikTokScraper(PROFILE_DIR, DATA_DIR, emit=emit)

    def run():
        global is_scraping, scraper_instance
        try:
            scraper_instance.scrape_accounts(accounts)
        except Exception as e:
            emit("error", msg=f"采集异常: {e}")
        finally:
            is_scraping = False
            scraper_instance = None

    threading.Thread(target=run, daemon=True).start()
    return {"status": "started", "accounts": accounts}


@app.post("/api/scrape/stop")
async def stop_scrape():
    if scraper_instance:
        scraper_instance.stop()
        return {"status": "stopping"}
    return {"status": "idle"}


@app.get("/api/comment-sources")
async def comment_sources():
    """列出可用于评论采集的账号（已存在 {account}_full.csv 视频列表的账号）"""
    sources = []
    for f in sorted(glob.glob(os.path.join(DATA_DIR, "*_full.csv"))):
        account = os.path.basename(f)[: -len("_full.csv")]
        video_count = _count_csv_rows(f)
        comments_path = os.path.join(DATA_DIR, f"{account}_comments.csv")
        comment_count = _count_csv_rows(comments_path) if os.path.exists(comments_path) else 0
        sources.append({
            "account": account,
            "video_count": max(video_count, 0),
            "comment_count": max(comment_count, 0),
        })
    return sources


@app.post("/api/comments/scrape")
async def start_comment_scrape(req: CommentScrapeRequest):
    global scraper_instance, is_scraping
    if is_scraping:
        return JSONResponse({"error": "正在采集中"}, 400)
    if scraper_instance is not None:
        return JSONResponse({"error": "登录浏览器打开中，请先完成登录"}, 400)
    accounts = [a for a in req.accounts if a and not any(c in a for c in ("..", "/", "\\"))]
    if not accounts:
        return JSONResponse({"error": "请至少选择一个账号"}, 400)

    scraper_instance = TikTokScraper(PROFILE_DIR, DATA_DIR, emit=emit)
    is_scraping = True

    def run():
        global is_scraping, scraper_instance
        try:
            scraper_instance.scrape_comments_for_accounts(accounts)
        except Exception as e:
            emit("error", msg=f"评论采集异常: {e}")
        finally:
            is_scraping = False
            scraper_instance = None

    threading.Thread(target=run, daemon=True).start()
    return {"status": "started", "accounts": accounts}


@app.get("/api/files")
async def list_files():
    files = []
    for f in sorted(glob.glob(os.path.join(DATA_DIR, "*.csv"))):
        name = os.path.basename(f)
        size = os.path.getsize(f)
        rows = _count_csv_rows(f)
        files.append({"name": name, "size": size, "rows": max(rows, 0)})
    return files


@app.get("/api/download/{filename}")
async def download(filename: str):
    if ".." in filename or "/" in filename or "\\" in filename:
        return JSONResponse({"error": "非法文件名"}, 400)
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        return JSONResponse({"error": "文件不存在"}, 404)
    return FileResponse(path, filename=filename, media_type="text/csv")


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    ws_clients.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        ws_clients.discard(ws)


if __name__ == "__main__":
    print("=" * 40)
    print("TikTok Scraper")
    print("Open http://localhost:8000 in your browser")
    print("=" * 40)
    uvicorn.run(app, host="127.0.0.1", port=8000)
