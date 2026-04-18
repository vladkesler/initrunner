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

## 快速开始

```bash
curl -fsSL https://initrunner.ai/install.sh | sh
initrunner setup        # 向导：选择提供商、模型、API 密钥
```

或: `uv pip install "initrunner[recommended]"` / `pipx install "initrunner[recommended]"`。查看 [安装指南](docs/getting-started/installation.md)。

### 入门模板

八个一条命令即可运行的入门模板。用 `initrunner run --list` 浏览完整目录。模型根据你的 API 密钥自动检测。

| 入门模板 | 功能描述 |
|---------|---------|
| `helpdesk` | 针对你的文档（Markdown、PDF、HTML、Word）的问答 Agent，带引用和按用户记忆 |
| `scholar` | 三 Agent 研究团队：规划者、网络研究员、综合者，共享记忆 |
| `reviewer` | 多视角代码审查：架构师、安全专家、维护者 |
| `reader` | 索引代码库，聊架构，跨会话记忆模式 |
| `scout` | 网络研究，产出带引用的结构化简报 |
| `writer` | 主题到文章流水线：研究员、撰稿人、编辑/事实核查员，由 webhook 或 cron 驱动 |
| `mail` | 监控收件箱，分类消息，起草回复，紧急邮件通知 Slack |
| `librarian` | 带文档摄入的知识库问答 Agent |

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
initrunner run reviewer.yaml -i                          # 交互式 REPL
initrunner run reviewer.yaml -p "Review PR #42"          # 一个提示，一个回复
initrunner run reviewer.yaml -a -p "Audit the whole repo"  # 自主循环
initrunner run reviewer.yaml --daemon                    # 由触发器驱动
```

`model:` 部分是可选的。省略它，InitRunner 会根据你的 API 密钥自动检测。支持 Anthropic、OpenAI、Google、Groq、Mistral、Cohere、xAI、OpenRouter、Ollama 以及任何 OpenAI 兼容端点。

### 自主模式

加上 `-a`，Agent 建立任务列表，逐项处理，反思进度，全部完成后自动停止。四种推理策略控制思考方式：`react`（默认）、`todo_driven`、`plan_execute` 和 `reflexion`。

```yaml
spec:
  autonomy:
    compaction: { enabled: true, threshold: 30 }
  guardrails:
    max_iterations: 15
    autonomous_token_budget: 100000
    autonomous_timeout_seconds: 600
```

空转检测捕获无进展的循环。历史压缩总结旧上下文，防止长时间运行耗尽 Token 窗口。迭代、Token 和墙钟上限约束每次运行。查看 [自主执行](docs/orchestration/autonomy.md) · [护栏](docs/configuration/guardrails.md)。

### 守护进程

添加触发器并切换到 `--daemon`。Agent 持续运行。每个事件触发一次提示-响应循环。

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

六种触发器类型：cron、webhook、file_watch、heartbeat、telegram、discord。守护进程热重载角色变更无需重启，最多同时运行四个触发器。查看 [触发器](docs/core/triggers.md)。

### 自动驾驶

`--autopilot` 就是 `--daemon` 加上每个触发器的自主循环。Telegram 消息 "帮我找从纽约到伦敦下周的航班" 在守护进程模式下只有一次 LLM 轮次。在自动驾驶模式下，Agent 搜索航班、比较选项、核对日期，然后回复一份候选列表。

```bash
initrunner run role.yaml --autopilot
```

也可以有选择地启用。在单个触发器上设置 `autonomous: true`，其余保持单次响应：

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
      # 默认：单次响应
```

### 跨模式的记忆

语义记忆（Agent 学到的事实）、情景记忆（过去会话中发生的事）和程序记忆（Agent 倾向的解决方式）在交互式会话、自主运行和守护进程触发之间持久化。每次会话后，LLM 将持久事实整合到存储中。知识随时间积累，不只是在单次运行内。

## 会学习的 Agent

将 Agent 指向一个目录。它会自动提取、分块、嵌入并索引文档。对话时，Agent 搜索索引并引用找到的内容。新增和变更的文件每次运行时重新索引。

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
initrunner run reader -i   # 索引代码，然后开始问答
```

关键在于整合。每次会话结束后，LLM 阅读对话并将其提炼到语义存储中。Agent 在周二调试会话中学到的事实，会在周四审查代码时出现。Flow 中的共享记忆让 Agent 团队共同积累知识。查看 [记忆](docs/core/memory.md) · [摄入](docs/core/ingestion.md) · [RAG 快速开始](docs/getting-started/rag-quickstart.md)。

## 安全

五个随框架内置、通过配置项启用的控制项。没有 `security:` 部分的角色使用安全默认值。

**输入验证。** 内容策略引擎（禁止模式、提示长度限制、可选的 LLM 话题分类器）和输入守卫能力在 Agent 启动前验证提示。

**工具授权。** [InitGuard](https://github.com/initrunner/initguard) ABAC 策略引擎根据 CEL 策略检查每次工具调用和委托。每个工具的 allow/deny glob 模式执行参数级权限。

**代码执行沙箱。** 审计钩子阻止 python 工具写入允许列表之外的路径、启动子进程、访问私有 IP、加载原生库或创建新线程。如需更强的隔离，Linux 上的 [Bubblewrap](docs/security/bubblewrap.md) 或任意平台的 [Docker](docs/security/docker-sandbox.md) 会在运行 shell 和 python 工具时强制无网络、只读文件系统以及内存和 CPU 上限。

**防篡改审计日志。** 每次运行写入仅追加的 SQLite 审计日志，用 HMAC-SHA256 对前一条记录的哈希进行签名。`initrunner audit verify-chain` 可检测任何中间记录的修改、重排或删除。敏感信息在写入时脱敏。

**加密凭证保险库。** `initrunner vault init` 创建 `~/.initrunner/vault.enc`，使用 Fernet + scrypt 根据你的口令加密。API 密钥先从环境变量解析，然后从保险库，所以现有的 `api_key_env:` 和 `${VAR}` 占位符继续工作。

```yaml
spec:
  security:
    audit_hooks_enabled: true
    block_private_ips: true
    input_guard:
      max_prompt_chars: 10000
      blocked_patterns: ["(?i)rm -rf /"]
```

查看 [安全](docs/security/security.md) · [Bubblewrap](docs/security/bubblewrap.md) · [Docker 沙箱](docs/security/docker-sandbox.md) · [Agent 策略](docs/security/agent-policy.md) · [凭证保险库](docs/security/vault.md) · [审计链](docs/security/audit-chain.md) · [护栏](docs/configuration/guardrails.md)。

## 成本控制

USD 预算限制守护进程支出。达到上限后，触发器停止发火，直到窗口重置。

```yaml
spec:
  guardrails:
    daemon_daily_cost_budget: 5.00    # 每日 USD
    daemon_weekly_cost_budget: 25.00  # 每周 USD
```

成本估算使用 [genai-prices](https://pypi.org/project/genai-prices/) 按模型和提供商计算支出。每次运行的成本记录到审计日志。仪表盘绘制跨 Agent 和时间范围的成本曲线。查看 [成本追踪](docs/core/cost-tracking.md)。

## 多 Agent 编排

将 Agent 串联为 Flow。一个 Agent 的输出传入下一个。

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

智能路由先用关键词评分选择目标（零 API 调用），仅在关键词模糊时才用 LLM 仲裁。

**团队模式** 适用于需要多视角处理同一任务、但不需要完整 Flow 的场景。在一个文件中定义多个角色，三种策略：顺序交接、并行执行或辩论（多轮论证加综合）。查看 [模式指南](docs/orchestration/patterns-guide.md) · [团队模式](docs/orchestration/team_mode.md) · [Flow](docs/orchestration/flow.md)。

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
| 安全 | [Security Model](docs/security/security.md) · [Runtime Sandbox](docs/security/sandbox.md) · [Bubblewrap](docs/security/bubblewrap.md) · [Docker Sandbox](docs/security/docker-sandbox.md) · [Credential Vault](docs/security/vault.md) · [Audit Chain](docs/security/audit-chain.md) · [Agent Policy](docs/security/agent-policy.md) · [Guardrails](docs/configuration/guardrails.md) |
| 运维 | [Audit](docs/core/audit.md) · [Cost Tracking](docs/core/cost-tracking.md) · [Reports](docs/core/reports.md) · [Evals](docs/core/evals.md) · [Doctor](docs/operations/doctor.md) · [Observability](docs/core/observability.md) · [CI/CD](docs/operations/cicd.md) |

## 示例

```bash
initrunner examples list               # 浏览所有 Agent、团队和 Flow 项目
initrunner examples copy code-reviewer # 复制到当前目录
```

## 升级

运行 `initrunner doctor --role role.yaml` 检查角色文件的废弃字段、Schema 错误和规范版本问题。添加 `--fix` 自动修复。用 `--flow flow.yaml` 验证整个 Flow 及其引用的角色。查看 [废弃说明](docs/operations/deprecations.md)。

## 社区

- [Discord](https://discord.gg/GRTZmVcW): 聊天、提问、分享角色
- [GitHub Issues](https://github.com/vladkesler/initrunner/issues): Bug 报告和功能请求
- [Changelog](CHANGELOG.md): 发布说明
- [CONTRIBUTING.md](CONTRIBUTING.md): 开发配置和 PR 指南

## 许可证

根据 [MIT](LICENSE-MIT) 或 [Apache-2.0](LICENSE-APACHE) 许可，由你选择。

---

<p align="center"><sub>v2026.4.15</sub></p>
