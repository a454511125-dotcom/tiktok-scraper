# -*- coding: utf-8 -*-
"""核查第二轮：修正账号名 + 从页面数据提取视频总数。"""
import io
import os
import sys
import time
import json
import re

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根目录（脚本已归档至 scripts/）
sys.path.insert(0, BASE)

from cloakbrowser import launch_persistent_context

PROFILE = os.path.join(BASE, "_browser_profile")

# 修正后的账号名候选列表（每行可填多个尝试名）
CANDIDATES = [
    # (显示名, [尝试的 @ 名列表])
    ("Euronews",          ["euronews.english", "euronews_en", "euronewsofficial"]),
    ("CNA",               ["channelnewsasia"]),
    ("Africanews",        ["africanews.en", "africanews_tv", "africanewsenglish"]),
    ("Arirang TV",        ["arirangtv", "arirang_tv", "arirangtvworld"]),
    ("WION",              ["wionews"]),
    ("Sky News",          ["skynews"]),
    ("NHK World",         ["nhkworldjapan", "nhkworldjp", "nhkworld_english"]),
]


def extract_video_count_from_page(page):
    """从页面内嵌 JSON 数据提取总视频数。"""
    try:
        raw = page.evaluate("""() => {
            const scripts = Array.from(document.querySelectorAll('script'));
            for (const s of scripts) {
                const t = s.textContent || '';
                if (t.includes('videoCount') || t.includes('SIGI_STATE')) return t;
            }
            return '';
        }""")
        if raw:
            m = re.search(r'"videoCount"\s*:\s*(\d+)', raw)
            if m:
                return int(m.group(1))
    except Exception:
        pass
    return None


def check_account(page, username):
    """访问一个账号主页，返回信息字典；账号不存在返回 None。"""
    url = f"https://www.tiktok.com/@{username}"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception:
        pass
    time.sleep(7)

    info = page.evaluate("""() => {
        const get = (sel) => { const el = document.querySelector(sel); return el ? el.innerText.trim() : ""; };
        const bodyText = document.body.innerText || "";
        const notFound = /couldn't find this account|no longer available|用户不存在|无法找到此账号/i.test(bodyText);
        if (notFound) return { notFound: true };
        const followers = get('[data-e2e="followers-count"]');
        const likes     = get('[data-e2e="likes-count"]');
        const nickname  = get('[data-e2e="user-title"]') || document.title;
        const bio       = get('[data-e2e="user-bio"]');
        const hasLabel  = /state.{0,10}(controlled|funded|media)|government.{0,10}media/i.test(bodyText);
        return { notFound: false, followers, likes, nickname, bio, hasLabel };
    }""")

    if info.get("notFound"):
        return None

    video_count = extract_video_count_from_page(page)
    info["video_count"] = video_count
    info["username"] = username
    return info


def main():
    print("启动 CloakBrowser ...", flush=True)
    browser = launch_persistent_context(user_data_dir=PROFILE, headless=False)
    page = browser.new_page()

    final_results = {}

    for display_name, usernames in CANDIDATES:
        print(f"\n=== {display_name} ===", flush=True)
        found = None
        for uname in usernames:
            print(f"  尝试 @{uname} ...", flush=True)
            info = check_account(page, uname)
            if info is not None:
                found = info
                print(f"  [找到] 昵称={info.get('nickname','?')} | 粉丝={info.get('followers','?')} | 获赞={info.get('likes','?')}", flush=True)
                vc = info.get('video_count')
                print(f"         视频总数={vc if vc else '未提取到'} | 标签={'YES[!]' if info.get('hasLabel') else 'NO'}", flush=True)
                print(f"         简介: {(info.get('bio') or '')[:80]}", flush=True)
                break
            else:
                print(f"  [无效]", flush=True)

        if found is None:
            print(f"  所有候选名均无效", flush=True)
            final_results[display_name] = None
        else:
            final_results[display_name] = found

    page.close()
    browser.close()

    # 汇总
    print("\n" + "=" * 72)
    print(f"{'媒体':<18} {'@账号':<22} {'粉丝':>8} {'视频数':>7} {'标签':>6}")
    print("=" * 72)
    for name, info in final_results.items():
        if info is None:
            print(f"{name:<18} {'[未找到]'}")
        else:
            vc = str(info.get("video_count") or "?")
            label = "YES" if info.get("hasLabel") else " NO"
            print(f"{name:<18} @{info.get('username',''):<21} {info.get('followers','?'):>8} {vc:>7} {label:>6}")
    print("=" * 72)


if __name__ == "__main__":
    main()
