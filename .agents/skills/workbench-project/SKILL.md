---
name: workbench-project
description: 为新项目初始化、为已有项目增量接入 Agent Workbench，或作为项目环境 Builder 盘点缺口、提出简短组队方案、配置能力与任务上下文并衔接首项真实任务交付与可核验交接。
---

# Workbench 项目接入与环境 Builder

让团队或下一位 Agent 只依靠项目入口、能力配置和交接证据，就能理解规则、找到任务上下文、完成约定交付并复核结果。

## 1. 模式分流：基础接入 vs Builder 组队交付

先读取 [接入约定](references/contract.md)。确认目标项目与允许写入范围，读取已有 `AGENTS.md`、`CLAUDE.md`/`GEMINI.md`、`README.md`、项目地图、现行设计/状态及测试入口。盘点 `staged`、`unstaged`、`untracked`；无提交（`head=null`）也可用文件摘要固定基线。只检查目标项目，不扫描无关仓库或私人历史。

- **基础 `init / adopt`（仅接入兼容路径）**：用户仅要求建立或修补项目契约、运行检查或准备交接时，按最小缺口补齐入口与 `.agent/contract.json`，**不因接入而启动业务任务，缺少推荐工具亦不阻断与该工具无关的基础接入**。
  - `init`：按项目目标建立最小身份、规则、任务导航与验收入口；无代码时只验证文档与引用，原有文件优先复用。
  - `adopt`：列出现有入口与实质缺口，直接补最小缺口；保留既有 `PROJECT_MAP.md` / `HANDOFF.md` 等权威文件，语义冲突显式报告，不靠复制或覆盖规则解决。
- **Builder 组队与首项真实交付**：用户要求“接手项目、配好团队/能力、完成某项真实需求/验证”时，按 [Builder 方法](references/builder.md)、[推荐工具与环境注册表](references/recommended-tools.json) 与 [任务上下文准备](references/task-context.md) 推进：
  1. **环境/工具感应、事实摘要与差距判断**：先执行 `node scripts/check.mjs env /absolute/project` 加载 [recommended-tools.json](references/recommended-tools.json)，自动识别项目类型（`general / code-engineering / research`）、检测推荐工具（`semble`、`codegraph`、`gh`、`archify`）与项目依赖环境（JDK/Gradle、Android SDK、Python/uv、Node、Rust/Go、`.env` 等），结合已有文档与代码反推项目工程原则。`check.mjs env` 的 `ready` 仅保证本地静态发现（可执行文件/Skill 目录/配置项与目录存在），不代表在线认证、宿主 MCP 自动发现或真实构建已运行通过；严禁静默执行登录、安装、联网或读取凭据。
  2. **简短组队/环境方案与一次确认**：给出首项真实任务目标/交付物/完成标准/排除项、**环境与推荐工具就绪及初始化清单**（未安装工具引导用户安装；已安装待项目初始化的工具如 `codegraph` 列入自动初始化动作）、拟装原子 Skill 清单、执行模式（未安装 Fabric 时采用**单 Agent + 原子 Skill** 直接执行，严禁无 Fabric 伪造或模拟 Manager/Worker 多角色派工）、上下文入口与写入边界。**经用户一次确认后，在授权边界内自主连续推进**。
  3. **工具初始化、宪法/原则/工具策略编译、原子 Skill 装配与真实任务交付**：完成推荐工具项目级初始化（如代码工程项目执行 `codegraph init .`、配置 `.mcp.json` 与 `.git/hooks/post-commit` 自动同步 repo 图谱；预热 `semble` 索引；验证 `gh`；登记标配 `archify` Skill），在 `AGENTS.md` 中编译 **AI 宪法内核 + 分级工程原则（`INVARIANT / DEFAULT / HEURISTIC`）+ 推荐工具策略 + 原子 Skill 路由表**，通过 `skills-hub` 安装适用原子 Skill 并适配领域 Skill，按 [任务上下文准备](references/task-context.md) 落实并验证首项真实任务。

## 2. 推荐工具、项目环境感应与原子能力装配

AWB 通过 [recommended-tools.json](references/recommended-tools.json) 注册推荐工具策略与环境探测器，`skills-hub` 供给固定版本原子工程 Skill。**初始化/接手阶段必须同时完成“环境与推荐工具收敛”和“原子 Skill 装配”**：

1. **推荐工具注册表与工程策略（写入 `AGENTS.md`）**：
   - **`semble`（普通及全部项目标配）**：**策略：`semble` 优于 `grep / find / glob` 等暴力扫描工具**。检索代码、文档（`--content docs`）、配置（`--content config`）或相似实现（`find-related`）时优先调用 `mcp__semble__search` 或 `semble` CLI；若环境未安装，引导用户执行 `uv tool install "semble[mcp]" && semble install`。
   - **`codegraph`（代码工程类项目标配）**：**策略：构建项目代码图谱，`git commit` 时自动同步项目 repo**。分析调用链、符号上下文、上下游依赖（`callers / callees`）与改动影响面（`impact / affected`）时优先使用 `codegraph`；若环境未安装引导用户安装，若已安装则在项目初始化时执行 `codegraph init .`（`.codegraph/` 入 `.gitignore`）、配置项目 `.mcp.json`（`codegraph serve --mcp`），并在 `.git/hooks/post-commit` 配置 `codegraph sync --quiet .` 自动同步。
   - **`gh`（研究性项目、代码工程类项目标配）**：**策略：不熟悉的功能别从零写，先通过 `gh` 去 GitHub 搜开源项目对比思路再动手；搜索之后先给出方案取舍（Trade-offs），绝不直接照搬实现**。若环境未安装或未登录，引导用户安装 `gh` 并执行 `gh auth login`。
   - **`archify`（全项目标配，属于原子 Skill）**：**策略：鼓励 Agent 在为用户分析、解惑、梳理架构/状态机或总结阶段成果时，主动建议或使用 `archify` 进行可视化解说（交互式架构图 / 一页式 Explainer）和辅助决策**。若环境未安装引导用户安装；若全局已安装，可适配到项目 `.agents/skills/archify` 与 `.claude/skills/archify` 或在能力表中登记引用。
2. **感应项目依赖的其他环境**：通过 `check.mjs env` 及项目构建清单自动感应运行时与 SDK（如 JDK 版本、Gradle Wrapper、Android SDK `local.properties`、Python/uv、Node、`.env` 模板等），如实报告就绪状态并在缺失时给出具体完善引导。
3. **Hub 原子工程能力与领域原子能力装配**：通过 `skills-hub` 查询并安装适用原子工程 Skill（如 `matt-tdd`、`matt-diagnosing-bugs`、`matt-code-review`、`matt-codebase-design`），同时适配项目/父工作区领域原子 Skill（注明 `unmanaged (workspace-adapted)`）。未安装 Fabric 时，由单 Agent 依次加载并遵循已安装的原子 Skill，绝不凭空模拟 Manager/Worker 角色。

## 3. 检查、交接与经验回流

本 Skill 目录内的检查命令：

```sh
node scripts/check.mjs env /absolute/project
node scripts/check.mjs doctor /absolute/project
node scripts/check.mjs snapshot /absolute/project /absolute/baseline.json AGENTS.md README.md src
node scripts/check.mjs verify /absolute/project /absolute/handoff.json
```

改动前必须先用 `snapshot` 保存明确覆盖路径的基线（放在目标项目忽略目录或临时目录）。`doctor` 只读检查 `.agent/contract.json` 的角色路径与验证命令来源，不执行项目测试。业务交付必须运行项目自身的构建/测试命令验证。

交接前读取 [交接约定](references/handoff.md) 与 [Builder 方法](references/builder.md#6-四段衔接五层验证与反馈回流)：
- 分别报告五层结果：**项目入口可读取、能力文件已安装、依赖/宿主可用、真实任务已完成、新会话接手与用户接受**；未执行项写“未验证”，不以前一层替代后一层。
- 新会话仅凭项目入口与指定任务/交接材料即可恢复上下文并复核交付。
- 记录交付一致性、用户介入次数及原因、准备与协调耗时/已知用量、可复用资产，将规则、方法、能力证据与执行问题按归属回流对应组件，并清理无效规则或冗余能力。
