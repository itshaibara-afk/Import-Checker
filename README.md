# SEV検索（非公式ミラー）

オーストラリア政府のROVER（[Specialist and Enthusiast Vehicles Register](https://www.rover.infrastructure.gov.au/PublishedApprovals/SEVApprovals/)）
を検索しやすくした非公式サイトです。GitHub Actionsで毎日自動的にデータを
取得し、GitHub Pagesで無料公開できるように構成してあります。

**このプロジェクトは政府の公式サイトではありません。** 実際の輸入可否判断は
必ずROVER公式サイトで確認してください。

## 構成

```
sev-register/
├── .github/workflows/update-and-deploy.yml   毎日の自動取得＋公開
├── scraper/
│   ├── scrape_rover.py       ROVER一覧の自動取得スクリプト（本番で使用）
│   ├── requirements.txt
│   └── optional_carsales/    carsales.com.au相場データ（手動・任意・要注意）
├── data/
│   ├── sev-data.json         ROVERデータ（自動更新される。今はシードデータ入り）
│   └── market-data.json      相場データ（任意。無くても動く）
├── site/
│   └── index.html            検索サイト本体（このファイル1つで完結）
└── README.md                 このファイル
```

## セットアップ手順

### 1. GitHubリポジトリを作る

GitHub上で新しいリポジトリを作成し（Public推奨。Privateだと無料枠でも
GitHub Pagesは使えますが設定がやや異なります）、このフォルダの中身を
すべてそのリポジトリにpushしてください。

```bash
cd sev-register
git init
git add .
git commit -m "init: SEV register mirror site"
git branch -M main
git remote add origin https://github.com/<あなたのユーザー名>/<リポジトリ名>.git
git push -u origin main
```

### 2. GitHub Pagesを有効にする

リポジトリの **Settings → Pages** を開き、Source を
**「GitHub Actions」** に設定してください（「Deploy from a branch」ではない
方です）。

### 3. Actionsに書き込み権限を与える

リポジトリの **Settings → Actions → General → Workflow permissions** で
**「Read and write permissions」** を選択して保存してください。
これがないと、毎日のデータ更新をActionsがリポジトリにコミットできません。

### 4. ワークフローを起動する

**Actions** タブ → 「Update SEV data and deploy」→ 「Run workflow」で
手動実行してみてください。成功すると:

- `data/sev-data.json` が実データで上書きされてコミットされる
- GitHub Pagesにサイトが公開される（URLは Settings → Pages に表示されます）

その後は毎日自動的に（UTC 19:00 = 豪州東部時間の朝5時ごろ）実行されます。
スケジュールを変えたい場合は `.github/workflows/update-and-deploy.yml` の
`cron` の値を書き換えてください。

## 重要: ROVERスクレイパーは初回実行時に調整が必要な可能性が高いです

`scraper/scrape_rover.py` は、ROVERサイトを実際にブラウザで操作しながら
作ったものではなく、Power Pages（旧Power Apps ポータル）系サイトの一般的な
構造を前提にしたベストエフォート実装です。初回実行のログを確認し、

- 結果が0件になる → `find_results_table()` を調整（検索ボタンのクリックが
  必要な場合など）
- 列がずれる／文字化けする → `COLUMN_ALIASES` を実際の見出し文言に合わせる
- 有効期限・適合エンジン・走行距離制限が取れない → そもそもROVERの一覧/詳細
  ページにその情報が無い可能性があります。詳細ページ側のラベル文言を確認して
  `DETAIL_LABEL_ALIASES` を調整してください

Actionsのログ（`scrape` ジョブ）にスクリプトの標準エラー出力が表示される
ので、そこで状況を確認できます。ローカルで `--headful` オプション付きで
実行すると、実際にブラウザが開いて動きを目で確認できます。

```bash
cd scraper
pip install -r requirements.txt
playwright install chromium
python scrape_rover.py --out ../data/sev-data.json --limit 5 --headful
```

## 相場価格（州別マーケット価格）について

前回のやり取りでお伝えした通り、carsales.com.auのような商用サイトを
無断で自動スクレイピングするのは利用規約違反のリスクがあります。そのため、
このプロジェクトの **日次自動更新には carsales データを含めていません。**

サイト側（`site/index.html`）は `data/market-data.json` が存在すれば
それを表示し、無ければ「相場データはまだありません」と表示するだけなので、
このファイルが無くてもサイトは正常に動きます。

もし相場情報も載せたい場合は、`scraper/optional_carsales/README.md` を
必ず読んだ上で、ご自身の判断・責任で手動運用してください（GitHub Actionsには
組み込まれていません）。

## サイトのカスタマイズ

`site/index.html` は1ファイル完結のHTMLです。色・文言・カテゴリ分けなどは
このファイル内のCSS変数（`:root` 内）やJavaScriptの表示ロジックを直接
編集してください。デザインの元になっているサンプル版と同じ構造なので、
これまで確認してきた挙動（あいまい検索・詳細パネル・類似車両・ダーク
モードなど）はそのまま引き継がれています。

## トラブルシューティング

- **サイトを開くと「データを読み込めませんでした」と出る** →
  まだActionsが一度も成功していません。Actionsタブでエラーログを確認して
  ください。
- **GitHub Pagesのページが真っ白 / 404** → Settings → Pages の Source が
  「GitHub Actions」になっているか確認してください。
- **毎日自動更新されない** → Settings → Actions で Workflow permissions が
  「Read and write」になっているか、また cron のタイムゾーンはUTCである点を
  確認してください。
