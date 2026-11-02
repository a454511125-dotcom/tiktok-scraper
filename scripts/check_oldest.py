# -*- coding: utf-8 -*-
"""通过拦截 TikTok API 响应，快速确认账号最早视频发布时间。
用于判断候选对照账号是否有 2022 年以前的数据。
"""
import io, os, sys, time, json, datetime
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根目录（脚本已归档至 scripts/）
sys.path.insert(0, BASE)
from cloakbrowser import launch_persistent_context

PROFILE = os.path.join(BASE, "_browser_profile")
ACCOUNTS = ["channelnewsasia", "reuters"]


def check_account_dates(browser, account):
    """打开账号页，向下滚动多次，收集视频时间戳，返回最早时间。"""
    page = browser.new_page()
    timestamps = []

    def on_response(response):
        if "/api/post/item_list/" in response.url:
            try:
                body = response.text()
                data = json.loads(body)
                for item in data.get("itemList") or []:
                    ts = item.get("createTime", 0)
                    if ts:
                        timestamps.append(int(ts))
            except Exception:
                pass

    page.on("response", on_response)

    url = f"https://www.tiktok.com/@{account}"
    print(f"\n>>> @{account} 加载中...", flush=True)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        print(f"    加载异常: {e}", flush=True)

    time.sleep(5)

    # 向下滚动 20 次以触发 API 请求（每次 ~20 条视频）
    for i in range(20):
        page.keyboard.press("End")
        time.sleep(1.5)
        if i % 5 == 4:
            print(f"    滚动 {i+1}/20，已收集 {len(timestamps)} 条时间戳...", flush=True)

    page.close()

    if not timestamps:
        print(f"    未拦截到时间戳", flush=True)
        return

    earliest_ts = min(timestamps)
    latest_ts   = max(timestamps)
    earliest_dt = datetime.datetime.fromtimestamp(earliest_ts)
    latest_dt   = datetime.datetime.fromtimestamp(latest_ts)

    # 2023-01-18 干预点之前的数量
    cut = datetime.datetime(2023, 1, 18).timestamp()
    before_cut = [t for t in timestamps if t < cut]
    after_cut  = [t for t in timestamps if t >= cut]

    print(f"    共收集: {len(timestamps)} 条（抽样）", flush=True)
    print(f"    最早视频: {earliest_dt.strftime('%Y-%m-%d')}", flush=True)
    print(f"    最新视频: {latest_dt.strftime('%Y-%m-%d')}", flush=True)
    print(f"    干预前(< 2023-01-18): {len(before_cut)} 条", flush=True)
    print(f"    干预后(>= 2023-01-18): {len(after_cut)} 条", flush=True)
    return {"earliest": earliest_dt, "latest": latest_dt,
            "before": len(before_cut), "after": len(after_cut), "total": len(timestamps)}


def main():
    print("启动 CloakBrowser ...", flush=True)
    browser = launch_persistent_context(user_data_dir=PROFILE, headless=False)
    results = {}
    for acct in ACCOUNTS:
        results[acct] = check_account_dates(browser, acct)
    browser.close()

    print("\n" + "=" * 60)
    print("汇总（抽样，非全量）")
    print("=" * 60)
    for acct, r in results.items():
        if not r:
            print(f"@{acct}: 无数据")
        else:
            print(f"@{acct}: 最早={r['earliest'].strftime('%Y-%m-%d')} | 干预前抽样={r['before']} | 干预后抽样={r['after']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
