#!/usr/bin/env python3
"""
snapshot_carsales.py — carsales.com.au の検索結果ページから、現在の出品を
州別に集計して1回分の「スナップショット」として保存する。

*** 実行前に必ず scraper/optional_carsales/README.md を読んでください ***
このスクリプトはGitHub Actionsの自動実行には含まれておらず、実行するかどうか、
その頻度は利用者自身の判断・責任で決めてください。

このスクリプトは carsales.com.au の実際のDOM構造をライブで確認せずに
書かれたベストエフォート実装です。実行してもリスティングが0件しか
取れない場合は、--headful で開いて実際のセレクタを見ながら
extract_listings() を調整してください。

使い方:
    python snapshot_carsales.py \
        --sev-id "<ROVERのGUID>" \
        --search-url "https://www.carsales.com.au/cars/..." \
        --out history/
"""

import argparse
import asyncio
import json
import re
import sys
from datetime import date
from pathlib import Path

from playwright.async_api import async_playwright

# carsales上の州表記 → 内部コードの対応（サフィックス表記ゆれをある程度吸収）
STATE_MAP = {
    "nsw": "NSW", "new south wales": "NSW",
    "vic": "VIC", "victoria": "VIC",
    "qld": "QLD", "queensland": "QLD",
    "wa": "WA", "western australia": "WA",
    "sa": "SA", "south australia": "SA",
    "tas": "TAS", "tasmania": "TAS",
    "act": "ACT", "australian capital territory": "ACT",
    "nt": "NT", "northern territory": "NT",
}


def guess_state(text):
    t = text.strip().lower()
    for key, code in STATE_MAP.items():
        if re.search(rf"\b{re.escape(key)}\b", t):
            return code
    return None


def parse_price(text):
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else None


async def extract_listings(page):
    """検索結果ページから (price, state) のリストを抽出する。
    TODO: 実際のcarsalesのDOM構造に合わせてセレクタを調整すること。"""
    listings = []
    cards = page.locator("[class*='listing'], [class*='card'], article")
    count = await cards.count()
    for i in range(count):
        card = cards.nth(i)
        text = (await card.inner_text()) if await card.count() else ""
        price = None
        price_match = re.search(r"\$[\d,]+", text)
        if price_match:
            price = parse_price(price_match.group(0))
        state = guess_state(text)
        if price and state:
            listings.append({"price": price, "state": state})
    return listings


async def run(sev_id, search_url, out_dir, headful):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not headful)
        page = await browser.new_page()
        print(f"[snapshot_carsales] opening {search_url}", file=sys.stderr)
        await page.goto(search_url, wait_until="networkidle", timeout=30000)
        listings = await extract_listings(page)
        await browser.close()

    by_state = {}
    for item in listings:
        by_state.setdefault(item["state"], []).append(item["price"])

    states_summary = {
        code: {"avgPrice": round(sum(prices) / len(prices)), "count": len(prices)}
        for code, prices in by_state.items()
    }

    out_path = Path(out_dir) / sev_id
    out_path.mkdir(parents=True, exist_ok=True)
    snapshot_file = out_path / f"{date.today().isoformat()}.json"
    with open(snapshot_file, "w", encoding="utf-8") as f:
        json.dump({"date": date.today().isoformat(), "states": states_summary}, f, ensure_ascii=False, indent=2)

    print(f"[snapshot_carsales] {len(listings)} listings -> {snapshot_file}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Snapshot carsales.com.au listings by state (manual/optional)")
    parser.add_argument("--sev-id", required=True, help="このスナップショットが対応するROVERのroverId")
    parser.add_argument("--search-url", required=True, help="carsales.com.auの検索結果URL")
    parser.add_argument("--out", default="history/", help="スナップショット保存先ディレクトリ")
    parser.add_argument("--headful", action="store_true")
    args = parser.parse_args()

    asyncio.run(run(args.sev_id, args.search_url, args.out, args.headful))


if __name__ == "__main__":
    main()
