#!/usr/bin/env python3
"""
scrape_rover.py — ROVER (Specialist and Enthusiast Vehicles Register) の一覧を
取得して data/sev-data.json 用のJSONを生成するスクレイパー。

重要な注意
----------
このスクリプトは開発時にライブブラウザでROVERサイトを直接確認しながら
書いたものではなく、Power Pages（旧Power Apps ポータル）系サイトの一般的な
構造を前提にしたベストエフォート実装です。実際にGitHub Actions等で初回実行
した際、以下の点でセレクタや挙動の調整が必要になる可能性が高いです:

  1. 検索結果グリッドを表示するために追加の操作（検索ボタンのクリック、
     フィルタの選択など）が必要な場合がある → find_results_table() 内の
     TODO を参照して調整してください。
  2. 列の並び順や列名（見出しテキスト)が異なる場合 → COLUMN_ALIASES を
     実際のヘッダー文言に合わせて追記してください。
  3. 一覧に「有効期限」「適合エンジン」「走行距離制限」に相当する列が
     そもそも存在しない可能性があります。その場合は詳細ページ
     (SEVDetails/?id=...) 側にある可能性が高いため、--with-details
     オプションで詳細ページも巡回し、ラベル文言から拾う実装にしてあります
     （scrape_detail_page() 参照）。それでも見つからない場合は null のまま
     出力され、サイト側は「情報なし」を表示します。

初回実行時は必ず --limit 5 --headful などスモールスケールで動作確認してから
本番の日次スケジュールに載せてください。

使い方
------
    pip install -r requirements.txt
    playwright install --with-deps chromium
    python scrape_rover.py --out ../data/sev-data.json
    python scrape_rover.py --out ../data/sev-data.json --with-details --limit 20 --headful
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

# 一覧テーブルの列見出し(小文字化・空白除去済み)から内部フィールド名へのマッピング。
# 実際のROVERの見出し文言を確認したら、ここに追記/修正してください。
COLUMN_ALIASES = {
    "make": "make",
    "manufacturer": "make",
    "model": "model",
    "category": "category",
    "vehiclecategory": "category",
    "modelcode": "code",
    "model code": "code",
    "sev#": "sev",
    "sevnumber": "sev",
    "sev no": "sev",
    "sev no.": "sev",
    "registrationnumber": "sev",
    "builddate": "year",
    "build date": "year",
    "buildyear": "year",
    "buildyears": "year",
}

# 詳細ページのラベルテキスト(小文字化)から内部フィールドへのマッピング。
# ここも実物を見て調整が必要です。
DETAIL_LABEL_ALIASES = {
    "mileage limit": "mileageLimit",
    "odometer limit": "mileageLimit",
    "km limit": "mileageLimit",
    "expiry date": "expiry",
    "expiry": "expiry",
    "approval expiry": "expiry",
    "engine": "engines_raw",
    "engine code": "engines_raw",
    "approved engines": "engines_raw",
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def normalize_header(text):
    return re.sub(r"\s+", "", text.strip().lower())


def normalize_label(text):
    return re.sub(r"\s+", " ", text.strip().lower())


async def find_results_table(page):
    """検索結果テーブルが表示されるまで待つ。必要なら検索/表示ボタンを押す。"""
    # 何もしなくてもデフォルトで一覧が表示されるページも多いため、まず素直に待つ。
    try:
        await page.wait_for_selector("table tbody tr", timeout=8000)
        return
    except PlaywrightTimeoutError:
        pass

    # TODO: 実際のサイトで「検索」「すべて表示」に相当するボタンがあれば
    # ここでクリックする。候補になりそうなテキストを順番に試す。
    candidate_texts = ["Search", "Show all", "View all", "Submit", "検索"]
    for text in candidate_texts:
        try:
            btn = page.get_by_role("button", name=re.compile(text, re.I))
            if await btn.count() > 0:
                await btn.first.click()
                await page.wait_for_selector("table tbody tr", timeout=10000)
                return
        except PlaywrightTimeoutError:
            continue
        except Exception:
            continue

    # それでも見つからなければ例外を送出し、呼び出し側でログを出す。
    raise RuntimeError(
        "結果テーブルが見つかりませんでした。ROVERサイトのUIが想定と異なる可能性があります。"
        "--headful で実行し、実際の画面を確認して find_results_table() を調整してください。"
    )


async def extract_row_link_id(row):
    """行内のリンク(詳細ページへのhref)から id= のGUIDを取り出す。"""
    link = row.locator("a").first
    if await link.count() == 0:
        return None
    href = await link.get_attribute("href")
    if not href:
        return None
    full = urljoin(BASE_URL, href)
    qs = parse_qs(urlparse(full).query)
    if "id" in qs and qs["id"]:
        return qs["id"][0]
    return None


async def scrape_list_page(page):
    """現在表示中の1ページ分の結果テーブルを構造化データに変換する。"""
    header_cells = await page.locator("table thead th").all_inner_texts()
    field_order = [COLUMN_ALIASES.get(normalize_header(h)) for h in header_cells]

    rows = page.locator("table tbody tr")
    count = await rows.count()
    results = []
    for i in range(count):
        row = rows.nth(i)
        cells = await row.locator("td").all_inner_texts()
        record = {}
        for idx, field in enumerate(field_order):
            if field and idx < len(cells):
                record[field] = cells[idx].strip()
        rover_id = await extract_row_link_id(row)
        if rover_id:
            record["roverId"] = rover_id
        if record:
            results.append(record)
    return results


async def go_to_next_page(page):
    """次ページへのページネーション操作。無ければ False を返す。"""
    # 一般的なPower Pagesのページネーションは "Next" リンク/ボタン。
    for name in ["Next", "次へ", ">"]:
        try:
            btn = page.get_by_role("link", name=re.compile(f"^{re.escape(name)}$", re.I))
            if await btn.count() == 0:
                btn = page.get_by_role("button", name=re.compile(f"^{re.escape(name)}$", re.I))
            if await btn.count() > 0:
                disabled = await btn.first.get_attribute("aria-disabled")
                classes = await btn.first.get_attribute("class") or ""
                if disabled == "true" or "disabled" in classes:
                    return False
                await btn.first.click()
                await page.wait_for_timeout(1500)
                await page.wait_for_selector("table tbody tr", timeout=10000)
                return True
        except Exception:
            continue
    return False


async def scrape_detail_page(context, rover_id):
    """詳細ページを開いて、ラベル/値のペアをできる限り拾う。"""
    url = f"{BASE_URL}/PublishedApprovals/SEVDetails/?id={rover_id}"
    page = await context.new_page()
    extracted = {}
    try:
        await page.goto(url, wait_until="networkidle", timeout=20000)
        # dl/dt/dd, または label的なdiv構造を両方試す generic 抽出。
        pairs = await page.evaluate(
            """
            () => {
                const out = [];
                document.querySelectorAll('dt').forEach(dt => {
                    const dd = dt.nextElementSibling;
                    if (dd && dd.tagName === 'DD') {
                        out.push([dt.innerText, dd.innerText]);
                    }
                });
                document.querySelectorAll('[class*="label"], [class*="Label"]').forEach(el => {
                    const label = el.innerText;
                    const sibling = el.nextElementSibling;
                    if (label && sibling && sibling.innerText) {
                        out.push([label, sibling.innerText]);
                    }
                });
                return out;
            }
            """
        )
        raw = {}
        for label, value in pairs:
            key = normalize_label(label)
            raw[key] = value.strip()
            mapped = DETAIL_LABEL_ALIASES.get(key)
            if mapped:
                extracted[mapped] = value.strip()
        extracted["raw"] = raw
    except Exception as e:
        extracted["_detailError"] = str(e)
    finally:
        await page.close()
    return extracted


def parse_engines_raw(text):
    """'RB26DETT (OK), RB20DET (対象外)' のような自由記述をベストエフォートで
    engines: [{code, ok}] に変換する。パターンに合わなければ code のみのリストにする。"""
    if not text:
        return []
    parts = re.split(r"[,、/]", text)
    engines = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        ok = not re.search(r"(not approved|対象外|ng|✕|✗)", part, re.I)
        code = re.sub(r"\(.*?\)", "", part).strip()
        engines.append({"code": code, "ok": ok})
    return engines


async def run(out_path, with_details, limit, headful, max_pages):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not headful)
        context = await browser.new_context()
        page = await context.new_page()

        print(f"[scrape_rover] opening {LIST_URL}", file=sys.stderr)
        await page.goto(LIST_URL, wait_until="networkidle", timeout=30000)
        await find_results_table(page)

        all_records = []
        page_num = 1
        while True:
            print(f"[scrape_rover] scraping list page {page_num}", file=sys.stderr)
            records = await scrape_list_page(page)
            all_records.extend(records)
            if limit and len(all_records) >= limit:
                all_records = all_records[:limit]
                break
            if page_num >= max_pages:
                print(f"[scrape_rover] reached max_pages={max_pages}, stopping", file=sys.stderr)
                break
            moved = await go_to_next_page(page)
            if not moved:
                break
            page_num += 1

        print(f"[scrape_rover] collected {len(all_records)} list rows", file=sys.stderr)

        if with_details:
            for i, rec in enumerate(all_records):
                rover_id = rec.get("roverId")
                if not rover_id:
                    continue
                print(f"[scrape_rover] detail {i+1}/{len(all_records)}: {rover_id}", file=sys.stderr)
                detail = await scrape_detail_page(context, rover_id)
                if "engines_raw" in detail:
                    rec["engines"] = parse_engines_raw(detail.pop("engines_raw"))
                for k in ("mileageLimit", "expiry"):
                    if k in detail:
                        rec[k] = detail[k]
                rec["_detailRaw"] = detail.get("raw", {})
                await page.wait_for_timeout(300)  # サイトへの負荷を抑えるための小休止

        await browser.close()

    output = {
        "updatedAt": now_iso(),
        "source": LIST_URL,
        "count": len(all_records),
        "vehicles": all_records,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"[scrape_rover] wrote {len(all_records)} vehicles to {out_path}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Scrape ROVER SEV Approvals list")
    parser.add_argument("--out", default="../data/sev-data.json", help="output JSON path")
    parser.add_argument("--with-details", action="store_true", help="detail pages also visit")
    parser.add_argument("--limit", type=int, default=0, help="max vehicles to scrape (0 = no limit)")
    parser.add_argument("--headful", action="store_true", help="run with a visible browser (debugging)")
    parser.add_argument("--max-pages", type=int, default=500, help="safety cap on list pagination")
    args = parser.parse_args()

    asyncio.run(run(args.out, args.with_details, args.limit, args.headful, args.max_pages))


if __name__ == "__main__":
    main()
