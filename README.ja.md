# InitRunner

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="assets/logo-light.svg">
    <img src="assets/logo-light.svg" alt="InitRunner" width="500">
  </picture>
</p>

<p align="center">
  <a href="https://pypi.org/project/initrunner/"><img src="https://img.shields.io/pypi/v/initrunner?color=%2334D058&v=1" alt="PyPI version"></a>
  <a href="https://pypi.org/project/initrunner/"><img src="https://img.shields.io/pypi/dm/initrunner?color=%2334D058" alt="PyPI downloads"></a>
  <a href="https://hub.docker.com/r/vladkesler/initrunner"><img src="https://img.shields.io/docker/pulls/vladkesler/initrunner?color=%2334D058" alt="Docker pulls"></a>
  <a href="LICENSE-MIT"><img src="https://img.shields.io/badge/license-MIT%20OR%20Apache--2.0-%2334D058" alt="MIT OR Apache-2.0"></a>
  <a href="https://ai.pydantic.dev/"><img src="https://img.shields.io/badge/PydanticAI-6e56cf?logo=pydantic&logoColor=white" alt="PydanticAI"></a>
  <a href="https://discord.gg/GRTZmVcW"><img src="https://img.shields.io/badge/Discord-InitRunner%20Hub-5865F2?logo=discord&logoColor=white" alt="Discord"></a>
</p>

<p align="center">
  <a href="https://initrunner.ai/">公式サイト</a> · <a href="https://initrunner.ai/docs">ドキュメント</a> · <a href="https://hub.initrunner.ai/">InitHub</a> · <a href="https://discord.gg/GRTZmVcW">Discord</a>
</p>

<p align="center">
  <a href="README.md">English</a> · <a href="README.zh-CN.md">简体中文</a> · 日本語
</p>

> **注意:** これはコミュニティによる翻訳です。最新の情報は [英語版 README](README.md) を参照してください。翻訳は更新に遅れる場合があります。

YAML ファーストの AI エージェントプラットフォーム。エージェントのロール、ツール、ナレッジベース、メモリを 1 つのファイルで定義。インタラクティブチャット、ワンショットコマンド、自律エージェント、cron/webhook/ファイル監視トリガー付きデーモン、Telegram/Discord ボット、OpenAI 互換 API として実行可能。RAG と永続メモリはすぐに使えます。Web ダッシュボードまたはネイティブデスクトップアプリですべてを管理。`curl` または `pip` でインストール、コンテナ不要。

```bash
initrunner run helpdesk -i                                    # RAG + メモリでドキュメント Q&A
initrunner run deep-researcher -p "Compare vector databases"  # 3 エージェント研究チーム
initrunner run code-review-team -p "Review the latest commit" # 多視点コードレビュー
```

15 種類のスターター、60 以上のサンプル、または独自に定義。

> **v2026.4.3**: 自律実行ドキュメント、Launchpad で Compose/Team 実行表示、次元別リフレクション、予算対応継続プロンプト、finalize_plan() ツール、Electric Charcoal ダッシュボード。[変更履歴](CHANGELOG.md) を参照。

## クイックスタート

```bash
curl -fsSL https://initrunner.ai/install.sh | sh
initrunner setup        # ウィザード：プロバイダー、モデル、API キーを選択
```

または: `uv pip install "initrunner[recommended]"` / `pipx install "initrunner[recommended]"`。[インストールガイド](docs/getting-started/installation.md) を参照。

### スターターを試す

`initrunner run --list` で全カタログを表示。モデルは API キーから自動検出されます。

| スターター | 機能 | 種類 |
|-----------|------|------|
| `helpdesk` | ドキュメントを読み込み、引用とメモリ付き Q&A エージェントを取得 | Agent (RAG) |
| `code-review-team` | 多視点レビュー：アーキテクト、セキュリティ、メンテナー | Team |
| `deep-researcher` | 3 エージェントパイプライン：プランナー、Web リサーチャー、シンセサイザー（共有メモリ） | Team |
| `codebase-analyst` | リポジトリをインデックスし、アーキテクチャについて対話、セッション間でパターンを学習 | Agent (RAG) |
| `web-researcher` | Web を検索し、引用付き構造化ブリーフィングを作成 | Agent |
| `content-pipeline` | トピック調査、執筆、編集/ファクトチェック（webhook または cron 経由） | Compose |
| `telegram-assistant` | メモリと Web 検索付き Telegram ボット | Agent (Daemon) |
| `email-agent` | 受信トレイを監視、メッセージを分類、返信を起草、緊急メールを Slack に通知 | Agent (Daemon) |
| `support-desk` | インテリジェントルーティング：リサーチャー、レスポンダー、エスカレーターに自動分配 | Compose |
| `memory-assistant` | セッション間で記憶する個人アシスタント | Agent |

RAG スターターは初回実行時に自動取り込み。プロジェクトディレクトリに `cd` するだけ：

```bash
cd ~/myproject
initrunner run codebase-analyst -i   # コードをインデックスし、Q&A を開始
```

### 自分で作る

```bash
initrunner new "a research assistant that summarizes papers"  # role.yaml を生成
initrunner run --ingest ./docs/    # YAML をスキップして、ドキュメントと直接対話
```

[InitHub](https://hub.initrunner.ai/) でコミュニティエージェントを検索・インストール: `initrunner search "code review"` / `initrunner install alice/code-reviewer`。

**Docker**、インストール不要：

```bash
docker run -d -e OPENAI_API_KEY -p 8100:8100 \
    -v initrunner-data:/data ghcr.io/vladkesler/initrunner:latest        # ダッシュボード
docker run --rm -it -e OPENAI_API_KEY \
    -v initrunner-data:/data ghcr.io/vladkesler/initrunner:latest run -i # チャット
```

詳細は [Docker ガイド](docs/getting-started/docker.md) を参照。

## YAML でエージェントを定義する

```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: code-reviewer
  description: Reviews code for bugs and style issues
spec:
  role: |
    You are a senior engineer. Review code for correctness and readability.
    Use git tools to examine changes and read files for context.
  model: { provider: openai, name: gpt-5-mini }
  tools:
    - type: git
      repo_path: .
    - type: filesystem
      root_path: .
      read_only: true
```

```bash
initrunner run reviewer.yaml -p "Review the latest commit"
```

`model:` セクションはオプションです。省略すると InitRunner が API キーから自動検出します。Anthropic、OpenAI、Google、Groq、Mistral、Cohere、xAI、OpenRouter、Ollama、および任意の OpenAI 互換エンドポイントに対応。28 の組み込みツール（ファイルシステム、git、HTTP、Python、shell、SQL、検索、メール、Slack、MCP、オーディオ、PDF 抽出、CSV 分析、画像生成）を搭載し、1 つのファイルで[独自のツールを追加](docs/agents/tool_creation.md)できます。

## なぜ InitRunner なのか

YAML ファイルがエージェント*そのもの*です。ツール、ナレッジソース、メモリ、トリガー、モデル、ガードレール、すべてが一箇所に宣言されています。読めばエージェントが何をするか即座に理解できます。diff を取り、PR でレビューし、チームメイトに渡せます。GPT から Claude に切り替えたいときは 1 行変更するだけ。RAG を追加したいときは `ingest:` セクションを追加するだけです。

同じファイルをインタラクティブチャット（`-i`）、ワンショットコマンド（`-p "..."`）、自律エージェント（`-a`）、cron/webhook/ファイル監視デーモン（`--daemon`）、または OpenAI 互換 API（`--serve`）として実行できます。デプロイモードを事前に選んでそれに合わせて構築する必要はありません。実行時にフラグで選ぶだけです。

これが実際に意味すること：エージェント設定はコードと一緒にバージョン管理に置かれます。新しいチームメンバーは YAML を読んでエージェントの動作を理解します。他の設定と同様に PR でエージェントの変更をレビューします。インタラクティブにプロトタイプしたエージェントは、デーモンや API としてデプロイするものと同じです。同じファイル、違うフラグ。

## 他ツールとの比較

|  | InitRunner | LangChain | CrewAI | AutoGen |
|---|---|---|---|---|
| **エージェント設定** | YAML ファイル | Python chains + 設定 | Python クラス | Python クラス |
| **RAG** | `--ingest ./docs/`（フラグ 1 つ） | Loaders + splitters + vectorstore | RAG ツールまたはカスタム | 外部セットアップ |
| **メモリ** | 組み込み、デフォルトで有効 | アドオン（複数の選択肢） | 短期/長期メモリ | 外部 |
| **マルチエージェント** | `compose.yaml` または `kind: Team` | LangGraph | Crew 定義 | Group chat |
| **自律実行** | `-a` フラグ + YAML ガードレール | カスタムエージェントループ | 順次プロセス | 会話ループ |
| **デプロイモード** | 同一 YAML: REPL / デーモン / API | モードごとにカスタム | CLI または Kickoff | カスタム |
| **モデル切替** | YAML 1 行変更 | LLM クラスを差替 | エージェントごとに設定 | エージェントごとに設定 |
| **カスタムツール** | 1 ファイル、1 デコレータ | `@tool` デコレータ | `@tool` デコレータ | Function call |
| **ボットデプロイ** | `--telegram` / `--discord` フラグ | 別途統合 | 別途統合 | 別途統合 |
| **移行** | `--pydantic-ai` / `--langchain` インポート | N/A | N/A | N/A |

## 機能紹介

### ナレッジとメモリ

エージェントをディレクトリに向けるだけ。ドキュメントを自動的に抽出、チャンク分割、埋め込み、インデックスします。会話中、エージェントは自動的にインデックスを検索し、見つけた内容を引用します。メモリはセッション間で永続化されます。

```yaml
spec:
  ingest:
    auto: true
    sources: ["./docs/**/*.md", "./docs/**/*.pdf"]
  memory:
    semantic:
      max_memories: 1000
```

```bash
initrunner run role.yaml -i   # 初回実行時に自動取り込み、メモリ + 検索準備完了
```

[取り込み](docs/core/ingestion.md) · [メモリ](docs/core/memory.md) · [RAG クイックスタート](docs/getting-started/rag-quickstart.md) を参照。

### トリガーとデーモン

任意のエージェントを cron スケジュール、ファイル変更、webhook、ハートビートに反応するデーモンに変換：

```yaml
spec:
  triggers:
    - type: cron
      schedule: "0 9 * * 1"
      prompt: "Generate the weekly status report."
    - type: file_watch
      paths: [./src]
      prompt_template: "File changed: {path}. Review it."
```

```bash
initrunner run role.yaml --daemon   # 停止するまで実行
```

[トリガー](docs/core/triggers.md) · [Telegram](docs/getting-started/telegram.md) · [Discord](docs/getting-started/discord.md) を参照。

### マルチエージェントオーケストレーション

エージェントを連鎖させます。あるエージェントの出力が次のエージェントの入力になります。センスルーティングがメッセージごとに適切なターゲットを自動選択（まずキーワードマッチング、タイブレーク時に単一の LLM 呼び出し）：

```yaml
apiVersion: initrunner/v1
kind: Compose
metadata: { name: email-chain }
spec:
  services:
    inbox-watcher:
      role: roles/inbox-watcher.yaml
      sink: { type: delegate, target: triager }
    triager:
      role: roles/triager.yaml
      sink: { type: delegate, strategy: sense, target: [researcher, responder] }
    researcher: { role: roles/researcher.yaml }
    responder: { role: roles/responder.yaml }
```

`initrunner compose up compose.yaml` で実行。[パターンガイド](docs/orchestration/patterns-guide.md) · [Compose](docs/orchestration/agent_composer.md) を参照。

### 推論とツール管理

エージェントが何をするかだけでなく、どう考えるかを制御：

```yaml
spec:
  reasoning:
    pattern: plan_execute    # 事前に計画を立て、各ステップを実行
    auto_plan: true
  tools:
    - type: think            # 自己批評付き内部スクラッチパッド
      critique: true
    - type: todo             # マルチステップ作業用の構造化タスクリスト
```

4 つの推論パターン：`react`、`todo_driven`、`plan_execute`、`reflexion`。[推論](docs/core/reasoning.md) を参照。

ツールが多いエージェントはコンテキストを浪費し、選択精度が下がります。ツール検索はツールをオンデマンドのキーワード検索の背後に隠します：エージェントは `search_tools` と少数の固定ツールだけを見て、ターンごとに必要なものを発見します。BM25 スコアリング、API 呼び出しなし、通常 60-80% のコンテキストを節約。[ツール検索](docs/core/tool-search.md) を参照。

### 自律実行

通常の実行は 1 ターンで完結します。プロンプトを送り、エージェントが応答して終わり。`-a` を付けるとエージェントは作業を続けます。TODO リストを作り、各項目を順に処理し、すべて完了したら自動的に停止します。予算 -- イテレーション回数、トークン数、時間 -- を設定して暴走を防ぎます。

```yaml
spec:
  autonomy:
    compaction: { enabled: true, threshold: 30 }
  guardrails:
    max_iterations: 15
    autonomous_token_budget: 100000
```

```bash
initrunner run role.yaml -a -p "Scan this repo for security issues and file a report"
```

トリガーでも使えます。任意のトリガーに `autonomous: true` を設定すると、デーモンが起動する実行は単一応答ではなくフルループになります。[自律実行](docs/orchestration/autonomy.md) · [ガードレール](docs/configuration/guardrails.md) を参照。

## アーキテクチャ

```
initrunner/
  agent/        ロールスキーマ、ローダー、エグゼキューター、28 の自己登録ツール
  runner/       ワンショット、REPL、自律、デーモン実行モード
  compose/      compose.yaml によるマルチエージェントオーケストレーション
  triggers/     Cron、ファイルウォッチャー、webhook、ハートビート、Telegram、Discord
  stores/       ドキュメント + メモリストア（LanceDB、zvec）
  ingestion/    抽出 -> チャンク分割 -> 埋め込み -> 格納 パイプライン
  mcp/          MCP サーバー統合とゲートウェイ
  audit/        追記専用 SQLite 監査証跡
  services/     共有ビジネスロジック層
  cli/          Typer + Rich CLI エントリーポイント
```

エージェントフレームワークとして [PydanticAI](https://ai.pydantic.dev/)、設定バリデーションに Pydantic、ベクトル検索に LanceDB を使用。開発セットアップは [CONTRIBUTING.md](CONTRIBUTING.md) を参照。

## セキュリティ

InitRunner には [initguard](https://github.com/initrunner/initguard) ポリシーエンジンが組み込まれています。エージェントはロールメタデータ（名前、チーム、タグ、作者）からアイデンティティを取得し、すべてのツール呼び出しと委任がポリシーに対してチェックされます：

- **ツールレベル認可**：エージェントはポリシーが許可するツールのみ呼び出し可能
- **委任ポリシー**：どのエージェントがどのエージェントに委任できるかを制御
- **コンテンツフィルタリング**：設定可能なコンテンツポリシー付き入力ガードレール
- **PEP 578 サンドボックス**：危険な操作の監査フック
- **Docker 分離**：オプションのサンドボックス実行環境
- **トークン予算とレート制限**：コスト暴走を防止
- **環境変数スクラブ**：機密キーをサブプロセス環境から除去
- **追記専用監査証跡**：すべてのツール呼び出しを SQLite に記録

```bash
export INITRUNNER_POLICY_DIR=./policies
initrunner run role.yaml                  # ツール呼び出し + 委任をポリシーに対してチェック
```

[エージェントポリシー](docs/security/agent-policy.md) · [セキュリティ](docs/security/security.md) · [ガードレール](docs/configuration/guardrails.md) を参照。

## ユーザーインターフェース

<p align="center">
  <img src="assets/screenshot-dashboard.png" alt="InitRunner Dashboard" width="800"><br>
  <em>ダッシュボード：エージェント、アクティビティ、コンポジション、チームを一覧</em>
</p>

```bash
pip install "initrunner[dashboard]"
initrunner dashboard                  # http://localhost:8100 を開く
```

エージェントの閲覧、プロンプトの実行、コンポジションの視覚的構築、推論パターンの設定、監査証跡のレビュー。ネイティブデスクトップウィンドウとしても利用可能（`initrunner desktop`）。[ダッシュボードドキュメント](docs/interfaces/dashboard.md) を参照。

## その他の機能

| 機能 | コマンド / 設定 | ドキュメント |
|-----|---------------|------------|
| **スキル**（再利用可能なツール + プロンプトバンドル） | `spec: { skills: [../skills/web-researcher] }` | [Skills](docs/agents/skills_feature.md) |
| **チームモード**（1 つのタスクに複数ペルソナ） | `kind: Team` + `spec: { personas: {…} }` | [Team Mode](docs/orchestration/team_mode.md) |
| **API サーバー**（OpenAI 互換エンドポイント） | `initrunner run agent.yaml --serve --port 3000` | [Server](docs/interfaces/server.md) |
| **マルチモーダル**（画像、音声、動画、ドキュメント） | `initrunner run role.yaml -p "Describe" -A photo.png` | [Multimodal](docs/core/multimodal.md) |
| **構造化出力**（バリデーション済み JSON スキーマ） | `spec: { output: { schema: {…} } }` | [Structured Output](docs/core/structured-output.md) |
| **評価**（エージェント出力品質のテスト） | `initrunner test role.yaml -s eval.yaml` | [Evals](docs/core/evals.md) |
| **MCP ゲートウェイ**（エージェントを MCP ツールとして公開） | `initrunner mcp serve agent.yaml` | [MCP Gateway](docs/interfaces/mcp-gateway.md) |
| **MCP ツールキット**（エージェントなしのツール） | `initrunner mcp toolkit` | [MCP Gateway](docs/interfaces/mcp-gateway.md) |
| **ケイパビリティ**（ネイティブ PydanticAI 機能） | `spec: { capabilities: [Thinking, WebSearch] }` | [Capabilities](docs/core/capabilities.md) |
| **オブザーバビリティ**（OpenTelemetry 統合） | `spec: { observability: { enabled: true } }` | [Observability](docs/core/observability.md) |
| **設定変更**（任意ロールのプロバイダー/モデル切替） | `initrunner configure role.yaml --provider groq` | [Providers](docs/configuration/providers.md) |

## 配布

**InitHub:** [hub.initrunner.ai](https://hub.initrunner.ai/) でコミュニティエージェントを検索・インストール。`initrunner publish` で自分のエージェントを公開。[Registry](docs/agents/registry.md) を参照。

**OCI レジストリ:** ロールバンドルを任意の OCI 準拠レジストリにプッシュ: `initrunner publish oci://ghcr.io/org/my-agent --tag 1.0.0`。[OCI 配布](docs/core/oci-distribution.md) を参照。

**クラウドデプロイ:**

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/template/FROM_REPO?referralCode=...)
[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/vladkesler/initrunner)

## ドキュメント

| 領域 | 主要ドキュメント |
|------|---------------|
| 入門 | [Installation](docs/getting-started/installation.md) · [Setup](docs/getting-started/setup.md) · [RAG Quickstart](docs/getting-started/rag-quickstart.md) · [Tutorial](docs/getting-started/tutorial.md) · [CLI Reference](docs/getting-started/cli.md) · [Docker](docs/getting-started/docker.md) · [Discord Bot](docs/getting-started/discord.md) · [Telegram Bot](docs/getting-started/telegram.md) |
| エージェントとツール | [Tools](docs/agents/tools.md) · [Tool Creation](docs/agents/tool_creation.md) · [Tool Search](docs/core/tool-search.md) · [Skills](docs/agents/skills_feature.md) · [Structured Output](docs/core/structured-output.md) · [Providers](docs/configuration/providers.md) |
| インテリジェンス | [Reasoning](docs/core/reasoning.md) · [Intent Sensing](docs/core/intent_sensing.md) · [Tool Search](docs/core/tool-search.md) · [Autonomy](docs/orchestration/autonomy.md) |
| ナレッジとメモリ | [Ingestion](docs/core/ingestion.md) · [Memory](docs/core/memory.md) · [Multimodal Input](docs/core/multimodal.md) |
| オーケストレーション | [Patterns Guide](docs/orchestration/patterns-guide.md) · [Compose](docs/orchestration/agent_composer.md) · [Delegation](docs/orchestration/delegation.md) · [Team Mode](docs/orchestration/team_mode.md) · [Autonomy](docs/orchestration/autonomy.md) · [Triggers](docs/core/triggers.md) |
| インターフェース | [Dashboard](docs/interfaces/dashboard.md) · [API Server](docs/interfaces/server.md) · [MCP Gateway](docs/interfaces/mcp-gateway.md) |
| 配布 | [OCI Distribution](docs/core/oci-distribution.md) · [Shareable Templates](docs/getting-started/shareable-templates.md) |
| 運用 | [Security](docs/security/security.md) · [Agent Policy](docs/security/agent-policy.md) · [Guardrails](docs/configuration/guardrails.md) · [Audit](docs/core/audit.md) · [Reports](docs/core/reports.md) · [Evals](docs/core/evals.md) · [Doctor](docs/operations/doctor.md) · [Observability](docs/core/observability.md) · [CI/CD](docs/operations/cicd.md) |

## サンプル

```bash
initrunner examples list               # 60 以上のエージェント、チーム、Compose プロジェクト
initrunner examples copy code-reviewer # カレントディレクトリにコピー
```

## アップグレード

`initrunner doctor --role role.yaml` を実行して、ロールファイルの非推奨フィールド、スキーマエラー、仕様バージョンの問題をチェック。`--fix` で自動修復、`--fix --yes` で CI 向け。[非推奨事項](docs/operations/deprecations.md) を参照。

## コミュニティと貢献

- [Discord](https://discord.gg/GRTZmVcW): チャット、質問、ロール共有
- [GitHub Issues](https://github.com/vladkesler/initrunner/issues): バグ報告と機能リクエスト
- [Changelog](CHANGELOG.md): リリースノート

コントリビューション歓迎！開発セットアップと PR ガイドラインは [CONTRIBUTING.md](CONTRIBUTING.md) を参照。

## ライセンス

[MIT](LICENSE-MIT) または [Apache-2.0](LICENSE-APACHE) のいずれかのライセンスで提供。お好みで選択してください。

---

<p align="center"><sub>v2026.4.3</sub></p>
