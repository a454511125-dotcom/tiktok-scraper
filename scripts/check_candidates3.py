# -*- coding: utf-8 -*-
"""第三轮核查：修正账号名 + 新备选。"""
import io, os, sys, time, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根目录（脚本已归档至 scripts/）
sys.path.insert(0, BASE)
from cloakbrowser import launch_persistent_context

PROFILE = os.path.join(BASE, "_browser_profile")

CANDIDATES = [
    ("Euronews",       ["euronews_en", "euronewsen", "euronews.official", "euronewsofficial2"]),
    ("Arirang TV",     ["arirang_world", "arirangnews", "arirangtvofficial", "arirangtv_world"]),
    ("NHK World",      ["nhknews", "nhk_world", "nhkworldnews", "nhkworldenglish"]),
    ("PBS NewsHour",   ["pbsnewshour"]),
    ("ABC Australia",  ["abcnewsau", "abcaustralia", "abc_australia"]),
    ("VOA News",       ["voanews"]),
    ("Reuters",        ["reuters"]),
    ("AP Archive",     ["aparchive"]),
]


def get_info(page, username):
    url = f"https://www.tiktok.com/@{username}"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=25000)
    except Exception:
        pass
    time.sleep(6)

    info = page.evaluate("""() => {
        const get = (sel) => { const el = document.querySelector(sel); return el ? el.innerText.trim() : ""; };
        const bodyText = document.body.innerText || "";
        const notFound = /couldn't find|no longer available|无法找到|该账号不存在/i.test(bodyText);
        if (notFound) return { notFound: true };
        const followers = get('[data-e2e="followers-count"]');
        const likes = get('[data-e2e="likes-count"]');
        const nickname = get('[data-e2e="user-title"]') || "";
        const bio = get('[data-e2e="user-bio"]');
        const hasLabel = /state.{0,10}(controlled|funded|media)|government.{0,10}media/i.test(bodyText);
        return { notFound: false, followers, likes, nickname, bio, hasLabel };
    }""")

    if info.get("notFound") or not info.get("followers"):
        return None

    # 视频总数从页面脚本提取
    try:
        raw = page.evaluate("""() => {
            for (const s of document.querySelectorAll('script')) {
                if ((s.textContent || '').includes('videoCount')) return s.textContent;
            }
            return '';
        }""")
        m = re.search(r'"videoCount"\s*:\s*(\d+)', raw or "")
        info["video_count"] = int(m.group(1)) if m else None
    except Exception:
        info["video_count"] = None

    info["username"] = username
    return info


def main():
    print("启动 CloakBrowser ...", flush=True)
    browser = launch_persistent_context(user_data_dir=PROFILE, headless=False)
    page = browser.new_page()

    found_results = {}
    for display, usernames in CANDIDATES:
        print(f"\n=== {display} ===", flush=True)
        hit = None
        for uname in usernames:
            print(f"  @{uname} ...", flush=True)
            info = get_info(page, uname)
            if info:
                hit = info
                vc = info.get("video_count")
                print(f"  [OK] 粉丝={info['followers']} | 获赞={info['likes']} | 视频={vc or '?'} | 标签={'YES' if info['hasLabel'] else 'NO'}", flush=True)
                print(f"       简介: {(info.get('bio') or '')[:80]}", flush=True)
                break
            else:
                print(f"  [无效]", flush=True)
        found_results[display] = hit

    page.close()
    browser.close()

    print("\n" + "=" * 72)
    print(f"{'媒体':<16} {'@账号':<24} {'粉丝':>8} {'视频数':>7} {'标签':>5}")
    print("=" * 72)
    for name, info in found_results.items():
        if not info:
            print(f"{name:<16} {'[未找到]'}")
        else:
            vc = str(info.get("video_count") or "?")
            label = "YES" if info.get("hasLabel") else " NO"
            print(f"{name:<16} @{info['username']:<23} {info['followers']:>8} {vc:>7} {label:>5}")
    print("=" * 72)


if __name__ == "__main__":
    main()
