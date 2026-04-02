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
  <a href="https://initrunner.ai/">官网</a> · <a href="https://initrunner.ai/docs">文档</a> · <a href="https://hub.initrunner.ai/">InitHub</a> · <a href="https://discord.gg/GRTZmVcW">Discord</a>
</p>

<p align="center">
  <a href="README.md">English</a> · 简体中文 · <a href="README.ja.md">日本語</a>
</p>

> **注意:** 这是社区翻译版本。以 [英文 README](README.md) 为准。翻译内容可能滞后于最新更新。

YAML 优先的 AI Agent 平台。在一个文件中定义 Agent 的角色、工具、知识库和记忆。可作为交互式聊天、一次性命令、带 cron/webhook/文件监听触发器的自动守护进程、Telegram/Discord 机器人或 OpenAI 兼容 API 运行。RAG 和持久化记忆开箱即用。通过 Web 仪表盘或原生桌面应用管理一切。使用 `curl` 或 `pip` 安装，无需容器。

```bash
initrunner run helpdesk -i                                    # 文档问答，支持 RAG + 记忆
initrunner run deep-researcher -p "Compare vector databases"  # 3-Agent 研究团队
initrunner run code-review-team -p "Review the latest commit" # 多视角代码审查
```

15 个精选入门模板，60+ 示例，或自定义你自己的。

> **v2026.4.2**: PydanticAI + LangChain Agent 导入。使用 `initrunner new --pydantic-ai my_agent.py` 或 `--langchain` 转换现有 Agent。查看 [更新日志](CHANGELOG.md)。

## 快速开始

```bash
curl -fsSL https://initrunner.ai/install.sh | sh
initrunner setup        # 向导：选择提供商、模型、API 密钥
```

或: `uv pip install "initrunner[recommended]"` / `pipx install "initrunner[recommended]"`。查看 [安装指南](docs/getting-started/installation.md)。

### 试用入门模板

运行 `initrunner run --list` 查看完整目录。模型根据你的 API 密钥自动检测。

| 入门模板 | 功能描述 | 类型 |
|---------|---------|------|
| `helpdesk` | 导入你的文档，获得带引用和记忆的问答 Agent | Agent (RAG) |
| `code-review-team` | 多视角审查：架构师、安全专家、维护者 | Team |
| `deep-researcher` | 3-Agent 流水线：规划者、网络研究员、综合者，共享记忆 | Team |
| `codebase-analyst` | 索引你的仓库，聊架构，跨会话学习模式 | Agent (RAG) |
| `web-researcher` | 搜索网络，生成带引用的结构化简报 | Agent |
| `content-pipeline` | 话题研究、撰写、编辑/事实核查，通过 webhook 或 cron 触发 | Compose |
| `telegram-assistant` | 带记忆和网络搜索的 Telegram 机器人 | Agent (Daemon) |
| `email-agent` | 监控收件箱，分类消息，起草回复，紧急邮件通知 Slack | Agent (Daemon) |
| `support-desk` | 智能路由：自动分发到研究员、回复者或升级处理 | Compose |
| `memory-assistant` | 跨会话记忆的个人助手 | Agent |

RAG 入门模板首次运行时自动摄入。只需 `cd` 到你的项目目录：

```bash
cd ~/myproject
initrunner run codebase-analyst -i   # 索引你的代码，然后开始问答
```

### 创建自己的 Agent

```bash
initrunner new "a research assistant that summarizes papers"  # 生成 role.yaml
initrunner run --ingest ./docs/    # 或跳过 YAML，直接和你的文档聊天
```

在 [InitHub](https://hub.initrunner.ai/) 浏览和安装社区 Agent: `initrunner search "code review"` / `initrunner install alice/code-reviewer`。

**Docker**，无需安装：

```bash
docker run -d -e OPENAI_API_KEY -p 8100:8100 \
    -v initrunner-data:/data ghcr.io/vladkesler/initrunner:latest        # 仪表盘
docker run --rm -it -e OPENAI_API_KEY \
    -v initrunner-data:/data ghcr.io/vladkesler/initrunner:latest run -i # 聊天
```

更多内容查看 [Docker 指南](docs/getting-started/docker.md)。

## 用 YAML 定义 Agent

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

`model:` 部分是可选的；省略它，InitRunner 会根据你的 API 密钥自动检测。支持 Anthropic、OpenAI、Google、Groq、Mistral、Cohere、xAI、OpenRouter、Ollama 以及任何 OpenAI 兼容端点。28 个内置工具（文件系统、git、HTTP、Python、shell、SQL、搜索、邮件、Slack、MCP、音频、PDF 提取、CSV 分析、图像生成），你还可以用一个文件[添加自己的工具](docs/agents/tool_creation.md)。

## 为什么选择 InitRunner

一个 YAML 文件*就是* Agent。工具、知识源、记忆、触发器、模型、护栏，全部声明在一处。你可以阅读它，立即理解 Agent 做什么。你可以 diff 它，在 PR 中审查它，交给队友。当你想从 GPT 切换到 Claude，只需改一行。当你想添加 RAG，加一个 `ingest:` 部分。

同一个文件可以作为交互式聊天（`-i`）、一次性命令（`-p "..."`）、cron/webhook/文件监听守护进程（`--daemon`）或 OpenAI 兼容 API（`--serve`）运行。你不需要预先选择部署模式然后围绕它构建。你在运行时用一个标志选择。

实际上这意味着：你的 Agent 配置和代码一起存在版本控制中。新团队成员阅读 YAML 就能理解 Agent 做什么。你在 PR 中审查 Agent 变更，就像审查其他配置一样。你交互式原型的 Agent 就是你部署为守护进程或 API 的那个。同一个文件，不同的标志。

## 横向对比

|  | InitRunner | LangChain | CrewAI | AutoGen |
|---|---|---|---|---|
| **Agent 配置** | YAML 文件 | Python chains + 配置 | Python 类 | Python 类 |
| **RAG** | `--ingest ./docs/`（一个标志） | Loaders + splitters + vectorstore | RAG 工具或自定义 | 外部配置 |
| **记忆** | 内置，默认开启 | 附加组件（多种选项） | 短期/长期记忆 | 外部 |
| **多 Agent** | `compose.yaml` 或 `kind: Team` | LangGraph | Crew 定义 | Group chat |
| **部署模式** | 同一 YAML: REPL / 守护进程 / API | 每种模式自定义 | CLI 或 Kickoff | 自定义 |
| **模型切换** | 改 1 行 YAML | 替换 LLM 类 | 每个 Agent 配置 | 每个 Agent 配置 |
| **自定义工具** | 1 个文件，1 个装饰器 | `@tool` 装饰器 | `@tool` 装饰器 | Function call |
| **Bot 部署** | `--telegram` / `--discord` 标志 | 单独集成 | 单独集成 | 单独集成 |
| **迁移** | `--pydantic-ai` / `--langchain` 导入 | N/A | N/A | N/A |

## 功能概览

### 知识库与记忆

将你的 Agent 指向一个目录。它会自动提取、分块、嵌入并索引你的文档。对话过程中，Agent 自动搜索索引并引用找到的内容。记忆跨会话持久化。

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
initrunner run role.yaml -i   # 首次运行自动摄入，记忆 + 搜索就绪
```

查看 [摄入](docs/core/ingestion.md) · [记忆](docs/core/memory.md) · [RAG 快速开始](docs/getting-started/rag-quickstart.md)。

### 触发器与守护进程

将任何 Agent 变成对 cron 计划、文件变更、webhook 或心跳做出反应的守护进程：

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
initrunner run role.yaml --daemon   # 运行直到停止
```

查看 [触发器](docs/core/triggers.md) · [Telegram](docs/getting-started/telegram.md) · [Discord](docs/getting-started/discord.md)。

### 多 Agent 编排

将 Agent 串联起来。一个 Agent 的输出传入下一个。智能路由根据每条消息自动选择正确的目标（先关键词匹配，平局时用单次 LLM 调用打破）：

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

运行 `initrunner compose up compose.yaml`。查看 [模式指南](docs/orchestration/patterns-guide.md) · [Compose](docs/orchestration/agent_composer.md)。

### 推理与工具管理

控制你的 Agent 如何思考，而不仅仅是做什么：

```yaml
spec:
  reasoning:
    pattern: plan_execute    # 先规划，然后逐步执行
    auto_plan: true
  tools:
    - type: think            # 内部草稿本，带自我批评
      critique: true
    - type: todo             # 结构化任务列表，用于多步骤工作
```

四种推理模式：`react`、`todo_driven`、`plan_execute` 和 `reflexion`。查看 [推理](docs/core/reasoning.md)。

工具多的 Agent 会浪费上下文并选择更差。工具搜索将工具隐藏在按需关键词发现之后：Agent 只看到 `search_tools` 和几个固定工具，然后按需发现每轮需要的。BM25 评分，无 API 调用，通常节省 60-80% 上下文。查看 [工具搜索](docs/core/tool-search.md)。

## 架构

```
initrunner/
  agent/        角色 Schema、加载器、执行器、28 个自注册工具
  runner/       一次性、REPL、自主、守护进程执行模式
  compose/      通过 compose.yaml 的多 Agent 编排
  triggers/     Cron、文件监听、webhook、心跳、Telegram、Discord
  stores/       文档 + 记忆存储（LanceDB、zvec）
  ingestion/    提取 -> 分块 -> 嵌入 -> 存储 流水线
  mcp/          MCP 服务器集成与网关
  audit/        仅追加 SQLite 审计日志
  services/     共享业务逻辑层
  cli/          Typer + Rich CLI 入口
```

基于 [PydanticAI](https://ai.pydantic.dev/) 构建 Agent 框架，Pydantic 用于配置验证，LanceDB 用于向量搜索。查看 [CONTRIBUTING.md](CONTRIBUTING.md) 了解开发配置。

## 安全

InitRunner 内置了 [initguard](https://github.com/initrunner/initguard) 策略引擎。Agent 从角色元数据（名称、团队、标签、作者）获取身份，每次工具调用和委托都会根据你的策略进行检查：

- **工具级授权**：Agent 只能调用其策略允许的工具
- **委托策略**：控制哪些 Agent 可以委托给哪些其他 Agent
- **内容过滤**：输入护栏，带可配置的内容策略
- **PEP 578 沙箱**：危险操作的审计钩子
- **Docker 隔离**：可选的沙箱执行环境
- **Token 预算和速率限制**：防止成本失控
- **环境变量清理**：敏感密钥从子进程环境中剥离
- **仅追加审计日志**：每次工具调用记录到 SQLite

```bash
export INITRUNNER_POLICY_DIR=./policies
initrunner run role.yaml                  # 工具调用 + 委托根据策略检查
```

查看 [Agent 策略](docs/security/agent-policy.md) · [安全](docs/security/security.md) · [护栏](docs/configuration/guardrails.md)。

## 用户界面

<p align="center">
  <img src="assets/screenshot-dashboard.png" alt="InitRunner Dashboard" width="800"><br>
  <em>仪表盘：Agent、活动、编排和团队一览</em>
</p>

```bash
pip install "initrunner[dashboard]"
initrunner dashboard                  # 打开 http://localhost:8100
```

浏览 Agent、运行提示、可视化构建编排、配置推理模式、审查审计日志。也可作为原生桌面窗口使用（`initrunner desktop`）。查看 [仪表盘文档](docs/interfaces/dashboard.md)。

## 更多功能

| 功能 | 命令 / 配置 | 文档 |
|-----|-----------|------|
| **技能**（可复用的工具 + 提示词包） | `spec: { skills: [../skills/web-researcher] }` | [Skills](docs/agents/skills_feature.md) |
| **团队模式**（多角色处理同一任务） | `kind: Team` + `spec: { personas: {…} }` | [Team Mode](docs/orchestration/team_mode.md) |
| **API 服务器**（OpenAI 兼容端点） | `initrunner run agent.yaml --serve --port 3000` | [Server](docs/interfaces/server.md) |
| **多模态**（图像、音频、视频、文档） | `initrunner run role.yaml -p "Describe" -A photo.png` | [Multimodal](docs/core/multimodal.md) |
| **结构化输出**（验证的 JSON Schema） | `spec: { output: { schema: {…} } }` | [Structured Output](docs/core/structured-output.md) |
| **评估**（测试 Agent 输出质量） | `initrunner test role.yaml -s eval.yaml` | [Evals](docs/core/evals.md) |
| **MCP 网关**（将 Agent 暴露为 MCP 工具） | `initrunner mcp serve agent.yaml` | [MCP Gateway](docs/interfaces/mcp-gateway.md) |
| **MCP 工具箱**（无 Agent 的工具） | `initrunner mcp toolkit` | [MCP Gateway](docs/interfaces/mcp-gateway.md) |
| **能力**（原生 PydanticAI 功能） | `spec: { capabilities: [Thinking, WebSearch] }` | [Capabilities](docs/core/capabilities.md) |
| **可观测性**（OpenTelemetry 集成） | `spec: { observability: { enabled: true } }` | [Observability](docs/core/observability.md) |
| **配置**（切换任意角色的提供商/模型） | `initrunner configure role.yaml --provider groq` | [Providers](docs/configuration/providers.md) |

## 分发

**InitHub:** 在 [hub.initrunner.ai](https://hub.initrunner.ai/) 浏览和安装社区 Agent。使用 `initrunner publish` 发布你自己的。查看 [Registry](docs/agents/registry.md)。

**OCI 注册表:** 将角色包推送到任何 OCI 兼容注册表: `initrunner publish oci://ghcr.io/org/my-agent --tag 1.0.0`。查看 [OCI 分发](docs/core/oci-distribution.md)。

**云部署:**

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/template/FROM_REPO?referralCode=...)
[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/vladkesler/initrunner)

## 文档

| 领域 | 关键文档 |
|------|---------|
| 入门 | [Installation](docs/getting-started/installation.md) · [Setup](docs/getting-started/setup.md) · [RAG Quickstart](docs/getting-started/rag-quickstart.md) · [Tutorial](docs/getting-started/tutorial.md) · [CLI Reference](docs/getting-started/cli.md) · [Docker](docs/getting-started/docker.md) · [Discord Bot](docs/getting-started/discord.md) · [Telegram Bot](docs/getting-started/telegram.md) |
| Agent 与工具 | [Tools](docs/agents/tools.md) · [Tool Creation](docs/agents/tool_creation.md) · [Tool Search](docs/core/tool-search.md) · [Skills](docs/agents/skills_feature.md) · [Structured Output](docs/core/structured-output.md) · [Providers](docs/configuration/providers.md) |
| 智能 | [Reasoning](docs/core/reasoning.md) · [Intent Sensing](docs/core/intent_sensing.md) · [Tool Search](docs/core/tool-search.md) · [Autonomy](docs/orchestration/autonomy.md) |
| 知识与记忆 | [Ingestion](docs/core/ingestion.md) · [Memory](docs/core/memory.md) · [Multimodal Input](docs/core/multimodal.md) |
| 编排 | [Patterns Guide](docs/orchestration/patterns-guide.md) · [Compose](docs/orchestration/agent_composer.md) · [Delegation](docs/orchestration/delegation.md) · [Team Mode](docs/orchestration/team_mode.md) · [Autonomy](docs/orchestration/autonomy.md) · [Triggers](docs/core/triggers.md) |
| 界面 | [Dashboard](docs/interfaces/dashboard.md) · [API Server](docs/interfaces/server.md) · [MCP Gateway](docs/interfaces/mcp-gateway.md) |
| 分发 | [OCI Distribution](docs/core/oci-distribution.md) · [Shareable Templates](docs/getting-started/shareable-templates.md) |
| 运维 | [Security](docs/security/security.md) · [Agent Policy](docs/security/agent-policy.md) · [Guardrails](docs/configuration/guardrails.md) · [Audit](docs/core/audit.md) · [Reports](docs/core/reports.md) · [Evals](docs/core/evals.md) · [Doctor](docs/operations/doctor.md) · [Observability](docs/core/observability.md) · [CI/CD](docs/operations/cicd.md) |

## 示例

```bash
initrunner examples list               # 60+ Agent、团队和 Compose 项目
initrunner examples copy code-reviewer # 复制到当前目录
```

## 升级

运行 `initrunner doctor --role role.yaml` 检查任何角色文件的废弃字段、Schema 错误和规范版本问题。添加 `--fix` 自动修复，或 `--fix --yes` 用于 CI。查看 [废弃说明](docs/operations/deprecations.md)。

## 社区与贡献

- [Discord](https://discord.gg/GRTZmVcW): 聊天、提问、分享角色
- [GitHub Issues](https://github.com/vladkesler/initrunner/issues): Bug 报告和功能请求
- [Changelog](CHANGELOG.md): 发布说明

欢迎贡献！查看 [CONTRIBUTING.md](CONTRIBUTING.md) 了解开发配置和 PR 指南。

## 许可证

根据 [MIT](LICENSE-MIT) 或 [Apache-2.0](LICENSE-APACHE) 许可，由你选择。

---

<p align="center"><sub>v2026.4.2</sub></p>
