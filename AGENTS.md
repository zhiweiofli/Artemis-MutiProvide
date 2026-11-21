# AGENTS.md — Artemis Agent Operating Contract & Engineering Constitution

> **项目身份与目标**：ARTEMIS (Autonomous AI Assistant for Mobile Automation) 是面向 Android 跨应用移动自动化的自主智能体系统，支持通过自然语言操控手机、执行端到端测试并输出诊断报告。
> **当前工程阶段**：模型供应商架构解耦与多模型接入（阶段一：全面接入 DeepSeek 等候选供应商，解除 Google/Gemini 强绑定，同时 100% 保持移动端感知与闭环执行核心能力）。

---

## 1. AI 宪法内核 (AI Constitutional Kernel)

任何参与 ARTEMIS 开发、重构、调试或交付的 Agent，必须无条件遵循以下六项宪法原则：

1. **清晰度优先于泛化自治 (Clarity over Open-Ended Autonomy)**
   - 仓库事实（文件、配置、代码分支、调用链）先做只读核实，不靠臆测做架构决策。
   - 当涉及不可逆变更（如破坏现有接口契约、改变默认模型路由规则、越过授权写入边界）时，必须显式提出并取得用户确认。
2. **长期规则与当次任务上下文分离 (Memory vs Task Context Separation)**
   - 严禁 `Identity → Preference → Rule → Action` 越级自动固化。
   - 长期规范写入 `AGENTS.md` / `PROJECT-MAP.md`；单次调试假说、日志排障记录与时点验证写入 `HANDOFF.md` 或任务上下文，不得污染长期架构契约。
3. **显式证据分级 (`FACT / INFERENCE / HYPOTHESIS`)**
   - **FACT（事实）**：工作区已核实的代码片段、配置文件、SHA-256 摘要、运行输出或测试结果（附带文件路径与行号）。
   - **INFERENCE（推论）**：基于事实建立的逻辑推导，说明推导逻辑与影响。
   - **HYPOTHESIS（假设）**：待验证猜想，必须明确验证手段以及假设不成立时的回退路线。
4. **可观察证据优先于自报完成 (Observable Evidence over Self-Report)**
   - 严禁空口宣称“重构成功”或“接入完成”。必须提供可复现的执行命令、回归测试日志、输出差分或基线验证证据。
5. **状态外化与上下文编译 (Externalized State & Compiled Context)**
   - 关键工程决策落盘固化，上下文是“编译”而成而非无限堆叠聊天历史。
   - 新会话依靠 `AGENTS.md`、`PROJECT-MAP.md` 与 `HANDOFF.md` 即可零历史恢复完整上下文。
6. **风险匹配验证与原生边界保护 (Risk-Matched Verification & Native Boundaries)**
   - 严禁篡改测试断言、跳过关键验收项或伪造测试通过结果。严禁绕过操作系统与沙箱的原生权限边界。

---

## 2. 分级工程原则 (Engineering Principles)

| 编号 | 名称 | 级别 | 适用范围 | 核心陈述与说明 | 验证方式 |
|---|---|---|---|---|---|
| **P-001** | **核心能力保全原则** | `INVARIANT` | 全局架构与Agent | 解耦 Google 供应商过程中，**不得丢失或降级当前项目的核心能力**：Android 双引擎闭环（Flash 响应式循环 + Pro LangGraph 决策图谱）、UI 层次感知（Accessibility Helper / UIAutomator2）、坐标回退定位与错误诊断自愈。 | 回归测试套件 `tests/unit` + 模拟器/真实设备任务闭环验证 |
| **P-002** | **模型提供商中立抽象** | `INVARIANT` | `artemis/llm` / `artemis/config` | 所有智能体节点与工具禁止硬编码特定厂商专有 SDK 调用；全部通过 `artemis.llm.router.ModelFactory`、`ModelEndpoint` 与 `artemis.services.llm.get_llm` 进行统一抽象，提供商配置由 `config/artemis.jsonc` 统一驱动。 | 静态代码扫描禁绝除适配层外的厂商 SDK 直接引用 |
| **P-003** | **端点模态匹配保护原则** | `INVARIANT` | 模型调度与Payload | **当前架构（如 Gemini 主模型）原生接收截图 (`image_url`) 进行闭环感知。** 仅当某个节点显式路由到纯文本模型时，才必须走 Payload 过滤或 UI 树文本化模式，严禁向不支持视觉的端点硬传 `image_url` 引发 API 400 报错。对于原生支持多模态推理的模型（如 `deepseek flash v4 1017` / Gemini），保持直接端到端输入截图。 | 单元测试验证模型请求 Payload 格式与端点能力的匹配校验 |
| **P-004** | **高可靠 Fallback 链路** | `DEFAULT` | 运行时与配置 | 每个 Agent 节点与 Utility 节点必须在配置中声明明确的 `fallback` 备用模型；当主模型遭遇 RateLimit、5xx 或超时时，由 `FallbackRunner` 自动接管，保障自动化测试不因单点网络抖动而中断。 | `tests/unit/test_llm_reliability.py` 覆盖切换验证 |
| **P-005** | **推荐工程工具优先** | `DEFAULT` | 开发与调试流程 | 遵循 Agent Workbench 工具规范：检索优先用 `semble`；AST/调用图分析优先用 `codegraph` 并挂载 Git hook 自动同步；开源对标优先用 `gh`（先比对取舍再设计）；阶段成果与复杂状态机主动建议使用 `archify` 进行可视化呈现。 | 检查 `.agent/contract.json` 及工具状态 |
| **P-006** | **测试驱动与原子能力装配** | `DEFAULT` | 功能与修复交付 | 新增功能与 Bug 修复必须遵循 TDD 流程（编写失败测试 -> 最小实现 -> 重构），交付前通过原子 Skill 审查代码边界与模块设计。 | Git 提交记录与 pytest 绿色报告 |
| **P-007** | **深度推理高性价比倾向** | `HEURISTIC` | 文本认知类节点 | 在规划（Planner）、日志诊断（Log Analyzer / Diagnoser）、总结报告（Summarizer / Outputter）等重文本与强逻辑场景，优先接入高性价比推理模型（如 DeepSeek 系列），实现极高推理质量与百倍成本节约。 | 对比评估规划质量与 Token 消耗账单 |
| **P-008** | **多模态平替与异构扩展** | `HEURISTIC` | 视觉感知类节点 | 核心候选模型为支持多模态推理的 **`deepseek flash v4 1017`**，可对等平替 Gemini 接收屏幕截图；若遇无视觉微调的纯文本候选版本，才启用“DeepSeek 规划 + 开源视觉端点/文本化 UI 树”分工模式。 | 端到端测试执行成功率验证 |

---

## 3. 工作契约与推荐工具策略 (Tooling Policies)

### 3.1 四大标配工具策略

1. **`semble`（语义与混合代码检索）**：
   - **策略**：`semble` 优于暴力 `grep / find / glob` 扫描。查找业务逻辑、探索代码实现模式、查阅配置定义时，优先使用 `semble` 检索。
   - **未安装引导**：`uv tool install "semble[mcp]" && semble install`。
2. **`codegraph`（代码图谱与调用链分析）**：
   - **策略**：项目初始化建立代码图谱，`git commit` 时通过 `.git/hooks/post-commit` 自动执行 `codegraph sync --quiet .` 同步。修改核心模型路由或重构 LangGraph 节点前，先通过 `codegraph` 分析 `callers / callees` 与影响面（`impact / affected`）。
   - **未安装引导**：通过 Homebrew 或全局 npm 安装 `@colbymchenry/codegraph` 并运行 `codegraph init .`。
3. **`gh`（GitHub 开源对标与方案检索）**：
   - **策略**：不闭门造车。涉及多模型流式解析、OpenAI 兼容协议扩展、视觉微调接口时，先用 `gh search code / repos` 查阅成熟开源库（如 LiteLLM, LangChain 社区适配器, OpenRouter SDK）的设计取舍，向用户输出对比结论（Trade-offs）后再行实现。
4. **`archify`（可视化架构与一页式解说）**：
   - **策略**：在为用户梳理双循环架构（Flash vs Pro）、解说 Google 解耦方案、呈现异构模型协同状态机时，主动使用 `archify` 输出交互式架构图或 One-page Explainer 辅助决策。

### 3.2 原子能力路由表 (Atomic Skill Router)

| 任务场景 | 核心关注路径 | 推荐加载原子 Skill | 验证命令 |
|---|---|---|---|
| **新增模型供应商/端点** | `artemis/llm/router.py`, `artemis/config/settings.py` | `matt-tdd` + `matt-codebase-design` | `uv run pytest tests/unit/test_llm_gateway.py` |
| **排查模型调用/重试失败** | `artemis/services/llm.py`, `artemis/llm/reliability.py` | `matt-diagnosing-bugs` | `uv run pytest tests/unit/test_llm_reliability.py` |
| **Agent 提示词与决策流改造** | `artemis/agents/`, `artemis/graph/` | `matt-codebase-design` | `uv run pytest tests/unit/test_llm_structured.py` |
| **架构演进与解耦可视化** | `config/artemis.jsonc`, `docs/` | `archify` (或工作区适配版) | 检查生成的 HTML 交互图 |
| **阶段性交付审查与自检** | 全部修改范围 | `matt-code-review` | `node .agents/skills/workbench-project/scripts/check.mjs doctor .` |
| **Fabric 3.0 接入与升级** | `fabric.json`, `fabric.agents.json`, `.fabric/` | `fabric-onboarding` | `./.fabric/runtime/node_modules/.bin/fabric doctor .` |
| **Fabric 3.0 多角色主控/Manager** | `tasks/plan.json`, `.fabric/runs/` | `fabric-main` + `fabric-manager` | `./.fabric/runtime/node_modules/.bin/fabric prepare ... --plan tasks/plan.json` |
| **Fabric 3.0 Worker / Reviewer** | `.fabric/runs/run-*/<task>/CURRENT.json` | `fabric-worker` / `fabric-reviewer` | 产出 `DELIVERY.md` 或 `REVIEW.md` + `REVIEW.json` |

### 3.3 Fabric 按任务升级 Worker 与审查收敛策略

- 每个业务 Task 默认由 AGY / Gemini Flash 先执行。按同一业务 Task 累计独立业务审查次数；CLI/权限/消息传输恢复及仅补交生命周期回执不计为新的业务审查，换模型不重置计数。
- 同一 Task 第 3 次业务审查后仍为 REWORK（超过两次）时，为 `fabric.agents.json` 增加 AGY Argon 备用 profile（如 `agy-argon`）：`orcaAgent=antigravity`、`model=gemini-4-argon-high`、`modelIdentity=gemini-4-argon`、`effort=high`，仅该 Task 的后续实现改用 Argon；后续新 Task 仍由 Flash 先执行，Argon 兜底。
- 同一 Task 第 5 次业务审查后仍未通过（超过四次）时，controller 与 Reviewer 逐项评估意见是否影响可用性或核心能力。非核心且不影响可用性的意见记录风险、证据与后续项后作为非阻断项处理；保留核心功能、正确性及当前必需验收的阻断项。由 Reviewer 真实更新审查结论，controller 再裁决，禁止伪造 PASS、跳过必需测试或静默降低验收。
- 本用户授权策略优先于旧流程的两次返工默认；落地须保留全部 Task/Dispatch、候选、审查和模型切换回执，不通过新建 Task/Run 清零历史。模型配置/冻结材料发生变化时按实际支持能力更新并记录；未具备执行支持不得声称已自动兜底。启动与时间预算独立有效，不因模型切换或审查收敛而自动扩大。

---

## 4. 验证与交接门禁 (Validation & Handoff Rules)

1. **基线保护**：修改前必须核实 `.agent/baseline.json` 覆盖范围。未在基线范围内的非预期变更不得随本任务提交。
2. **五层验证报告**：每次阶段交付必须按五层分别报告：
   - **L1 项目入口可读取**：`node .agents/skills/workbench-project/scripts/check.mjs doctor .` 输出 `healthy`。
   - **L2 能力文件已安装**：`.agents/skills/` 下对应原子 Skill 存在且完整。
   - **L3 依赖/宿主可用**：Python 3.12+ / uv 环境就绪，`pyproject.toml` 依赖满足。
   - **L4 真实任务已完成**：针对目标实现的功能测试或重构单元测试全部通过。
   - **L5 新会话接手与用户接受**：新会话通过 `HANDOFF.md` 与 `PROJECT-MAP.md` 可无障碍复核。
3. **交接文档维护**：任务终态事实、决策结论、开放问题必须写入 `HANDOFF.md`。
4. **阶段看板与可视化同步门禁 (Phase Board Sync Gate)**：
   - 每次完成一个 Phase（`P0-SPEC` → `P1-RED` → `P2-GREEN` → `P3-REVIEW` → `P4-BENCH`）或发起 `Test Dispute` 时，**必须同步更新 [`docs/TASK_BOARD.md`](file:///Users/zw-mini/orca/artemis/docs/TASK_BOARD.md) 与 Archify 可视化看板（[`.archify/explainer-phase-task-board-20261109-141300/phase-task-board.html`](file:///Users/zw-mini/orca/artemis/.archify/explainer-phase-task-board-20261109-141300/phase-task-board.html)）**。
   - 阶段 `P2-GREEN` 落地的 `scripts/gate.py` 必须内置自动看板同步逻辑：每次执行 `gate.py` 后，根据实测结果自动刷新 `docs/TASK_BOARD.md` 与 `candidate.archify.md`，并调用 `node .agents/skills/archify/bin/archify.mjs finalize explainer` 重新编译 HTML 页面。未同步刷新看板的阶段交接一律视为未完成。
