# -*- coding: utf-8 -*-
"""统一的 UTC 时间格式化工具，供 scraper.py 与 comment_scraper.py 共用（避免二者互相导入）"""

import datetime


def utc_str(ts: int) -> str:
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def now_utc_str() -> str:
    return datetime.datetime.now(tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
