# AzurPilot — アズールレーン自動化支援ツール

<p align="center">
  <a href="README.md"><img src="https://img.shields.io/badge/简体中文-中文-blue?style=flat-square" alt="简体中文"></a>
  <a href="README.zh-TW.md"><img src="https://img.shields.io/badge/繁體中文-繁體-green?style=flat-square" alt="繁體中文"></a>
  <a href="README.en.md"><img src="https://img.shields.io/badge/English-English-red?style=flat-square" alt="English"></a>
  <a href="README.ja.md"><img src="https://img.shields.io/badge/日本語-日本語-orange?style=flat-square" alt="日本語"></a>
  <a href="README.ko.md"><img src="https://img.shields.io/badge/한국어-한국어-violet?style=flat-square" alt="한국어"></a>
</p>

<p align="center">
  <img src="doc/logo.webp" alt="AzurPilot Logo" width="400">
</p>

<p align="center">
  <strong><a href="https://azurpilot.com/">AzurPilot 公式サイト</a></strong> ｜ アズールレーン自動化スクリプト・大世界侵蝕ループ・マルチプラットフォーム対応
</p>

<p align="center">
  <a href="https://deepwiki.com/wess09/AzurPilot"><img src="https://deepwiki.com/badge.svg" alt="Ask DeepWiki"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.14-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/github/license/wess09/AzurPilot?style=flat-square&label=License&color=2ea44f" alt="License">
  <img src="https://img.shields.io/github/stars/wess09/AzurPilot?style=flat-square&label=Stars&color=ffcc00" alt="Stars">
  <img src="https://img.shields.io/github/forks/wess09/AzurPilot?style=flat-square&label=Forks&color=58a6ff" alt="Forks">
  <img src="https://img.shields.io/github/issues/wess09/AzurPilot?style=flat-square&label=Issues&color=f85149" alt="Issues">
</p>

<p align="center">
  <img src="https://img.shields.io/github/last-commit/wess09/AzurPilot?style=flat-square&label=Last%20Commit&color=8b949e" alt="Last Commit">
  <img src="https://img.shields.io/github/commit-activity/m/wess09/AzurPilot?style=flat-square&label=Commit%20Activity&color=8957e5" alt="Commit Activity">
  <img src="https://img.shields.io/github/repo-size/wess09/AzurPilot?style=flat-square&label=Repo%20Size&color=orange" alt="Repo Size">
  <img src="https://img.shields.io/github/languages/top/wess09/AzurPilot?style=flat-square&label=Top%20Language&color=3776AB" alt="Top Language">
</p>

<p align="center">
  <img src="https://img.shields.io/github/contributors/wess09/AzurPilot?style=flat-square&label=Contributors&color=00b4d8" alt="Contributors">
  <img src="https://img.shields.io/github/issues-pr/wess09/AzurPilot?style=flat-square&label=Pull%20Requests&color=ffb703" alt="Pull Requests">
  <img src="https://img.shields.io/github/issues-pr-closed/wess09/AzurPilot?style=flat-square&label=PRs%20Closed&color=2ea44f" alt="Closed Pull Requests">
</p>

<div align="center">
  <a href="https://azurpilot.com/">
    <img src="https://img.shields.io/badge/Web-ダウンロード-blue?style=for-the-badge&logo=google-chrome&logoColor=white" />
  </a>
  &nbsp;&nbsp;&nbsp;&nbsp;
  <a href="https://join.nanoda.work/#/">
    <img src="https://img.shields.io/badge/交流群-QQ-red?style=for-the-badge&logo=tencent-qq&logoColor=white" />
  </a>
</div>

## プロジェクト概要

AzurPilot は [AzurLaneAutoScript](https://github.com/LmeSzinc/AzurLaneAutoScript) をベースに改変されたアズールレーン自動化支援ツールです。元プロジェクトのコア機能を維持しつつ、複数のブランチ、機能改善、実験的な機能を統合しています。ADB/uiautomator2 で Android エミュレータを操作し、スクリーンショット認識・画像マッチング・OCR によりゲームタスクを自動実行します。CN/EN/JP/TW の4サーバーに対応しています。

> **ご注意**: 本プロジェクトのコードはほぼ AI によって生成・補助されています。不確実性が高いため、修正の [Pull Request](https://github.com/wess09/AzurPilot/pulls) を歓迎します。

**[AzurPilot 公式サイト](https://azurpilot.com/)** で機能の詳細をご確認いただくか、**[ダウンロードページ](https://azurpilot.com/download.html)** から最新版を入手してください。

## GUI プレビュー

<div align="center">
  <img src="doc/GUI.png" alt="GUI Preview" width="800">
</div>

## クイックスタート

> 💡 **推奨**: [AzurPilot ダウンロードページ](https://azurpilot.com/download.html) からお使いのプラットフォームのランチャーを入手してください。Python 環境を同梱しており、すぐに利用できます。

### Linux ワンクリック導入

```shell
curl -fsSL https://azurpilot.com/install/deploy-image.sh | sudo -E bash
```

### ソースコードからの実行

本プロジェクトは `uv` とプロジェクトルートの `.venv` で Python 環境を管理しています（Python >= 3.14 が必要）。リリース版ランチャーには uv、Python、ADB、Git が同梱され、依存関係が `.venv` に同期されます。ソースから開発する場合は uv をインストールしてから実行します：

```bash
uv sync --frozen --no-dev
uv run python gui.py
```

起動後、ブラウザで `http://127.0.0.1:25548` を開くと WebUI にアクセスできます。

## 重要なお知らせ

- 本プロジェクトには大量の自動化ロジックと画像認識機能が含まれています。使用前に[ゲーム内設定](#使用前の設定)が完了していることを確認してください。完了していない場合、認識失敗、処理の異常、タスク実行不能などの問題が発生する可能性があります。
- 本プロジェクトには実験的な機能が含まれており、未知の問題が存在する可能性があります。使用前に設定をバックアップし、異常に気づいたら速やかにご報告ください。

## 使用前の設定

使用前に、以下の基準に従ってゲーム内設定を変更する必要があります。

パス: メインメニュー → 右下の設定 → 左サイドバーのオプション。

| 設定名 | 推奨値 |
| --- | --- |
| フレームレート設定 | 60 FPS |
| 大型作戦設定、TB チュートリアルの削減 | オン |
| 大型作戦設定、自律時にアイテムを自動提出 | オン |
| 大型作戦設定、安全海域で自律をデフォルトオン | オフ |
| ストーリー自動再生 | オン |
| ストーリー自動再生速度調整 | 特急 |
| 待機モード設定、待機モードを有効化 | オフ |
| その他の設定、重複キャラクター取得の通知 | オフ |
| その他の設定、快速交換の再確認ダイアログ | オフ |
| その他の設定、決算キャラクターの表示 | オフ |

### 大型作戦設定

パス: 大型作戦 → 右上のレーダー → 指令モジュール → 潜水艦支援。

| 設定名 | 推奨値 |
| --- | --- |
| X 消費時に潜水艦出撃 | チェックを外す |

### ワンクリック退役設定

パス: メインメニュー → 右下の建造 → 左サイドバーの退役 → 左側の歯車アイコン → ワンクリック退役設定。

| 設定名 | 推奨値 |
| --- | --- |
| 選択優先度 1 | R |
| 選択優先度 2 | SR |
| 選択優先度 3 | N |
| 満凸の同名艦船を所持時、退役条件を満たす同名艦船を何隻残すか | 残さない |
| 満凸の同名艦船を所持していない時、退役条件を満たす同名艦船を何隻残すか | 満凸に必要な数または残さない |

### 画像認識の注意事項

認識に影響を与える可能性がある以下のものを削除してください：

- キャラクターの装備
- キャラクターのスキン
- UI 要素を隠す可能性のあるカスタム表示内容

これらは画像認識結果に影響を与え、自動化処理に異常を引き起こす可能性があります。

## MCP サービス

AzurPilot は MCP サービスを提供しており、MCP 対応のクライアントやツールから呼び出すことで、Agent で AzurPilot を簡単に管理できます。

> MCP サービスはデフォルトで WebUI と一緒に起動し、`/mcp` パス（WebUI のデフォルトポート 25548）にマウントされます。また、`uv run python mcp_server_sse.py` で単独実行も可能です（単独ポート 22268）。

MCP は WebUI のパスワード（`--key` または `config/deploy.yaml` の `Password`）を流用します。パスワード未設定で WebUI が公開アドレスをリッスンしている場合、WebUI が自動生成し、リポジトリ直下の `password.txt` で確認できます。このパスワードを付けないリクエストは 401 で拒否されます。

### ローカル接続設定

```json
{
  "mcpServers": {
    "alas": {
      "url": "http://127.0.0.1:25548/mcp/sse",
      "headers": {
        "Authorization": "Bearer <WebUI のパスワード>"
      }
    }
  }
}
```

### クラウドサーバーまたはイントラネット接続設定

```json
{
  "mcpServers": {
    "alas": {
      "url": "http://[IP_ADDRESS]:25548/mcp/sse",
      "headers": {
        "Authorization": "Bearer <WebUI のパスワード>"
      }
    }
  }
}
```

`[IP_ADDRESS]` を実際のサーバーアドレスまたはイントラネットアドレスに置き換えてください。WebUI のポートを変更した場合は、URL 内のポートも同様に置き換えてください。

URL しか指定できずリクエストヘッダーを設定できないクライアントは、パスワードをクエリパラメータに含められます：`http://[IP_ADDRESS]:25548/mcp/sse?key=<WebUI のパスワード>`。この場合 URL 自体が資格情報になるため、スクリーンショットや共有は避け、可能な限りヘッダーを使用してください。`Authorization` の代わりに `X-API-Key: <WebUI のパスワード>` も使用できます。

パスワードを変更した場合は、MCP に反映させるため WebUI を再起動してください。

### MCP ツール一覧

既定のエンドポイントでは 25 個の `azurpilot_` ツールを公開します。旧ツール名は明示的に作成した互換エンドポイントのみで利用できます。

| カテゴリ | ツール名 | 機能 |
| --- | --- | --- |
| インスタンス管理 | `azurpilot_list_instances` | インスタンス、プロセス状態、実行中タスクを一覧表示 |
| | `azurpilot_get_context` | 状態・実行中タスク・スケジュール/リソース概要・直近のエラー・デバイス機能をまとめて取得 |
| | `azurpilot_start_instance` / `azurpilot_stop_instance` | インスタンスの起動 / 停止 |
| タスク検索 | `azurpilot_search_tasks` | タスク ID・表示名・引数の文言で検索し、一般的な口語別名にも対応 |
| | `azurpilot_get_task_schema` | 引数定義、既定値、選択肢、書き込み可否を取得 |
| 設定とスケジュール | `azurpilot_get_config` | タスクまたはパス単位で設定を取得し、revision を返す |
| | `azurpilot_patch_config` | revision を検証する一括原子変更、dry_run 対応 |
| | `azurpilot_set_task_schedule` | 有効状態と次回実行時刻を設定（予約済み＝完了ではない） |
| ログと観測 | `azurpilot_get_logs` | カーソル・レベル・キーワードで限定件数のログを取得 |
| 統計 | `azurpilot_get_statistics` | 統計ページと概要ページの指標・時系列・表を取得（概要資源、資源推移、セイレーン作戦、委託、艦船経験値、ドロップ、研究、倉庫、資源フロー） |
| | `azurpilot_get_statistics_schema` | 統計フィールド目録：分類、指標キー、単位、説明、絞り込み条件 |
| | `azurpilot_observe_device` | スクリーンショットとフレームのサイズ・向き・取得時刻を取得 |
| デバイス制御 | `azurpilot_acquire_device_control` / `azurpilot_release_device_control` | スケジューラ停止後にデバイスを引き継ぎ、`lease_id` を取得/解放（既定 30 分、呼び出しごとに延長） |
| | `azurpilot_click` / `azurpilot_swipe` / `azurpilot_long_press` | 座標タップ・スワイプ・長押し。`lease_id` が必要で、コマンド送信と画面変化を別々に返す |
| | `azurpilot_input_text` / `azurpilot_press_key` | テキスト入力（自動確定なし）とキー送信。`lease_id` が必要 |
| | `azurpilot_adb_shell` | ホワイトリスト内の読み取り専用 ADB 診断コマンド（`wm size`、`dumpsys battery` など） |
| 操作確認 | `azurpilot_get_operation` | operation_id で書き込み操作の最終状態を照会 |
| メンテナンスツール | `azurpilot_restart_emulator` | インスタンスに紐づくエミュレータを再起動 |
| | `azurpilot_restart_adb` | グローバル ADB サービスを再起動 |
| | `azurpilot_update_application` | アプリ更新を要求（受け付け済み＝完了ではない） |

すべてのツールに `inputSchema` / `outputSchema`、構造化結果、安定したエラーコードがあります。書き込み操作は `request_id` で重複排除でき、タイムアウト時は再送ではなく `azurpilot_get_operation` で確認してください。詳細は [MCP サービス文書](docs/modules/entry/mcp-server.md)。

## マルチプラットフォームランチャー

> 📥 [AzurPilot 公式サイト](https://azurpilot.com/download.html) から Windows / macOS / Linux ランチャーをダウンロード

<div align="center">
  <img src="doc/loading.png" alt="loading" width="500" />
  <p>起動読み込み画面</p>
  <table align="center">
    <tr>
      <td align="center"><img src="doc/GUI.png" alt="新版" width="260"><br>新版</td>
      <td align="center"><img src="doc/GUI-legacy.webp" alt="旧版" width="260"><br>旧版</td>
      <td align="center"><img src="doc/GUI-minimal.png" alt="シンプル" width="260"><br>シンプル</td>
    </tr>
  </table>
  <p>Windows クライアント画面</p>
  <img src="doc/macGUI.png" alt="macGUI" width="500" />
  <p>Mac クライアント画面</p>
</div>

ランチャーのプロジェクト：[GitHub](https://github.com/wess09/alas-launcher)・元プロジェクト [ALAS Launcher: 新型の AzurLaneAutoScript ランチャー](https://github.com/swordfeng/alas-launcher)

変更内容：

1. トレイ対応を追加
2. Windows ネイティブ通知
3. GUI スタイルの美化
4. uv 化
...

## コントリビューター

本プロジェクトは AzurLaneAutoScript とそのコミュニティフォークをベースに開発を続けているため、コントリビューター一覧には本リポジトリへの直接の貢献者だけでなく、上流プロジェクトや関連フォークの原作者も含まれます。

*本プロジェクトの貢献者リスト

<a href="https://github.com/wess09/AzurPilot/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=wess09/AzurPilot&max=1000" alt="AzurPilot Contributors">
</a>

*ランチャープロジェクトの貢献者リスト

<a href="https://github.com/wess09/alas-launcher/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=wess09/alas-launcher&max=1000" alt="Launcher Contributors">
</a>

*ALAS 元プロジェクトの貢献者リスト

<a href="https://github.com/LmeSzinc/AzurLaneAutoScript/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=LmeSzinc/AzurLaneAutoScript&max=1000" alt="AzurLaneAutoScript Contributors">
</a>

## 関連リンク

- [AzurPilot 公式サイト](https://azurpilot.com/) — プロジェクト紹介、機能詳細、アズールレーン自動化ソリューション
- [AzurPilot ダウンロードページ](https://azurpilot.com/download.html) — Windows / macOS / Linux 版のアズールレーンスクリプトツールをダウンロード
- [GitHub リポジトリ](https://github.com/wess09/AzurPilot) — ソースコード、Issue、Pull Request
- [QQ 交流群](https://join.nanoda.work/#/) — アズールレーン自動化コミュニティ
- [AzurLaneAutoScript 上流プロジェクト](https://github.com/LmeSzinc/AzurLaneAutoScript) — ALAS オリジナル版

### 派生プロジェクト・リンク

- [AzurPilot ラズベリーパイ版](https://github.com/nnieie/AzurPilot) — ラズベリーパイ / Termux 実機向けの AzurPilot CN デプロイ版
- [AzurPilot-private-Ru](https://github.com/AliceLiddell01/AzurPilot-private-Ru) — 制御可能なアップデート、透明な起動、外部ネットワーク依存を削減した個人向けロシア語版 AzurPilot
- [PerseusAutoScript](https://github.com/lajiovo/PerseusAutoScript) — AzurPilot 向け総合運用ツール（バックグラウンド静默実行、クローズドループ自己修復、各種通知）
- [AzurRem](https://github.com/syyxl3111/AzurRem) — AzurPilot 向けネイティブ Android クライアント（Kotlin + Jetpack Compose で再実装、PC ゲートウェイ同梱）

## 開発と貢献

本プロジェクトはほぼ完全に VibeCoding の産物です。不備がありましたらご容赦ください。Issue や Pull Request でのフィードバック、修正、ドキュメント改善を歓迎します。

### 開発環境

```bash
uv sync --frozen        # .venv を作成/同期（開発用依存関係を含む）

# コードチェック（CI は ruff の緩い設定を使用 — 致命的な構文エラーと未定義名のみチェック）
uv run ruff check . --select E9,F63,F7,F82 --ignore F821,F722

# テスト（約160個のユニットテスト）
uv run python -m unittest discover -s tests

# 設定生成（設定 YAML ファイルを変更した後は必ず実行）
uv run -m module.config.config_updater
```

### 使用した開発ツールとモデル

本プロジェクトの開発では、複数の AI モデルと開発ツールを使用しました。

**AI モデル：**

| | | |
| --- | --- | --- |
| Gemini | GPT | Claude |
| GLM | MiMo | DeepSeek |
| Kimi | Qwen | DouBao |

**開発ツール：**

| | | |
| --- | --- | --- |
| Claude Code | Codex | Cursor | Antigravity |
| TRAE | ZCode | OpenCode | MiMoCode |


## ライセンス

本プロジェクトは元プロジェクトおよび関連する上流プロジェクトのライセンス要件に従います。ランチャープロジェクトは GPL-3.0 ライセンスでオープンソース化されています。

本プロジェクトが依存する関連プロジェクトのライセンスは /licenses にあります。

本プロジェクトを使用・変更・配布する際は、関連する上流プロジェクトのライセンス要件も遵守してください。

## スポンサー

<p align="center">
  <a href="https://afdian.com/a/miaonaa">
    <img src="doc/afdian.jfif" alt="爱发电" width="200">
  </a>
  <br>
  <b>本プロジェクトを支援（サーバー費用や新モデルのトレーニングなどに使用）</b>
</p>
