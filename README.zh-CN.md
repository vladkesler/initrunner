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

用一个 YAML 文件定义 Agent。和它对话。效果满意后，让它自主运行。信任它之后，部署为守护进程，响应 cron 调度、文件变更、webhook 和 Telegram 消息。同一个文件，从原型到生产，无需重写。

```bash
initrunner run researcher -i                            # 和它对话
initrunner run researcher -a -p "Audit this codebase"   # 让它自主工作
initrunner run researcher --daemon                      # 7x24 运行，响应触发器
```

## 快速开始

```bash
curl -fsSL https://initrunner.ai/install.sh | sh
initrunner setup        # 向导：选择提供商、模型、API 密钥
```

或: `uv pip install "initrunner[recommended]"` / `pipx install "initrunner[recommended]"`。查看 [安装指南](docs/getting-started/installation.md)。

### 入门模板

运行 `initrunner run --list` 查看完整目录。模型根据你的 API 密钥自动检测。

| 入门模板 | 功能描述 |
|---------|---------|
| `helpdesk` | 导入你的文档，获得带引用和记忆的问答 Agent |
| `deep-researcher` | 3-Agent 流水线：规划者、网络研究员、综合者 |
| `code-review-team` | 多视角审查：架构师、安全专家、维护者 |
| `codebase-analyst` | 索引你的仓库，聊架构，跨会话学习模式 |
| `content-pipeline` | 研究、撰写、编辑/事实核查，通过 webhook 或 cron 触发 |
| `email-agent` | 监控收件箱，分类消息，起草回复，紧急邮件通知 Slack |

### 创建自己的 Agent

```bash
initrunner new "a research assistant that summarizes papers"
# 生成 role.yaml，然后询问："现在运行吗？[Y/n]"

initrunner new "a regex explainer" --run "what does ^[a-z]+$ match?"
# 一条命令：生成并执行

initrunner run --ingest ./docs/    # 跳过 YAML，直接和你的文档聊天
```

在 [InitHub](https://hub.initrunner.ai/) 浏览社区 Agent: `initrunner search "code review"` / `initrunner install alice/code-reviewer`。

**Docker:**

```bash
docker run --rm -it -e OPENAI_API_KEY ghcr.io/vladkesler/initrunner:latest run -i
```

## 一个文件，四种模式

一个角色文件：

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

这个文件有四种用法：

```bash
initrunner run reviewer.yaml -i              # 交互式 REPL
initrunner run reviewer.yaml -p "Review PR #42"  # 一个提示，一个回复
initrunner run reviewer.yaml -a -p "Audit the whole repo"  # 自主模式：规划、执行、反思
initrunner run reviewer.yaml --daemon        # 持续运行，响应触发器
```

`model:` 部分是可选的。省略它，InitRunner 会根据你的 API 密钥自动检测。支持 Anthropic、OpenAI、Google、Groq、Mistral、Cohere、xAI、OpenRouter、Ollama 以及任何 OpenAI 兼容端点。

### 自主模式

加上 `-a`，Agent 不再是聊天机器人。它建立任务列表，逐项完成，反思进度，全部做完后自动停止。四种推理策略控制思考方式：`react`（默认）、`todo_driven`、`plan_execute` 和 `reflexion`。

```yaml
spec:
  autonomy:
    compaction: { enabled: true, threshold: 30 }
  guardrails:
    max_iterations: 15
    autonomous_token_budget: 100000
    autonomous_timeout_seconds: 600
```

空转检测捕获循环不前进的 Agent。历史压缩总结旧上下文，防止长时间运行耗尽 Token 窗口。预算约束、迭代限制和墙钟超时确保一切有界。查看 [自主执行](docs/orchestration/autonomy.md) · [护栏](docs/configuration/guardrails.md)。

### 守护进程模式

添加触发器并切换到 `--daemon`。Agent 持续运行，响应事件。每个事件触发一次提示-响应循环。

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
initrunner run role.yaml --daemon   # 运行直到 Ctrl+C
```

六种触发器类型：cron、webhook、file_watch、heartbeat、telegram、discord。守护进程热重载角色变更无需重启，最多同时运行 4 个触发器。查看 [触发器](docs/core/triggers.md)。

### 自动驾驶

`--autopilot` 就是 `--daemon`，但每个触发器走完整的自主循环。有人给你的 Telegram 机器人发消息"帮我找从纽约到伦敦下周的航班"。在守护进程模式下，你只有一次回答机会。在自动驾驶模式下，Agent 搜索网络、比较选项、核对日期，然后发回有价值的答案。

```bash
initrunner run role.yaml --autopilot
```

你也可以有选择性地设置。在单个触发器上设置 `autonomous: true`，其余保持单次响应：

```yaml
spec:
  triggers:
    - type: telegram
      autonomous: true          # 思考、研究，然后回复
    - type: cron
      schedule: "0 9 * * 1"
      prompt: "Generate the weekly status report."
      autonomous: true          # 规划、收集数据、撰写、审查
    - type: file_watch
      paths: [./src]
      prompt_template: "File changed: {path}. Review it."
      # 默认：快速单次响应
```

### 记忆贯穿一切

情景记忆、语义记忆和程序记忆在交互式会话、自主运行和守护进程触发之间持久化。每次会话结束后，整合过程使用 LLM 从对话中提取持久事实。Agent 不只是运行，它随时间积累知识。

## 会学习的 Agent

将你的 Agent 指向一个目录。它会自动提取、分块、嵌入并索引你的文档。对话过程中，Agent 自动搜索索引并引用找到的内容。新增和变更的文件每次运行时自动重新索引，无需人工干预。

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
cd ~/myproject
initrunner run codebase-analyst -i   # 索引你的代码，然后开始问答
```

关键在于整合。每次会话结束后，LLM 阅读发生了什么，并将其提炼到语义存储中。Agent 在周二调试会话中学到的事实，会在周四审查代码时出现。Flow 中的共享记忆让 Agent 团队共同积累知识。查看 [记忆](docs/core/memory.md) · [摄入](docs/core/ingestion.md) · [RAG 快速开始](docs/getting-started/rag-quickstart.md)。

## 安全是配置，不是工程

大多数 Agent 框架把安全当作"到了生产再加认证中间件"。InitRunner 出厂就集成了安全功能。你通过配置项启用它们，不需要花一个周末去接管道。

**Agent 接受不可信输入。** 内容策略引擎（禁止模式、提示长度限制、可选的 LLM 话题分类器）和输入守卫能力在 Agent 启动前验证提示。

**Agent 调用有实际后果的工具。** [InitGuard](https://github.com/initrunner/initguard) ABAC 策略引擎根据 CEL 策略检查每次工具调用和委托。每个工具的 allow/deny glob 模式执行参数级权限。

**Agent 执行代码。** PEP 578 审计钩子沙箱限制文件系统写入、阻止子进程、阻止私有 IP 网络访问、阻止危险导入。Docker 容器沙箱在此基础上增加只读根文件系统、内存/CPU 限制和网络隔离。

**一切都有记录。** 仅追加 SQLite 审计日志，自动敏感信息清理。正则模式从提示和输出中脱敏 GitHub Token、AWS 密钥、Stripe 密钥等。

这些通过 `security:` 配置项启用，不是自动生效。没有 `security:` 部分的角色会获得安全默认值。重点是这些能力存在于框架内，而不是在生产六个月后从第三方库补上。

```bash
export INITRUNNER_POLICY_DIR=./policies
initrunner run role.yaml    # 工具调用 + 委托根据策略检查
```

查看 [Agent 策略](docs/security/agent-policy.md) · [安全](docs/security/security.md) · [护栏](docs/configuration/guardrails.md)。

## 成本控制

Token 预算是基本操作。InitRunner 还支持 USD 成本预算。为守护进程设置每日或每周美元上限，达到阈值后停止触发。

```yaml
spec:
  guardrails:
    daemon_daily_cost_budget: 5.00    # 每日 USD
    daemon_weekly_cost_budget: 25.00  # 每周 USD
```

成本估算使用 [genai-prices](https://pypi.org/project/genai-prices/) 计算每个模型和提供商的实际支出。每次运行的成本记录到审计日志。仪表盘显示跨 Agent 和时间范围的成本分析。查看 [成本追踪](docs/core/cost-tracking.md)。

## 多 Agent 编排

将 Agent 串联为 Flow。一个 Agent 的输出传入下一个。智能路由先用关键词评分自动选择目标（零 API 调用），仅在关键词模糊时用 LLM 仲裁：

```yaml
apiVersion: initrunner/v1
kind: Flow
metadata: { name: email-chain }
spec:
  agents:
    inbox-watcher:
      role: roles/inbox-watcher.yaml
      sink: { type: delegate, target: triager }
    triager:
      role: roles/triager.yaml
      sink: { type: delegate, strategy: sense, target: [researcher, responder] }
    researcher: { role: roles/researcher.yaml }
    responder: { role: roles/responder.yaml }
```

```bash
initrunner flow up flow.yaml
```

**团队模式** 适用于需要多视角处理同一任务但不需要完整 Flow 的场景。在一个文件中定义多个角色，三种策略：顺序交接、并行执行或辩论（多轮论证加综合）。查看 [模式指南](docs/orchestration/patterns-guide.md) · [团队模式](docs/orchestration/team_mode.md) · [Flow](docs/orchestration/flow.md)。

## MCP 与界面

Agent 可以使用任何 [MCP](https://modelcontextprotocol.io/) 服务器作为工具来源（stdio、SSE、streamable-http）。反过来，也可以把你的 Agent 暴露为 MCP 工具，让 Claude Code、Cursor 和 Windsurf 调用：

```bash
initrunner mcp serve agent.yaml          # Agent 变成 MCP 工具
initrunner mcp toolkit --tools search,sql  # 暴露原始工具，无需 LLM
```

查看 [MCP Gateway](docs/interfaces/mcp-gateway.md)。

<p align="center">
  <img src="assets/screenshot-dashboard.png" alt="InitRunner Dashboard" width="800"><br>
  <em>仪表盘：运行 Agent、构建 Flow、查看审计日志</em>
</p>

```bash
pip install "initrunner[dashboard]"
initrunner dashboard                  # 打开 http://localhost:8100
```

也可作为原生桌面窗口使用（`initrunner desktop`）。查看 [仪表盘文档](docs/interfaces/dashboard.md)。

## 更多功能

| 功能 | 命令 / 配置 | 文档 |
|-----|-----------|------|
| **技能**（可复用的工具 + 提示词包） | `spec: { skills: [../skills/web-researcher] }` | [Skills](docs/agents/skills_feature.md) |
| **API 服务器**（OpenAI 兼容端点） | `initrunner run agent.yaml --serve --port 3000` | [Server](docs/interfaces/server.md) |
| **A2A 服务器**（Agent 间协议） | `initrunner a2a serve agent.yaml` | [A2A](docs/interfaces/a2a.md) |
| **多模态**（图像、音频、视频、文档） | `initrunner run role.yaml -p "Describe" -A photo.png` | [Multimodal](docs/core/multimodal.md) |
| **结构化输出**（验证的 JSON Schema） | `spec: { output: { schema: {...} } }` | [Structured Output](docs/core/structured-output.md) |
| **评估**（测试 Agent 输出质量） | `initrunner test role.yaml -s eval.yaml` | [Evals](docs/core/evals.md) |
| **能力**（原生 PydanticAI 功能） | `spec: { capabilities: [Thinking, WebSearch] }` | [Capabilities](docs/core/capabilities.md) |
| **可观测性**（OpenTelemetry） | `spec: { observability: { enabled: true } }` | [Observability](docs/core/observability.md) |
| **推理**（结构化思维模式） | `spec: { reasoning: { pattern: plan_execute } }` | [Reasoning](docs/core/reasoning.md) |
| **工具搜索**（按需工具发现） | `spec: { tool_search: { enabled: true } }` | [Tool Search](docs/core/tool-search.md) |
| **配置**（切换提供商/模型） | `initrunner configure role.yaml --provider groq` | [Providers](docs/configuration/providers.md) |

## 架构

```
initrunner/
  agent/        角色 Schema、加载器、执行器、自注册工具
  runner/       一次性、REPL、自主、守护进程执行模式
  flow/         通过 flow.yaml 的多 Agent 编排
  triggers/     Cron、文件监听、webhook、心跳、Telegram、Discord
  stores/       文档 + 记忆存储（LanceDB、zvec）
  ingestion/    提取 -> 分块 -> 嵌入 -> 存储 流水线
  mcp/          MCP 服务器集成与网关
  audit/        仅追加 SQLite 审计日志，带敏感信息清理
  services/     共享业务逻辑层
  cli/          Typer + Rich CLI 入口
```

基于 [PydanticAI](https://ai.pydantic.dev/) 构建。查看 [CONTRIBUTING.md](CONTRIBUTING.md) 了解开发配置。

## 分发

**InitHub:** 在 [hub.initrunner.ai](https://hub.initrunner.ai/) 浏览和安装社区 Agent。使用 `initrunner publish` 发布你自己的。

**OCI 注册表:** 将角色包推送到任何 OCI 兼容注册表: `initrunner publish oci://ghcr.io/org/my-agent --tag 1.0.0`。查看 [OCI 分发](docs/core/oci-distribution.md)。

**云部署:**

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/template/FROM_REPO?referralCode=...)
[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/vladkesler/initrunner)

## 文档

| 领域 | 关键文档 |
|------|---------|
| 入门 | [Installation](docs/getting-started/installation.md) · [Setup](docs/getting-started/setup.md) · [Tutorial](docs/getting-started/tutorial.md) · [CLI Reference](docs/getting-started/cli.md) |
| 快速开始 | [RAG](docs/getting-started/rag-quickstart.md) · [Docker](docs/getting-started/docker.md) · [Discord Bot](docs/getting-started/discord.md) · [Telegram Bot](docs/getting-started/telegram.md) |
| Agent 与工具 | [Tools](docs/agents/tools.md) · [Tool Creation](docs/agents/tool_creation.md) · [Tool Search](docs/core/tool-search.md) · [Skills](docs/agents/skills_feature.md) · [Providers](docs/configuration/providers.md) |
| 智能 | [Reasoning](docs/core/reasoning.md) · [Intent Sensing](docs/core/intent_sensing.md) · [Autonomy](docs/orchestration/autonomy.md) · [Structured Output](docs/core/structured-output.md) |
| 知识与记忆 | [Ingestion](docs/core/ingestion.md) · [Memory](docs/core/memory.md) · [Multimodal Input](docs/core/multimodal.md) |
| 编排 | [Patterns Guide](docs/orchestration/patterns-guide.md) · [Flow](docs/orchestration/flow.md) · [Delegation](docs/orchestration/delegation.md) · [Team Mode](docs/orchestration/team_mode.md) · [Triggers](docs/core/triggers.md) |
| 界面 | [Dashboard](docs/interfaces/dashboard.md) · [API Server](docs/interfaces/server.md) · [MCP Gateway](docs/interfaces/mcp-gateway.md) · [A2A](docs/interfaces/a2a.md) |
| 分发 | [OCI Distribution](docs/core/oci-distribution.md) · [Shareable Templates](docs/getting-started/shareable-templates.md) |
| 安全 | [Security Model](docs/security/security.md) · [Agent Policy](docs/security/agent-policy.md) · [Guardrails](docs/configuration/guardrails.md) |
| 运维 | [Audit](docs/core/audit.md) · [Cost Tracking](docs/core/cost-tracking.md) · [Reports](docs/core/reports.md) · [Evals](docs/core/evals.md) · [Doctor](docs/operations/doctor.md) · [Observability](docs/core/observability.md) · [CI/CD](docs/operations/cicd.md) |

## 示例

```bash
initrunner examples list               # 浏览所有 Agent、团队和 Flow 项目
initrunner examples copy code-reviewer # 复制到当前目录
```

## 升级

运行 `initrunner doctor --role role.yaml` 检查角色文件的废弃字段、Schema 错误和规范版本问题。添加 `--fix` 自动修复。查看 [废弃说明](docs/operations/deprecations.md)。

## 社区

- [Discord](https://discord.gg/GRTZmVcW): 聊天、提问、分享角色
- [GitHub Issues](https://github.com/vladkesler/initrunner/issues): Bug 报告和功能请求
- [Changelog](CHANGELOG.md): 发布说明
- [CONTRIBUTING.md](CONTRIBUTING.md): 开发配置和 PR 指南

## 许可证

根据 [MIT](LICENSE-MIT) 或 [Apache-2.0](LICENSE-APACHE) 许可，由你选择。

---

<p align="center"><sub>v2026.4.10</sub></p>
