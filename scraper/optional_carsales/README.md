# carsales.com.au 相場スナップショット（オプション・手動実行専用）

## 必ず読んでください

このフォルダのスクリプトは **GitHub Actionsの日次自動実行には含まれていません**。
意図的に外してあります。理由は次の2点です。

1. carsales.com.auは商用の分類広告サイトであり、利用規約で自動収集
   （スクレイピング・クローリング）が禁止されている可能性が高いです。
   非商用・個人利用であっても、規約違反のリスクはゼロにはなりません。
   実行する前に、必ずご自身でcarsales.com.auの最新の利用規約を確認し、
   問題がないと判断した場合のみ実行してください。
2. 「直近3週間の価格推移」を作るには、今日から3週間分スナップショットを
   積み重ねる必要があります。過去に遡って取得することはできません。

## 使い方（自己責任で）

```bash
cd scraper/optional_carsales
pip install -r ../requirements.txt
playwright install --with-deps chromium

# 例: Nissan Skyline GT-R (BNR32) の現在の出品を州別に記録
python snapshot_carsales.py \
  --sev-id "3b583516-515f-4796-a79a-2d7ed754c30d" \
  --search-url "https://www.carsales.com.au/cars/nissan/skyline/?..." \
  --out history/

# これを手元のPC/自分専用サーバーなどで週1〜3回、3週間以上続けたあと、
# 蓄積したスナップショットを site が読む形式にまとめる
python build_market_data.py --history history/ --out ../../data/market-data.json
```

`data/market-data.json` を生成してリポジトリにコミットすれば、サイトの
「州別マーケット価格」セクションが自動的に実データを表示するようになります。
コミットするかどうかも含めて、ご自身の判断で行ってください。
