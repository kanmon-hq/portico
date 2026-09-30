# Portico コントリビューションガイド

Portico への貢献をご検討いただき、ありがとうございます！  
本プロジェクトは、Model Context Protocol (MCP) をベースとした、安全でスケーラブルなマルチテナント向け実行ゲートウェイ統合ハブを提供することを目指しています。新機能の提案、バグ報告、ドキュメントの改善など、あらゆる貢献を歓迎します。

---

## 目次

1. [行動規範 (Code of Conduct)](#1-行動規範-code-of-conduct)
2. [開発ワークフロー](#2-開発ワークフロー)
   - [Issue の作成](#issue-の作成)
   - [ブランチ戦略](#ブランチ戦略)
   - [コミットメッセージ規約](#コミットメッセージ規約)
3. [ローカル開発環境のセットアップ](#3-ローカル開発環境のセットアップ)
   - [前提ツール](#前提ツール)
   - [セットアップ手順](#セットアップ手順)
4. [アーキテクチャと設計原則](#4-アーキテクチャと設計原則)
   - [ディレクトリ構成と役割](#ディレクトリ構成と役割)
   - [厳守すべき設計・セキュリティルール](#厳守すべき設計セキュリティルール)
5. [コーディング規約](#5-コーディング規約)
   - [リント & フォーマット](#リント--フォーマット)
   - [型ヒント & 非同期 I/O](#型ヒント--非同期-io)
   - [エラーハンドリング & 機密情報マスキング](#エラーハンドリング--機密情報マスキング)
6. [テスト規約](#6-テスト規約)
   - [テストの実行](#テストの実行)
   - [モック方針 & テスト設計](#モック方針--テスト設計)
7. [プルリクエスト (PR) チェックリスト](#7-プルリクエスト-pr-チェックリスト)

---

## 1. 行動規範 (Code of Conduct)

すべての参加者が安全かつ敬意を持ってコラボレーションできるよう、オープンで歓迎されるコミュニティの維持に努めてください。相手を尊重した建設的なフィードバックと対話を心がけてください。

---

## 2. 開発ワークフロー

### Issue の作成
- バグの報告や新機能の提案を行う場合は、まず [GitHub Issues](https://github.com/kanmon-hq/portico/issues) を作成してください。
- 既存の Issue や PR で類似の議論がないか事前に確認してください。

### ブランチ戦略
- `main` ブランチから作業用ブランチを作成してください。
- ブランチ名は以下のプレフィックスを使用してください：
  - `feature/<機能名>`: 新機能の追加
  - `fix/<バグ内容>`: バグ修正
  - `docs/<ドキュメント名>`: ドキュメント修正
  - `refactor/<リファクタ内容>`: 振る舞いを変えないコード整理

```bash
git checkout -b feature/external-server-health-monitor
```

### コミットメッセージ規約
コミットメッセージには [Conventional Commits](https://www.conventionalcommits.org/) 形式を採用しています。

形式: `<type>(<scope>): <description>`

| Type | 説明 | 例 |
|---|---|---|
| `feat` | 新機能の追加 | `feat(servers): add automatic health probe for external MCP servers` |
| `fix` | バグ修正 | `fix(validator): prevent ssrf bypass via ipv4-mapped ipv6 addresses` |
| `docs` | ドキュメントの変更 | `docs(readme): update gateway secret authentication and endpoints` |
| `test` | テストの追加・修正 | `test(auth): add gateway shared secret rotation resilience test` |
| `refactor`| リファクタリング | `refactor(dispatch): streamline namespaced tool proxy routing` |
| `chore` | ビルド設定や補助ツールの変更 | `chore(deps): bump fastmcp from 2.14.7 to 3.2.0` |

主要な `<scope>` の例: `router`, `dispatch`, `servers`, `auth`, `db`, `tools`, `config`, `audit`

---

## 3. ローカル開発環境のセットアップ

### 前提ツール
- **Python**: 3.14+ (必須)
- **uv**: 高速な Python パッケージマネージャー ([インストール手順](https://github.com/astral-sh/uv))
- **Docker** & **Docker Compose**
- **Git**

### セットアップ手順

```bash
# 1. リポジトリのクローン
git clone https://github.com/kanmon-hq/portico.git
cd portico

# 2. 仮想環境の作成と依存関係の同期
uv sync

# 3. 開発用データベース (PostgreSQL) の起動 (任意)
docker compose up -d postgres
# (DB を起動しない場合でも、自動的にインメモリストアへフォールバックします)

# 4. 環境変数の設定
cp .env.example .env

# 5. ローカルサーバー起動
uv run uvicorn portico.main:app --host 0.0.0.0 --port 8001 --reload
```

サーバーが起動したら、別ターミナルでヘルスチェックを確認します：
```bash
curl -i http://localhost:8001/livez
curl -i http://localhost:8001/readyz
```

---

## 4. アーキテクチャと設計原則

### ディレクトリ構成と役割

```text
src/portico/
├── api/              # API ルーティング & 依存性注入 (FastAPI router, deps)
├── core/             # グローバル設定 (config)、FastMCP ハブ初期化
├── cache/            # 二段キャッシュ (L1: In-Memory, L2: Valkey/Redis)
├── storage/          # ゼロ運用ストレージ (SQLite, DynamoDB, Firestore, Cosmos DB)
├── schemas/          # Pydantic リクエスト/レスポンススキーマ
├── services/         # サーバー管理、ツールディスパッチ、監査ログ、URL 検証、暗号化
└── tools/            # テスト・PoC 用組み込みリファレンスツール (Slack / Google)
```

### 厳守すべき設計・セキュリティルール

Portico のコード変更時は、以下のルールを厳守してください：

1. **Gateway 共有シークレット照合（Tollgate / Kura 連携）**:
   - ゲートウェイからのリクエスト信頼確認には `X-Gateway-Secret` を使用し、タイミング攻撃防御のため必ず `secrets.compare_digest` で定数時間比較を行うこと。
2. **Fail-Fast 整合性検証（コンフリクト即時遮断）**:
   - クライアント指定の `tenant_id` とプロキシ指定の `X-Tenant-ID` に不一致がある場合は、暗黙的に上書きせず `403 Forbidden`（または `400 Bad Request`）で即座に遮断すること。
3. **SSRF 防止・安全性検証**:
   - 外部 MCP サーバー登録時は、プライベート IP、ループバック、クラウドメタデータ IP（`169.254.169.254` 等）、IPv4-Mapped IPv6 アドレスへのアクセスを即時検証・遮断すること。
4. **内部ゲートウェイ保護**:
   - 内部専用 API（`/v1/internal/*`）は共有シークレット（`X-Internal-Secret`）の定数時間比較で保護し、外部からの直接アクセスを遮断すること。
5. **暗号化キー未設定時の起動時エラー（Fail-Fast）**:
   - 外部サーバーの認証トークン暗号化キー（`SECRET_ENCRYPTION_KEY`）や本番用ゲートウェイシークレット（`GATEWAY_SHARED_SECRET`）が未設定の場合、本番環境ではデフォルト値にフォールバックせず起動を拒否すること。
6. **構造化監査ログの必須記録**:
   - ツール実行ごとの結果、実行時間、テナント情報、キー ID を `portico.audit` に構造化ログとして必ず記録すること。

---

## 5. コーディング規約

### リント & フォーマット
Portico では [Ruff](https://github.com/astral-sh/ruff) をリントおよびフォーマッターとして採用しています。コミット前に必ず実行してください：

```bash
# フォーマット実行
uv run ruff format .

# 静的解析 & リント実行
uv run ruff check .
```

### 型ヒント & 非同期 I/O
- すべての関数およびメソッドに適切な型ヒントを付与してください（`from __future__ import annotations` を推奨）。
- I/O バウンドな処理（HTTP 通信、PostgreSQL アクセス）は必ず `async` / `await` を使用し、ブロッキング処理を避けてください。
- 外部 HTTP 通信には `httpx.AsyncClient` を使用し、必ずタイムアウトを設定してください。

### エラーハンドリング & 機密情報マスキング
- ツール実行時や API ハンドリング時の内部例外において、生のスタックトレースやシークレットをレスポンスに露出させず、構造化エラーとしてラップしてください。
- ログ出力時、API キーや外部トークンはマスキング処理（例: `ext-token-***`）を徹底してください。

---

## 6. テスト規約

### テストの実行
品質と安全性を担保するため、機能追加・バグ修正には必ず対応する単体テストを同梱してください。

```bash
# 全テスト実行
uv run pytest

# キャッシュを無視して詳細実行
uv run pytest -v -o cache_dir=.pytest_cache

# カバレッジレポート出力
uv run pytest --cov=portico --cov-report=term-missing
```

### モック方針 & テスト設計
- `unittest.mock.patch` やインメモリストアを活用し、外部 DB や実 SaaS 接続なしで単体テストが完結できるように設計してください。
- `MOCK_EXTERNAL_APIS=true` により、外部 SaaS 呼び出しを安全にモック検証するテストを推奨します。
- 正常系だけでなく、SSRF 禁止 IP、認証不備、タイムアウト、並列フェッチ失敗時の耐障害性など、エッジケースを確実に検証してください。

---

## 7. プルリクエスト (PR) チェックリスト

PR を提出する前に、以下の項目を確認してください：

- [ ] 最新の `main` ブランチを取り込んでいるか（`git pull origin main` または `git rebase main`）
- [ ] 全テストが成功するか（`uv run pytest`）
- [ ] リンター・フォーマッターを通過しているか（`uv run ruff check .` / `uv run ruff format .`）
- [ ] 新機能・修正内容に対応するテストが含まれているか
- [ ] コミットメッセージが Conventional Commits 規約に準拠しているか
- [ ] コード内にハードコードされたシークレットや既定値フォールバックが含まれていないか
- [ ] 必要に応じて `README.md` や `docs/` のドキュメントを更新しているか
