#!/usr/bin/env python3
"""
scrape_rover.py — ROVER (Specialist and Enthusiast Vehicles Register) の一覧を
取得して data/sev-data.json 用のJSONを生成するスクレイパー。(version 3)

実際のROVER一覧の列構成（スクリーンショットで確認済み）:
    SEV番号(リンク) | メーカー | モデル | カテゴリ | 型式 | 製造開始(MM/YYYY)
    | 製造終了(MM/YYYY または "No end date") | 期限日(DD/MM/YYYY) | 展開ボタン

このバージョンでは列見出しの文言に頼らず、各セルの中身のパターン
（"SEV-" で始まる、日付形式など）からフィールドを自動判別します。
ページ送りは数字リンク（1 2 3 ... 60 >）方式に対応しています。

使い方
------
    pip install -r requirements.txt
    playwright install --with-deps chromium
    python scrape_rover.py --out ../data/sev-data.json
    python scrape_rover.py --out ../data/sev-data.json --limit 20 --headful
"""

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, parse_qs

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

BASE_URL = "https://www.rover.infrastructure.gov.au"
LIST_URL = f"{BASE_URL}/PublishedApprovals/SEVApprovals/"

# セル内容のパターン
RE_SEV = re.compile(r"^SEV-\d+", re.I)
RE_MONTH_YEAR = re.compile(r"^(\d{1,2})/(\d{4})$")          # 例: 08/2018
RE_FULL_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")  # 例: 16/07/2026
RE_NO_END = re.compile(r"^no\s*end\s*date$", re.I)
# カテゴリ例: "NA - Light Goods Vehicle", "LC - Motor Cycle"
RE_CATEGORY = re.compile(r"^[A-Z]{1,2}\d?\s*-\s*.+", re.I)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def to_iso_date(dd, mm, yyyy):
    return f"{int(yyyy):04d}-{int(mm):02d}-{int(dd):02d}"


async def find_results_table(page):
    """検索結果テーブルが表示されるまで待つ。必要なら検索ボタンを押す。"""
    try:
        await page.wait_for_selector("table tbody tr", timeout=15000)
        return
    except PlaywrightTimeoutError:
        pass

    for text in ["Search", "Show all", "View all", "Submit", "検索"]:
        try:
            btn = page.get_by_role("button", name=re.compile(text, re.I))
            if await btn.count() > 0:
                await btn.first.click()
                await page.wait_for_selector("table tbody tr", timeout=15000)
                return
        except Exception:
            continue

    raise RuntimeError(
        "結果テーブルが見つかりませんでした。--headful で実行して画面を確認してください。"
    )


async def extract_row_link_id(row):
    """行内のリンク(詳細ページへのhref)から id= のGUIDを取り出す。"""
    links = row.locator("a")
    n = await links.count()
    for i in range(n):
        href = await links.nth(i).get_attribute("href")
        if not href:
            continue
        full = urljoin(BASE_URL, href)
        qs = parse_qs(urlparse(full).query)
        if "id" in qs and qs["id"]:
            return qs["id"][0]
    return None


def classify_cells(cells):
    """セル配列を中身のパターンで分類して record を組み立てる。

    想定順: [SEV番号, メーカー, モデル, カテゴリ, 型式, 製造開始, 製造終了, 期限日, (空/ボタン列)]
    ただし順番が多少変わっても動くよう、パターン優先で判定する。
    """
    record = {}
    month_years = []   # MM/YYYY 形式（製造開始/終了）
    no_end = False
    texts = [c.strip() for c in cells]

    sev_idx = None
    cat_idx = None

    for idx, t in enumerate(texts):
        if not t:
            continue
        if sev_idx is None and RE_SEV.match(t):
            record["sev"] = t
            sev_idx = idx
            continue
        m = RE_FULL_DATE.match(t)
        if m:
            record["expiry"] = to_iso_date(m.group(1), m.group(2), m.group(3))
            continue
        m = RE_MONTH_YEAR.match(t)
        if m:
            month_years.append((int(m.group(1)), int(m.group(2))))
            continue
        if RE_NO_END.match(t):
            no_end = True
            continue
        if cat_idx is None and RE_CATEGORY.match(t) and len(t) > 6:
            record["category"] = t
            cat_idx = idx
            continue

    # メーカー/モデル: SEV番号セルの直後2つ（無ければ先頭2つの非日付セル）
    if sev_idx is not None:
        if sev_idx + 1 < len(texts) and texts[sev_idx + 1]:
            record["make"] = texts[sev_idx + 1]
        if sev_idx + 2 < len(texts) and texts[sev_idx + 2]:
            record["model"] = texts[sev_idx + 2]

    # 型式: カテゴリセルの直後
    if cat_idx is not None and cat_idx + 1 < len(texts) and texts[cat_idx + 1]:
        candidate = texts[cat_idx + 1]
        if not RE_MONTH_YEAR.match(candidate) and not RE_FULL_DATE.match(candidate) and not RE_NO_END.match(candidate):
            record["code"] = candidate

    # 年式: 製造開始〜終了
    if month_years:
        start_year = month_years[0][1]
        record["buildStart"] = f"{month_years[0][1]:04d}-{month_years[0][0]:02d}"
        if len(month_years) >= 2:
            end_year = month_years[1][1]
            record["buildEnd"] = f"{month_years[1][1]:04d}-{month_years[1][0]:02d}"
            record["year"] = f"{start_year}–{end_year}" if start_year != end_year else f"{start_year}"
        elif no_end:
            record["year"] = f"{start_year}"
            record["buildEnd"] = None
        else:
            record["year"] = f"{start_year}"

    return record


async def scrape_list_page(page, log_sample=False):
    """現在表示中の1ページ分の結果テーブルを構造化データに変換する。"""
    rows = page.locator("table tbody tr")
    count = await rows.count()
    results = []
    for i in range(count):
        row = rows.nth(i)
        cells = await row.locator("td").all_inner_texts()
        record = classify_cells(cells)
        rover_id = await extract_row_link_id(row)
        if rover_id:
            record["roverId"] = rover_id
        if log_sample and i < 2:
            print(f"[scrape_rover] sample raw cells: {[c.strip() for c in cells]}", file=sys.stderr)
            print(f"[scrape_rover] sample parsed:    {record}", file=sys.stderr)
        # SEV番号かroverIdのどちらかが取れている行だけを有効とみなす
        if record.get("sev") or record.get("roverId"):
            results.append(record)
    return results


async def first_row_signature(page):
    """ページが切り替わったことを検知するための、先頭行のテキスト。"""
    try:
        row = page.locator("table tbody tr").first
        return (await row.inner_text()).strip()[:120]
    except Exception:
        return ""


async def wait_for_page_change(page, old_signature, timeout_ms=10000):
    """先頭行の内容が変わるまで待つ。変わったらTrue。"""
    elapsed = 0
    step = 400
    while elapsed < timeout_ms:
        await page.wait_for_timeout(step)
        elapsed += step
        sig = await first_row_signature(page)
        if sig and sig != old_signature:
            return True
    return False


async def go_to_next_page(page, current_page_num):
    """次ページへ移動。成功したらTrue。数字リンク（1 2 3 ... >）方式に対応。"""
    old_sig = await first_row_signature(page)
    next_num = str(current_page_num + 1)

    # 方式1: 「>」やNextの明示的なリンク/ボタン
    for name in [">", "Next", "Next page", "次へ"]:
        for role in ("link", "button"):
            try:
                btn = page.get_by_role(role, name=re.compile(f"^{re.escape(name)}$", re.I))
                if await btn.count() > 0:
                    first = btn.first
                    classes = ((await first.get_attribute("class")) or "").lower()
                    aria_dis = await first.get_attribute("aria-disabled")
                    if "disabled" in classes or aria_dis == "true":
                        continue
                    await first.click()
                    if await wait_for_page_change(page, old_sig):
                        print(f"[scrape_rover] pagination: clicked '{name}' ({role}) -> page {next_num}", file=sys.stderr)
                        return True
            except Exception:
                continue

    # 方式2: 次のページ番号のリンク
    try:
        num_link = page.get_by_role("link", name=re.compile(f"^{next_num}$"))
        if await num_link.count() > 0:
            await num_link.first.click()
            if await wait_for_page_change(page, old_sig):
                print(f"[scrape_rover] pagination: clicked number '{next_num}'", file=sys.stderr)
                return True
    except Exception:
        pass

    # 方式3: role判定が効かないUI向けに、テキスト完全一致の任意要素をクリック
    for target in [">", next_num]:
        try:
            el = page.locator(f"text=/^{re.escape(target)}$/").last
            if await el.count() > 0:
                await el.click()
                if await wait_for_page_change(page, old_sig):
                    print(f"[scrape_rover] pagination: clicked text '{target}'", file=sys.stderr)
                    return True
        except Exception:
            continue

    print(
        f"[scrape_rover] pagination: could not move past page {current_page_num}. "
        "If the register has more pages, run with --headful and inspect the pager UI.",
        file=sys.stderr,
    )
    return False


async def run(out_path, limit, headful, max_pages):
    print("[scrape_rover] version 3 (content-based extraction)", file=sys.stderr)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not headful)
        context = await browser.new_context()
        page = await context.new_page()

        print(f"[scrape_rover] opening {LIST_URL}", file=sys.stderr)
        await page.goto(LIST_URL, wait_until="networkidle", timeout=45000)
        await find_results_table(page)

        all_records = []
        seen_ids = set()
        page_num = 1
        while True:
            records = await scrape_list_page(page, log_sample=(page_num == 1))
            new_count = 0
            for rec in records:
                key = rec.get("roverId") or rec.get("sev")
                if key and key in seen_ids:
                    continue
                if key:
                    seen_ids.add(key)
                all_records.append(rec)
                new_count += 1
            print(f"[scrape_rover] page {page_num}: {len(records)} rows ({new_count} new, total {len(all_records)})", file=sys.stderr)

            if limit and len(all_records) >= limit:
                all_records = all_records[:limit]
                break
            if page_num >= max_pages:
                print(f"[scrape_rover] reached max_pages={max_pages}, stopping", file=sys.stderr)
                break
            moved = await go_to_next_page(page, page_num)
            if not moved:
                break
            page_num += 1
            await page.wait_for_timeout(400)  # サイトへの負荷を抑える小休止

        await browser.close()

    sev_count = sum(1 for r in all_records if r.get("sev"))
    expiry_count = sum(1 for r in all_records if r.get("expiry"))
    print(
        f"[scrape_rover] done: {len(all_records)} vehicles "
        f"(with SEV number: {sev_count}, with expiry: {expiry_count})",
        file=sys.stderr,
    )

    output = {
        "updatedAt": now_iso(),
        "source": LIST_URL,
        "count": len(all_records),
        "vehicles": all_records,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"[scrape_rover] wrote {out_path}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Scrape ROVER SEV Approvals list (v3)")
    parser.add_argument("--out", default="../data/sev-data.json", help="output JSON path")
    parser.add_argument("--limit", type=int, default=0, help="max vehicles to scrape (0 = no limit)")
    parser.add_argument("--headful", action="store_true", help="run with a visible browser (debugging)")
    parser.add_argument("--max-pages", type=int, default=200, help="safety cap on list pagination")
    args = parser.parse_args()

    asyncio.run(run(args.out, args.limit, args.headful, args.max_pages))


if __name__ == "__main__":
    main()
