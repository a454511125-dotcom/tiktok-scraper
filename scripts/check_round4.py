# -*- coding: utf-8 -*-
"""第四轮候选核查：RTE, SBS, KBS, 及其他小体量账号。"""
import io, os, sys, time, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根目录（脚本已归档至 scripts/）
sys.path.insert(0, BASE)
from cloakbrowser import launch_persistent_context

PROFILE = os.path.join(BASE, "_browser_profile")

CANDIDATES = [
    ("RTE News (爱尔兰公广)",     ["rtenews"]),
    ("SBS News AU (澳洲公广)",    ["sbsnews_au"]),
    ("KBS World (韩国公广)",      ["kbsworld", "kbsworldtv", "kbs_world"]),
    ("Arirang TV (韩国国际广播)", ["arirangtv_official", "arirang_tv", "arirangnews"]),
    ("SwissInfo EN (瑞士国际广播)", ["swissinfo_en", "swisspublicmedia"]),
    ("Al Arabiya English",        ["alarabiya_eng", "alarabiyaeng"]),
    ("Guardian (英国独立报纸)",   ["theguardian", "guardian"]),
]


def get_info(page, username):
    try:
        page.goto(f"https://www.tiktok.com/@{username}",
                  wait_until="domcontentloaded", timeout=25000)
    except Exception:
        pass
    time.sleep(7)

    info = page.evaluate("""() => {
        const get = sel => { const e = document.querySelector(sel); return e ? e.innerText.trim() : ""; };
        const body = document.body.innerText || "";
        const notFound = /couldn't find|无法找到|该账号不存在/i.test(body);
        if (notFound) return { notFound: true };
        const hasLabel = /state.{0,10}(controlled|funded|media)|government.{0,10}media/i.test(body);
        return {
            notFound: false,
            followers: get('[data-e2e="followers-count"]'),
            likes: get('[data-e2e="likes-count"]'),
            nickname: get('[data-e2e="user-title"]'),
            bio: get('[data-e2e="user-bio"]'),
            hasLabel
        };
    }""")

    if info.get("notFound") or not info.get("followers"):
        return None

    try:
        raw = page.evaluate("""() => {
            for (const s of document.querySelectorAll('script')) {
                if ((s.textContent||'').includes('videoCount')) return s.textContent;
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

    found = {}
    for display, usernames in CANDIDATES:
        print(f"\n=== {display} ===", flush=True)
        hit = None
        for uname in usernames:
            print(f"  @{uname} ...", flush=True)
            info = get_info(page, uname)
            if info:
                hit = info
                vc = info.get("video_count")
                print(f"  [OK] 粉丝={info['followers']} | 视频={vc or '?'} | 标签={'YES' if info['hasLabel'] else 'NO'}", flush=True)
                print(f"       简介: {(info.get('bio') or '')[:80]}", flush=True)
                break
            else:
                print(f"  [无效]", flush=True)
        found[display] = hit

    page.close()
    browser.close()

    print("\n" + "=" * 72)
    print(f"{'媒体':<24} {'@账号':<22} {'粉丝':>8} {'视频数':>7} {'标签':>5}")
    print("=" * 72)
    for name, info in found.items():
        if not info:
            print(f"{name:<24} [未找到]")
        else:
            vc = str(info.get("video_count") or "?")
            label = "YES" if info.get("hasLabel") else " NO"
            print(f"{name:<24} @{info['username']:<21} {info['followers']:>8} {vc:>7} {label:>5}")
    print("=" * 72)
    print("\n理想条件：粉丝 1-5M、视频 <3000、标签 NO、2021年前加入TikTok")


if __name__ == "__main__":
    main()
