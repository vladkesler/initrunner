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

YAML ファーストの AI エージェントプラットフォーム。1 つのファイルでエージェントのロール、ツール、ナレッジベース、メモリを定義。インタラクティブチャット、ワンショットコマンド、cron/webhook/ファイル監視トリガー付き自律デーモン、Telegram/Discord ボット、または OpenAI 互換 API として実行できます。RAG と永続メモリがすぐに使えます。Web ダッシュボードまたはネイティブデスクトップアプリですべてを管理。`curl` または `pip` でインストール、コンテナ不要。

```bash
initrunner run helpdesk -i                                    # RAG + メモリでドキュメント Q&A
initrunner run deep-researcher -p "Compare vector databases"  # 3 エージェント研究チーム
initrunner run code-review-team -p "Review the latest commit" # 多視点コードレビュー
```

15 種類のスターター、60 以上のサンプル、または独自に定義。

> **v2026.4.4**: `--autopilot` フラグでマルチステップ自律トリガーに対応、README をセキュリティと自律性中心に再構成。[変更履歴](CHANGELOG.md) を参照。

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

## チャットからオートパイロットまで

同じ YAML ファイルが 4 つのエスカレーションモードで動作します。まずチャットで試す。うまくいったら自律実行させる。信頼できたらデーモンとしてデプロイする。ステージ間の書き直しは不要です。

**インタラクティブとワンショット：**

```bash
initrunner run role.yaml -i              # REPL：対話形式でやり取り
initrunner run role.yaml -p "Scan for security issues"  # 1 つのプロンプト、1 つの応答
```

**自律モード：** `-a` を付けるとエージェントは作業を続けます。タスクリストを作り、各項目を処理し、進捗を振り返り、すべて完了したら終了します。予算を設定して暴走を防ぎます。

```bash
initrunner run role.yaml -a -p "Scan this repo for security issues and file a report"
```

```yaml
spec:
  autonomy:
    compaction: { enabled: true, threshold: 30 }
  guardrails:
    max_iterations: 15
    autonomous_token_budget: 100000
    autonomous_timeout_seconds: 600
```

4 つの推論戦略がマルチステップ作業でのエージェントの思考方法を制御します：`react`（デフォルト）、`todo_driven`、`plan_execute`、`reflexion`。予算制約、イテレーション制限、タイムアウト、スピンガード（ツール呼び出しのない連続ターン）が自律実行を有界に保ちます。[自律実行](docs/orchestration/autonomy.md) · [ガードレール](docs/configuration/guardrails.md) を参照。

**デーモン：** トリガーを追加して `--daemon` に切り替えます。エージェントは継続的に実行し、cron スケジュール、ファイル変更、webhook、Telegram メッセージ、Discord メンションに反応します。各イベントが 1 回のプロンプト-応答サイクルを起動します。

```yaml
spec:
  triggers:
    - type: cron
      schedule: "0 9 * * 1"
      prompt: "Generate the weekly status report."
    - type: file_watch
      paths: [./src]
      prompt_template: "File changed: {path}. Review it."
    - type: telegram
      allowed_user_ids: [123456789]
```

```bash
initrunner run role.yaml --daemon   # Ctrl+C まで実行
```

6 種類のトリガー：cron、webhook、file_watch、heartbeat、telegram、discord。デーモンは再起動なしでロール変更をホットリロードし、日次・生涯トークン予算を適用し、最大 4 トリガーを同時実行します。[トリガー](docs/core/triggers.md) · [Telegram](docs/getting-started/telegram.md) · [Discord](docs/getting-started/discord.md) を参照。

**オートパイロット：** デーモンは応答します。オートパイロットは*考えてから*応答します。誰かが Telegram ボットに「来週ニューヨークからロンドンへのフライトを探して」とメッセージを送ったとき、デーモンモードでは 1 回で回答します。オートパイロットでは、エージェントが Web を検索し、オプションを比較し、日程を確認し、読む価値のある回答を返します。

```bash
initrunner run role.yaml --autopilot   # すべてのトリガーが完全な自律ループを実行
```

`--autopilot` は `--daemon` と同じですが、各トリガーがシングルショットではなくマルチステップの自律実行を行います。ガードレールは `-a` と同じ：イテレーション制限、トークン予算、スピンガード、`finish_task`。エージェントが計画し、ツールを使い、振り返り、完了したら返信します。

選択的に設定することもできます。個別のトリガーに `autonomous: true` を設定し、残りはクイックシングルショット応答のままにします。

```yaml
spec:
  triggers:
    - type: telegram
      autonomous: true          # 考え、調査し、返信
    - type: cron
      schedule: "0 9 * * 1"
      prompt: "Generate the weekly status report."
      autonomous: true          # 計画、データ収集、執筆、レビュー
    - type: file_watch
      paths: [./src]
      prompt_template: "File changed: {path}. Review it."
      # autonomous: false (default) -- クイックシングル応答
```

エージェントは実行中にフォローアップタスクを自己スケジュールできます。[自律実行](docs/orchestration/autonomy.md) · [ガードレール](docs/configuration/guardrails.md) を参照。

**メモリはすべてを貫きます。** エピソード記憶、セマンティック記憶、手続き記憶がインタラクティブセッション、自律実行、デーモントリガーの間で永続化されます。各セッション後、統合プロセスが LLM を使ってエピソード履歴から永続的な事実を抽出します。エージェントは単に実行するだけではありません。学習します。[メモリ](docs/core/memory.md) を参照。

## セキュリティ

InitRunner は 12 のセキュリティレイヤーを搭載しています。`security:` 設定キーでオプトインする方式で、自動的に有効になるわけではありませんが、統合済みですぐに使えます。`security:` セクションのないロールは安全なデフォルト値が適用されます。重要なのは、これらの機能が本番稼働 6 か月後にサードパーティライブラリから追加するものではなく、フレームワーク内に存在しているということです。

**入力：** サーバーミドルウェア（タイミングセーフ比較による Bearer 認証、レート制限、ボディサイズ制限、HTTPS 強制、セキュリティヘッダー、CORS）。コンテンツポリシーエンジン（不適切語フィルター、禁止パターンマッチング、プロンプト長制限、オプションの LLM トピック分類器）。入力ガードケイパビリティ（PydanticAI `before_run` フックでエージェント開始前にプロンプトを検証）。

**認可：** [InitGuard](https://github.com/initrunner/initguard) ABAC ポリシーエンジン（エージェントはロールメタデータからアイデンティティを取得、すべてのツール呼び出しと委任を CEL ポリシーに対してチェック）。引数レベルのパーミッションルール（ツールごとの allow/deny glob パターン、deny 優先）。SQL 認可コールバック（エンジンレベルで危険な操作をブロック）。

**実行：** PEP 578 監査フックサンドボックス（スレッドごとのファイルシステム書き込み制限、サブプロセスブロック、プライベート IP ネットワークブロック、危険モジュールインポートブロック、eval/exec ブロックの適用）。Docker コンテナサンドボックス（読み取り専用 rootfs、メモリ/CPU 制限、ネットワーク分離、PID 制限）。環境変数スクラブ（プレフィックスとサフィックスのマッチングですべてのサブプロセス環境から機密キーを除去）。

**予算：** API リクエストのトークンバケットレート制限。5 つの粒度のトークン予算：実行ごと、セッションごと、自律実行ごと、デーモン日次、デーモン生涯。

**監査：** 追記専用 SQLite 証跡、自動シークレットスクラブ（GitHub トークン、AWS キー、Stripe キー、Slack トークンなどをカバーする 16 の正規表現パターン）。すべてのツール呼び出し、委任イベント、セキュリティ違反が記録されます。

```bash
export INITRUNNER_POLICY_DIR=./policies
initrunner run role.yaml                  # ツール呼び出し + 委任をポリシーに対してチェック
```

[エージェントポリシー](docs/security/agent-policy.md) · [セキュリティ](docs/security/security.md) · [ガードレール](docs/configuration/guardrails.md) を参照。

## なぜ InitRunner なのか

**YAML ファイルがエージェントそのもの。** 1 つのファイル。可読で、diff でき、PR でレビューできます。開くだけでエージェントの動作がわかります：どのモデル、どのツール、どのナレッジソース、どのガードレール。ツールを設定するために Python のクラス階層を学ぶ必要はありません。新しいチームメンバーは YAML を読んで理解します。他の設定と同じように PR でエージェントの変更をレビューします。

**同じファイル、違うフラグ。** `-i` でインタラクティブにプロトタイプしたエージェントは、`--daemon` でデプロイするエージェントとまったく同じです。書き直し不要、デプロイメントアダプター不要、開発と異なる「本番モード」も不要。実行モードはデザイン時のアーキテクチャ決定ではなく、実行時のフラグで選びます。

**セキュリティは内蔵、後付けではない。** ほとんどのエージェントフレームワークはセキュリティを「本番になったら認証ミドルウェアを追加」として扱います。InitRunner はポリシーエンジン、PII リダクション、サンドボックス、ツール認可、監査ログを統合済みで出荷します。設定で有効化するだけで、週末を費やして配管工事する必要はありません。

**ブレーキ付きの自律性。** エージェントは無人で実行されますが、暴走はしません。トークン予算、イテレーション制限、ウォールクロックタイムアウト、スピンガードはすべて宣言的な YAML 設定です。1 回の自律実行が始まる前に、どれだけの自由度を与えるかを決められます。

## ナレッジとメモリ

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

## マルチエージェントオーケストレーション

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

## MCP -- あらゆるツールエコシステムに接続

エージェントは任意の [MCP](https://modelcontextprotocol.io/) サーバーをツールソースとして利用できます。サーバーを指定すれば、公開されているすべてのツールがエージェントで使えるようになります：

```yaml
spec:
  tools:
    - type: mcp
      transport: stdio
      command: npx
      args: ["-y", "@modelcontextprotocol/server-filesystem", "./data"]
    - type: mcp
      transport: sse
      url: https://my-mcp-server.example.com/sse
```

複数の MCP サーバーと組み込みツールを同時に使用可能。3つのトランスポート：`stdio`（ローカルプロセス）、`sse`（Server-Sent Events）、`streamable-http`。ツールフィルタリング（`tool_filter` / `tool_exclude`）と名前空間（`tool_prefix`）で、サーバーが多くのツールを公開する場合も整理できます。

逆方向も可能。エージェントを MCP ツールとして公開し、Claude Code、Cursor、Windsurf などの MCP クライアントから呼び出せます：

```bash
initrunner mcp serve agent.yaml            # エージェントが MCP ツールになる
initrunner mcp toolkit --tools search,sql  # LLM 不要で生ツールを公開
```

Dashboard の [MCP Hub](/mcp) では、全エージェントの MCP サーバーを一覧表示し、Playground で任意のツールを単独テストし、ドラッグ&ドロップキャンバスでサーバーとエージェントのトポロジーを視覚化できます。

[MCP Gateway](docs/interfaces/mcp-gateway.md) · [Dashboard](docs/interfaces/dashboard.md#mcp-hub-mcp) を参照。

## ユーザーインターフェース

<p align="center">
  <img src="assets/screenshot-dashboard.png" alt="InitRunner Dashboard" width="800"><br>
  <em>ダッシュボード：エージェント、アクティビティ、コンポジション、チームを一覧</em>
</p>

```bash
pip install "initrunner[dashboard]"
initrunner dashboard                  # http://localhost:8100 を開く
```

エージェントの実行、コンポジションの視覚的構築、監査証跡の詳細確認。ネイティブデスクトップウィンドウとしても利用可能（`initrunner desktop`）。[ダッシュボードドキュメント](docs/interfaces/dashboard.md) を参照。

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
| **推論**（構造化思考パターン） | `spec: { reasoning: { pattern: plan_execute } }` | [Reasoning](docs/core/reasoning.md) |
| **ツール検索**（オンデマンドツール発見） | `spec: { tool_search: { enabled: true } }` | [Tool Search](docs/core/tool-search.md) |

## アーキテクチャ

```
initrunner/
  agent/        ロールスキーマ、ローダー、エグゼキューター、28 の自己登録ツール
  authz.py      InitGuard ABAC ポリシーエンジン統合
  runner/       ワンショット、REPL、自律、デーモン実行モード
  compose/      compose.yaml によるマルチエージェントオーケストレーション
  triggers/     Cron、ファイルウォッチャー、webhook、ハートビート、Telegram、Discord
  stores/       ドキュメント + メモリストア（LanceDB、zvec）
  ingestion/    抽出 -> チャンク分割 -> 埋め込み -> 格納 パイプライン
  mcp/          MCP サーバー統合とゲートウェイ
  audit/        追記専用 SQLite 監査証跡、シークレットスクラブ付き
  middleware.py サーバーセキュリティミドルウェア（認証、レート制限、CORS、ヘッダー）
  services/     共有ビジネスロジック層
  cli/          Typer + Rich CLI エントリーポイント
```

エージェントフレームワークとして [PydanticAI](https://ai.pydantic.dev/)、設定バリデーションに Pydantic、ベクトル検索に LanceDB を使用。開発セットアップは [CONTRIBUTING.md](CONTRIBUTING.md) を参照。

## 配布

**InitHub:** [hub.initrunner.ai](https://hub.initrunner.ai/) でコミュニティエージェントを検索・インストール。`initrunner publish` で自分のエージェントを公開。[Registry](docs/agents/registry.md) を参照。

**OCI レジストリ:** ロールバンドルを任意の OCI 準拠レジストリにプッシュ: `initrunner publish oci://ghcr.io/org/my-agent --tag 1.0.0`。[OCI 配布](docs/core/oci-distribution.md) を参照。

**クラウドデプロイ:**

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/template/FROM_REPO?referralCode=...)
[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/vladkesler/initrunner)

## ドキュメント

| 領域 | 主要ドキュメント |
|------|---------------|
| 入門 | [Installation](docs/getting-started/installation.md) · [Setup](docs/getting-started/setup.md) · [Tutorial](docs/getting-started/tutorial.md) · [CLI Reference](docs/getting-started/cli.md) |
| クイックスタート | [RAG](docs/getting-started/rag-quickstart.md) · [Docker](docs/getting-started/docker.md) · [Discord Bot](docs/getting-started/discord.md) · [Telegram Bot](docs/getting-started/telegram.md) |
| エージェントとツール | [Tools](docs/agents/tools.md) · [Tool Creation](docs/agents/tool_creation.md) · [Tool Search](docs/core/tool-search.md) · [Skills](docs/agents/skills_feature.md) · [Providers](docs/configuration/providers.md) |
| インテリジェンス | [Reasoning](docs/core/reasoning.md) · [Intent Sensing](docs/core/intent_sensing.md) · [Autonomy](docs/orchestration/autonomy.md) · [Structured Output](docs/core/structured-output.md) |
| ナレッジとメモリ | [Ingestion](docs/core/ingestion.md) · [Memory](docs/core/memory.md) · [Multimodal Input](docs/core/multimodal.md) |
| オーケストレーション | [Patterns Guide](docs/orchestration/patterns-guide.md) · [Compose](docs/orchestration/agent_composer.md) · [Delegation](docs/orchestration/delegation.md) · [Team Mode](docs/orchestration/team_mode.md) · [Triggers](docs/core/triggers.md) |
| インターフェース | [Dashboard](docs/interfaces/dashboard.md) · [API Server](docs/interfaces/server.md) · [MCP Gateway](docs/interfaces/mcp-gateway.md) |
| 配布 | [OCI Distribution](docs/core/oci-distribution.md) · [Shareable Templates](docs/getting-started/shareable-templates.md) |
| セキュリティ | [Security Model](docs/security/security.md) · [Agent Policy](docs/security/agent-policy.md) · [Guardrails](docs/configuration/guardrails.md) |
| 運用 | [Audit](docs/core/audit.md) · [Reports](docs/core/reports.md) · [Evals](docs/core/evals.md) · [Doctor](docs/operations/doctor.md) · [Observability](docs/core/observability.md) · [CI/CD](docs/operations/cicd.md) |

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

<p align="center"><sub>v2026.4.4</sub></p>
