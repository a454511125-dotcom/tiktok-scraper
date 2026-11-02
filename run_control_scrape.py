# -*- coding: utf-8 -*-
"""命令行包装：用 tiktok-scraper 的 CloakBrowser + 已登录 profile 采集对照组账号。
用法：.venv\\Scripts\\python.exe run_control_scrape.py <account1> <account2> ...
"""
import sys
import os

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from scraper import TikTokScraper

profile = os.path.join(BASE, "_browser_profile")
output = os.path.join(BASE, "data")
os.makedirs(output, exist_ok=True)


def emit(event, **kw):
    print(f"[{event}] {kw}", flush=True)


def main():
    accounts = sys.argv[1:]
    if not accounts:
        print("用法: python run_control_scrape.py <account> ...", flush=True)
        return
    print(f"采集账号: {accounts}", flush=True)
    print(f"profile: {profile}", flush=True)
    print(f"output : {output}", flush=True)
    s = TikTokScraper(profile, output, emit=emit)
    s.scrape_accounts(accounts)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
