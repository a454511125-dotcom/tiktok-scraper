# -*- coding: utf-8 -*-
"""用 CloakBrowser 登录态核查候选对照账号基本信息。
依次打开各账号主页，提取粉丝数、获赞数、视频数、是否有国家控制媒体标签。
"""
import io
import os
import sys
import time

# 强制 stdout 使用 utf-8，避免 GBK 编码崩溃
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根目录（脚本已归档至 scripts/）
sys.path.insert(0, BASE)

from cloakbrowser import launch_persistent_context

PROFILE = os.path.join(BASE, "_browser_profile")

# TikTok 上实际的账号 @ 名称（需要与平台一致）
CANDIDATES = [
    "euronews",
    "channelnewsasia",
    "africanews",
    "arirang",
    "wionews",
    "skynews",
    "nhkworld",
]


def extract_profile(page, account):
    url = f"https://www.tiktok.com/@{account}"
    print(f"\n>>> 正在访问 @{account} ...", flush=True)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        print(f"    页面加载超时或出错: {e}", flush=True)

    time.sleep(8)  # 等待 JS 渲染

    info = page.evaluate("""() => {
        const get = (sel) => {
            const el = document.querySelector(sel);
            return el ? el.innerText.trim() : "";
        };

        const followers = get('[data-e2e="followers-count"]');
        const likes     = get('[data-e2e="likes-count"]');
        const following = get('[data-e2e="following-count"]');
        const video_count = get('[data-e2e="video-count"]');
        const nickname  = get('[data-e2e="user-title"]') || document.title;
        const bio       = get('[data-e2e="user-bio"]');

        // 页面正文里查找标签关键词
        const bodyText = document.body.innerText || "";
        const hasLabel = /state.{0,10}(controlled|funded|media)|government.{0,10}media/i.test(bodyText);

        // 检测账号是否存在（找不到账号时会有特殊提示）
        const notFound = /couldn't find this account|no longer available/i.test(bodyText);

        return { followers, likes, following, video_count, nickname, bio, hasLabel, notFound };
    }""")

    if info.get("notFound"):
        print(f"    [账号不存在或已更名]", flush=True)
    else:
        print(f"    昵称: {info.get('nickname', 'N/A')}", flush=True)
        print(f"    粉丝: {info.get('followers', 'N/A')}", flush=True)
        print(f"    获赞: {info.get('likes', 'N/A')}", flush=True)
        print(f"    视频数: {info.get('video_count', 'N/A')}", flush=True)
        label_flag = "YES [!]" if info.get("hasLabel") else "NO"
        print(f"    国家控制媒体标签: {label_flag}", flush=True)
        print(f"    简介: {(info.get('bio') or '')[:100]}", flush=True)
    return info


def main():
    print("启动 CloakBrowser (已登录 profile)...", flush=True)
    browser = launch_persistent_context(user_data_dir=PROFILE, headless=False)

    page = browser.new_page()

    results = {}
    for account in CANDIDATES:
        results[account] = extract_profile(page, account)

    page.close()
    browser.close()

    # 汇总表
    print("\n" + "=" * 68)
    print(f"{'账号':<22} {'粉丝':>8} {'获赞':>10} {'视频数':>7} {'有标签':>7}")
    print("=" * 68)
    for acct, info in results.items():
        if info.get("notFound"):
            print(f"@{acct:<21} {'[账号不存在]':>34}")
        else:
            label = "YES" if info.get("hasLabel") else " NO"
            print(f"@{acct:<21} {info.get('followers','?'):>8} {info.get('likes','?'):>10} {info.get('video_count','?'):>7} {label:>7}")
    print("=" * 68)


if __name__ == "__main__":
    main()
