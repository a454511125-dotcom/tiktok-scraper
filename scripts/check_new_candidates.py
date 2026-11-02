# -*- coding: utf-8 -*-
"""核查新发现的候选账号：NHK World Japan, ABC Australia。"""
import io, os, sys, time, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根目录（脚本已归档至 scripts/）
sys.path.insert(0, BASE)
from cloakbrowser import launch_persistent_context

PROFILE = os.path.join(BASE, "_browser_profile")

ACCOUNTS = [
    ("NHK World Japan",   "nhkworldjapanofficial"),
    ("ABC Australia",     "abcnewsaus"),
    ("CNA (已确认)",      "channelnewsasia"),
]


def get_video_count(page):
    try:
        raw = page.evaluate("""() => {
            for (const s of document.querySelectorAll('script')) {
                const t = s.textContent || '';
                if (t.includes('videoCount')) return t;
            }
            return '';
        }""")
        m = re.search(r'"videoCount"\s*:\s*(\d+)', raw or "")
        return int(m.group(1)) if m else None
    except Exception:
        return None


def check(page, display, username):
    print(f"\n>>> {display} (@{username})", flush=True)
    try:
        page.goto(f"https://www.tiktok.com/@{username}",
                  wait_until="domcontentloaded", timeout=25000)
    except Exception:
        pass
    time.sleep(7)

    info = page.evaluate("""() => {
        const get = (sel) => { const el = document.querySelector(sel); return el ? el.innerText.trim() : ""; };
        const body = document.body.innerText || "";
        const notFound = /couldn't find|无法找到|该账号不存在/i.test(body);
        const hasLabel = /state.{0,10}(controlled|funded|media)|government.{0,10}media/i.test(body);
        return {
            notFound,
            followers: get('[data-e2e="followers-count"]'),
            likes: get('[data-e2e="likes-count"]'),
            nickname: get('[data-e2e="user-title"]'),
            bio: get('[data-e2e="user-bio"]'),
            hasLabel
        };
    }""")

    if info.get("notFound"):
        print("  [账号不存在]", flush=True)
        return None

    vc = get_video_count(page)
    print(f"  昵称: {info.get('nickname', '?')}", flush=True)
    print(f"  粉丝: {info.get('followers', '?')} | 获赞: {info.get('likes', '?')} | 视频总数: {vc}", flush=True)
    label = "YES [!]" if info.get("hasLabel") else "NO"
    print(f"  国家控制媒体标签: {label}", flush=True)
    print(f"  简介: {(info.get('bio') or '')[:80]}", flush=True)
    return {"username": username, "followers": info.get("followers","?"),
            "likes": info.get("likes","?"), "video_count": vc,
            "has_label": info.get("hasLabel", False)}


def main():
    print("启动 CloakBrowser ...", flush=True)
    browser = launch_persistent_context(user_data_dir=PROFILE, headless=False)
    page = browser.new_page()

    results = {}
    for display, username in ACCOUNTS:
        results[display] = check(page, display, username)

    page.close()
    browser.close()

    print("\n" + "=" * 72)
    print(f"{'媒体':<20} {'@账号':<24} {'粉丝':>8} {'视频数':>7} {'标签':>5}")
    print("=" * 72)
    for name, info in results.items():
        if not info:
            print(f"{name:<20} [未找到]")
        else:
            vc = str(info.get("video_count") or "?")
            label = "YES" if info.get("has_label") else " NO"
            print(f"{name:<20} @{info['username']:<23} {info['followers']:>8} {vc:>7} {label:>5}")
    print("=" * 72)


if __name__ == "__main__":
    main()
