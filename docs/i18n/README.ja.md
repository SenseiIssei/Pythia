# Pythia

[English](../../README.md) · [Deutsch](README.de.md) · [简体中文](README.zh-CN.md) · 日本語 · [한국어](README.ko.md) · [Español](README.es.md) · [Français](README.fr.md) · [Português](README.pt-BR.md)

Pythia はペーパートレードから始まり、戦略が実力を示すまでペーパーのままでいるトレーディング・コックピットです。Rust のエンジン、その上で動くデスクトップアプリと Web UI、そしてエンジンが何を取引してよいかを決める Python の研究ラボで構成されています。ラボはこれまでに試したすべてのアイデアを数えているので、たまたま当たったバックテストが通り抜けることはありません。

ここにある戦略で利益が出ると証明されたものはありません。実口座をつなぐ前に [SAFETY.md](../../SAFETY.md)（英語）を読んでください。

<table>
  <tr>
    <td width="50%"><img src="../img/app-home.png" alt="ホーム画面"></td>
    <td width="50%"><img src="../img/app-autopilot.png" alt="オートパイロット画面"></td>
  </tr>
</table>

サンプルデータを使った開発ビルドのスクリーンショットです。

## できること

- オートパイロットは、止めるかストップルールが発動するまで一つの戦略を自動で取引する資金枠です。複数を並べて動かせ、それぞれ BTC と比較して評価されます。
- 暗号資産、米国株、ETF は Alpaca のペーパー口座で取引します。ロング/ショートのブックはペーパーで無期限先物を取引し、デモキーを設定すれば Bybit のデモ口座でも取引できます。
- すべての注文の前にリスクマネージャーがあります。キルスイッチ、日次損失とドローダウンの上限、エクスポージャー上限、ボラティリティ・ターゲティング。判断がつかないときは注文を拒否します。
- ラボの研究はすべて最初の実行前に計画を登録し、コスト控除後にアウト・オブ・サンプルで検証し、これまでの試行回数に応じてシャープレシオを割り引きます（deflated Sharpe）。
- モデル（ボラティリティ、銘柄ランキング、リターン分位点）はラボで学習し、エンジンで実行します。取引に影響する前に、まずシャドーモードで動きます。
- 通知は Telegram または任意の Webhook に、英語かドイツ語で届きます。

## アーキテクチャ

<img src="../img/architecture.svg" alt="Pythia：上に UI、その下に Rust エンジン、さらに研究ラボとレコーダー、一番下にマーケット" width="100%">

ラボのブックは、その根拠と一緒でなければオートパイロットに渡りません。自動選択は根拠とフォワード成績でブックを順位づけし、実験的なブックはオートパイロットが名指しした場合にだけ動きます。

## これまでの結果

数字はすべてラボの結果ファイルかエンジン自身の記録から取っています。下のグラフはすべて [`scripts/readme_charts.py`](../../scripts/readme_charts.py) が描き、出典も記しています。

<img src="../img/scoreboard.png" alt="検証した戦略のアウト・オブ・サンプルのシャープレシオ" width="100%">

最も成績の良いブックは、流動性上位 10 銘柄でのドンチャン・ブレイクアウトです。2024 年以降のシャープレシオは 1.17 で、BTC の保有は 0.74 でした。それでも割り引き後の検定には通りません。1,836 回の試行を数えると、同じ数の純粋なノイズ戦略のうち最良のものでも約 2.69 を示すからです。

無期限先物のロング/ショート研究が二つ、事前登録した検定に通りました（M4 残差とファンディング・キャリー）。どちらも割り引き後には残らないため、実験としてのみ動かしています。モメンタム系ブックの多くは、実は BTC の 200 日移動平均フィルターの言い換えでした。フィルターがオフの日には、どれも損失を出しています。

<img src="../img/forward.png" alt="2026 年 10 月 15 日以降のペーパー・オートパイロットのフォワード成績" width="100%">

ペーパーのオートパイロットは 2026 年 10 月 15 日に始まりました。6 日後の時点で、メインの自動選択は +0.48 %、BTC は +3.22 % です。何かを判断するには短すぎますが、記録を初日から公開するためにグラフを載せています。

<img src="../img/research_funnel.png" alt="試行回数の推移とすべての研究の判定" width="100%">

これまでの研究は 69 件です。43 件は失敗または中止、7 件はラベル付きの実験としてペーパーで稼働、2 件は事前登録どおり合格したものの未確認、5 件はベースラインを上回るモデルを生みました。すべての判定は [`research/lab/README.md`](../../research/lab/README.md) にあります。

<img src="../img/by_year.png" alt="稼働中のブックの年ごとのシャープレシオ" width="100%">

グラフを描き直すには：

```bash
pip install matplotlib
PYTHIA_DATA=/path/to/lab/data python scripts/readme_charts.py
```

`PYTHIA_DATA` がない場合、フォワード成績のグラフは省略されます。

## はじめに

Node.js（現行 LTS）、Rust 1.85 以降、ラボには Python 3 が必要です。

デスクトップアプリ：

```bash
npm install
npm run tauri dev
npm run tauri build
```

サーバーと Web UI：

```bash
cp .env.example .env
npm run server
```

```bash
echo "VITE_PYTHIA_SERVER=http://localhost:8787" > .env.local
npm run dev
```

サーバーは `127.0.0.1:8787` で待ち受けます（`PYTHIA_BIND` で変更可能）。`.env` のキーは任意で、なければすべてペーパーのままです。`VITE_PYTHIA_SERVER` がなければ、Web UI はブラウザ内の小さなペーパーエンジンで動きます。

研究ラボ：

```bash
cd research/lab
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m pytest tests
```

データは `research/recorder` のレコーダーと、その履歴バックフィルから来ます。[`research/lab/README.md`](../../research/lab/README.md) にすべての研究が、[`research/ops/README.md`](../../research/ops/README.md) に定期ジョブが載っています。

チェック：

```bash
npm run check
npm run preflight
npm run security:scan
```

Windows では、スペースを含むパスが Rust のネイティブビルドを壊すため、npm スクリプトが環境から `CC` と `CXX` を取り除きます。

## ディレクトリ構成

| パス | 内容 |
|---|---|
| [`crates/pythia-core`](../../crates/pythia-core) | エンジン：戦略、リスク、オートパイロット、執行、取引所、予測、通知 |
| [`crates/pythia-ml`](../../crates/pythia-ml) | モデル推論（LightGBM、ONNX）とラボとの一致テスト |
| [`server`](../../server) | エンジン上の HTTP / WebSocket サーバー |
| [`src-tauri`](../../src-tauri) | デスクトップアプリ |
| [`src`](../../src) | React UI |
| [`research/lab`](../../research/lab/README.md) | 研究、モデル、ペーパーブック、戦略ファクトリー |
| [`research/recorder`](../../research/recorder/README.md) | 市場データのレコーダーと履歴バックフィル |
| [`research/ops`](../../research/ops/README.md) | ジョブ表、ヘルスチェック、デプロイスクリプト |
| [`docs`](..) | [デモ取引](../DEMO.md)、[実運用](../LIVE-RUN.md)、[通知](../ALERTS.md)、[モデル](../MODELS.md)、[Claude API](../AI.md)、[準備ルール](../LIVE-READINESS.md)の手順書（英語） |

## 安全性

- 新規インストールでは実際の取引は一切行いません。オートパイロットはペーパーか取引所のデモ口座で始まります。
- 実取引には自分のキーと、取引所ごとに入力する確認が必要です。勝手に有効になるものはありません。
- キーは OS のキーチェーンかサーバーの環境変数に保存され、ログに出ることも UI に送られることもありません。
- Pythia には出金、入金、送金の機能がありません。API キーには取引権限だけを与えてください。
- 暗号資産の現物はロングのみ、ショートは無期限先物だけ、Polymarket は読み取りのみです。

詳しくは [SAFETY.md](../../SAFETY.md) を参照してください。脆弱性の報告は [SECURITY.md](../../SECURITY.md) の手順でお願いします。

## ライセンス

[MIT](../../LICENSE)。市場データは Alpaca、Binance、Kraken、Bybit、OKX、Coinbase、Deribit、DefiLlama、Polymarket、SEC EDGAR から取得しており、各データにはそれぞれの提供元の規約が適用されます。Pythia が役に立ったら、[Ko-fi で支援](https://ko-fi.com/senseiissei)していただけます。
