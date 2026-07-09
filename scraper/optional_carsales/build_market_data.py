#!/usr/bin/env python3
"""
build_market_data.py — snapshot_carsales.py が蓄積したスナップショット群から、
サイトが読み込む data/market-data.json を組み立てる。

3週間（週1回以上）分のスナップショットが無い場合、直近4件をそのまま
週次点として扱います（間隔が不揃いでも動きますが、正確な「週」表示には
なりません）。

使い方:
    python build_market_data.py --history history/ --out ../../data/market-data.json
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

AU_STATE_NAMES = {
    "NSW": "ニューサウスウェールズ",
    "VIC": "ビクトリア",
    "QLD": "クイーンズランド",
    "WA": "西オーストラリア",
    "SA": "南オーストラリア",
    "TAS": "タスマニア",
    "ACT": "オーストラリア首都特別地域",
    "NT": "北部準州",
}


def build_for_sev(sev_dir):
    snapshots = sorted(sev_dir.glob("*.json"))
    if not snapshots:
        return None
    loaded = []
    for f in snapshots:
        with open(f, encoding="utf-8") as fh:
            loaded.append(json.load(fh))
    last4 = loaded[-4:]
    while len(last4) < 4:
        last4.insert(0, last4[0])  # データが足りない分は最古のスナップショットで埋める

    states_out = []
    for code, name in AU_STATE_NAMES.items():
        series = []
        counts = []
        for snap in last4:
            entry = snap.get("states", {}).get(code)
            if entry:
                series.append(entry["avgPrice"])
                counts.append(entry["count"])
            else:
                series.append(None)
                counts.append(0)
        if all(v is None for v in series):
            states_out.append({"code": code, "name": name, "count": 0, "prices": None})
            continue
        # 欠損は直前の値で埋める（無ければ直後の値）
        filled = []
        last_val = next((v for v in series if v is not None), 0)
        for v in series:
            if v is not None:
                last_val = v
            filled.append(last_val)
        states_out.append({
            "code": code, "name": name,
            "count": max(counts),
            "prices": filled,
        })

    with_data = [s for s in states_out if s["prices"]]
    agg = None
    if with_data:
        total_count = sum(s["count"] for s in with_data)
        if total_count > 0:
            current_weighted = sum(s["prices"][3] * s["count"] for s in with_data) / total_count
            past_weighted = sum(s["prices"][0] * s["count"] for s in with_data) / total_count
            agg = {
                "current": round(current_weighted),
                "deltaPct": ((current_weighted - past_weighted) / past_weighted * 100) if past_weighted else 0,
                "totalCount": total_count,
                "stateCount": len(with_data),
            }

    return {"states": states_out, "agg": agg}


def main():
    parser = argparse.ArgumentParser(description="Build data/market-data.json from carsales snapshots")
    parser.add_argument("--history", default="history/", help="snapshot_carsales.pyの出力ディレクトリ")
    parser.add_argument("--out", default="../../data/market-data.json")
    args = parser.parse_args()

    history_dir = Path(args.history)
    by_rover_id = {}
    for sev_dir in history_dir.iterdir():
        if not sev_dir.is_dir():
            continue
        result = build_for_sev(sev_dir)
        if result:
            by_rover_id[sev_dir.name] = result

    output = {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "note": "carsales.com.auスナップショットの手動集計（非自動化）。scraper/optional_carsales/README.md 参照。",
        "byRoverId": by_rover_id,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"wrote {len(by_rover_id)} vehicles' market data to {args.out}")


if __name__ == "__main__":
    main()
