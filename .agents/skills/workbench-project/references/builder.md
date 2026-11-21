# Builder 增量接入、组队方案与交付闭环

本参考定义 `workbench-project` 在已有或新项目中执行 **环境适配 → 简短组队方案 → 一次确认 → 能力与上下文落地 → 首项真实任务验证 → 新会话交接与经验回流** 的工作方法。不新建独立 CLI、调度器、数据库或新 JSON schema。

## 1. 输入盘点、环境/工具自动感应与事实摘要

用户最少只需提供**目标项目**与**希望完成的工作**。仓库与本机环境能回答的问题先只读探测，不要求用户填写完整问卷：

1. **运行环境与推荐工具感应**：先执行 `node .agents/skills/workbench-project/scripts/check.mjs env /absolute/project`（读取 [recommended-tools.json](recommended-tools.json)），自动识别项目所属类型（`general` 普通项目、`code-engineering` 代码工程类项目、`research` 研究性/逆向对标项目），并检查：
   - **四项注册推荐工具/标配原子能力**：`semble`、`codegraph`、`gh`、`archify` 的安装与项目级初始化状态（`ready / needs_project_init / missing_install`）；
   - **项目依赖的其他运行环境**：自动感应构建与运行特征（JDK/Gradle、Android SDK `local.properties`、Python/uv、Node、Rust/Go、`.env` 等）是否就绪（`ready / needs_setup`）。
   - **静态发现与运行验证边界**：`check.mjs env` 是纯本地静态只读检查（不联网、不读取凭据、不执行登录或安装）。其 `ready` 仅表示二进制可执行位、Skill 入口 `SKILL.md`、本地索引目录或配置键/路径存在；在线登录状态（如 `gh auth status`）、宿主 MCP 会话自动加载、Git hook 真实提交触发及完整构建执行须按输出中的 `unverified` 字段在对应验证层单独确认。缺少推荐工具只触发安装/初始化引导，不阻断与该工具无关的基础接入。
2. 读取项目已有 `AGENTS.md`、`CLAUDE.md`、`README.md`、项目地图、现行设计/状态文档及测试入口。
3. 盘点 `staged`、`unstaged`、`untracked`；无 Git 提交（`head=null`）或 dirty 工作区均合法，保留既有改动，不自动清理或 `stash`。
4. 只读取与当前目标相关的材料，不扫描无关仓库或私人历史。
5. 输出**简短事实摘要**：
   - **已有入口**：身份、规则、导航、验证命令与现有交接文件。
   - **环境与推荐工具状态**：已就绪工具/环境、需在项目内初始化的工具（如 `codegraph` 图谱与 MCP/Git 钩子）、缺失需引导用户安装的工具或环境依赖。
   - **已知约束**：授权边界、版本锁定、构建环境与禁止事项。
   - **真实缺口**：为完成本次目标缺少的入口、原子 Skill、工具初始化或任务上下文。
   - **未知项及影响**：待验证假设或需用户拍板的不可逆/架构分歧。

## 2. 差距判断、推荐工具注册与原子能力选择（Selection）

每项拟议改动必须回答：**“为完成什么工作，当前缺少什么，最小补充是什么”**：

- **已有环境足够 → `noop`**：原规则、工具和入口可直接支撑任务时，直接引用原文件推进任务，不生成空目录或冗余模板。
- **推荐工具与初始化引导（按 [recommended-tools.json](recommended-tools.json) 匹配项目类型）**：
  - **`semble`（普通项目及全部项目）**：检查 `semble` CLI / MCP；未安装则引导用户安装（`uv tool install "semble[mcp]" && semble install`）；已安装则在项目初始化时预热索引，并将**“检索策略：`semble` 优于 `grep / find / glob` 等工具”**写入 `AGENTS.md`。
  - **`codegraph`（代码工程类项目）**：检查 `codegraph` CLI、`.codegraph/`、`.mcp.json` 与 `.git/hooks/post-commit`；未安装则引导用户安装；已安装但在项目中处于 `needs_project_init` 时，列入初始化动作：执行 `codegraph init .` 构建代码图谱（`.codegraph/` 加入 `.gitignore`）、配置项目 `.mcp.json`（`codegraph serve --mcp`）、配置 `.git/hooks/post-commit` 在 `git commit` 时自动执行 `codegraph sync --quiet .` 同步 repo，并将图谱优先策略写入 `AGENTS.md`。
  - **`gh`（研究性项目、代码工程类项目）**：检查 `gh` 与登录状态；未安装或未登录则引导用户完善；将**“不熟悉的功能别从零写，先通过 `gh` 去 GitHub 搜开源项目对比思路再动手，搜索之后先给出取舍（Trade-offs），绝不直接搬实现”**写入 `AGENTS.md`。
  - **`archify`（项目标配，属于原子 Skill）**：检查项目或全局 `archify` Skill；未安装则引导用户安装，若全局已安装则适配到项目 `.agents/skills/archify` 与 `.claude/skills/archify`（或登记引用），并将**“鼓励 Agent 在用户分析、解惑、总结与方案对比时，主动建议或通过 `archify` 进行可视化解说（架构图 / 一页式 Explainer）和辅助决策”**写入 `AGENTS.md`。
  - **项目其他依赖环境感应**：若 `check.mjs env` 报告运行时、SDK 或配置文件缺失（`needs_setup`），在方案中明确列出具体修复命令引导用户完善。
- **能力选择从 `skills-hub` 原子 Skill 与已有领域 Skill 开始**：
  - 核对候选 Skill 的适用任务、来源、固定版本、摘要、准入状态（`candidate / trial / verified`）与宿主依赖。
  - **读取候选 `SKILL.md` 正文**核实前提与边界，不把关键词命中当作适用性证明。
  - **必须装配真正干活的原子 Skill**：除 `workbench-project` 外，按任务类型装配核心工程原子 Skill（例如测试驱动与纯逻辑验证选 `matt-tdd`、故障与构建诊断选 `matt-diagnosing-bugs`、交付前边界与质量审查选 `matt-code-review`、模块与接口设计选 `matt-codebase-design`），并按需适配工作区已有的领域专项原子 Skill（注明 `unmanaged (workspace-adapted)`）。`candidate` 不得安装，`trial` 须具备明确试用授权并传 `--allow-trial`。
- **执行方式选择（禁止无 Fabric 伪造多角色）**：默认采用**单 Agent + 原子 Skill 工作流**直接执行。仅当任务确实需要跨角色并行依赖、独立交付裁决且已实际安装 `fabric-onboarding` 时，才启用 Fabric 多角色编排；**未安装 Fabric 时，严禁在单 Agent 流程中虚构或模拟 Manager/Worker 派工**。

## 3. 简短组队方案与一次确认

在启动真实业务修改、项目级能力安装或模型派工前，在现有任务或项目计划位置给出**简短组队方案**（不新增独立团队配置 schema），至少包含：

1. **首项真实任务**：目标、具体交付物、可观察完成标准与明确排除项。
2. **执行模式与分工**：明确采用“单 Agent + 原子 Skill 直接执行”还是“已安装 Fabric 的多角色编排”，说明各阶段调用哪些原子 Skill 及拟用模型理由。
3. **上下文与能力入口**：读取的入口文件、拟通过 `skills-hub` 安装的原子 Skill（固定版本、准入状态、`installation_id`）及工作区适配的领域 Skill。
4. **执行控制与边界**：唯一推进负责人、可用预算、允许写入范围，以及重大取舍的升级边界。
5. **本阶段必要动作**：需执行的安装、配置、测试实现、构建/验证命令，以及尚缺条件及其影响。

### 自主推进与重新对齐边界

- **确认后自主推进**：用户一次确认方案后，范围内的环境配置、原子 Skill 安装、代码/测试实施、常规验证与普通调整连续执行，不逐步骤重复请示。普通调整包括：补充读取相关代码、修复编译/测试失败、在不改变交付范围的前提下调整步骤顺序。
- **必须重新对齐的重大变化**：改变任务目标或完成标准、超出约定预算、扩大写入或权限范围、改用未批准的模型/外部工具、改变已接受架构或接口契约。
- **原生权限保护**：一次方案确认不等于绕过宿主原生权限检查、沙箱或凭据边界。

## 4. AI 宪法内核、分级工程原则与三层契约编译

接手项目生成的 `AGENTS.md` 不能只写项目背景和目录列表，必须包含以下完整结构（保持高信息密度、可直接指导运行）：

1. **Project Identity（项目身份与当前阶段）**：项目目标、核心模块、技术栈/工具链锁定与当前所处阶段。
2. **AI Constitutional Kernel（AI 宪法内核）**：
   - **清晰度优先于泛化自治（Clarity over Open-Ended Autonomy）**：仓库能回答的事实先只读核实；当目标、接口契约、写入边界或不可逆影响存在实质歧义时先暴露并请求确认，不靠臆测替用户拍板。
   - **长期记忆与当次任务上下文分离（Memory vs Task Context Separation）**：严禁 `Identity → Preference → Rule → Action` 自动越级；长期规则必须具备明确作用域与真实出处，单次任务的临时假设、排障记录与阶段进展写入任务上下文或交接文档，不混入长期契约。
   - **显式证据分级（`FACT / INFERENCE / HYPOTHESIS`）**：分析、设计与交接必须区分已验证仓库/构建事实（`FACT`）、基于事实的合理推论（`INFERENCE`）与待测试验证的猜想（`HYPOTHESIS`）。
   - **可观察证据优先于自报完成（Observable Evidence over Self-Report）**：任何任务完成声明必须附带可复现命令、测试结果、构建产物或基线差分证据。
   - **状态外化与上下文编译（Externalized State & Compiled Context）**：入口文档保持精炼（Context is compiled, not accumulated）；关键约束、能力回执与残余风险外化落盘，保证新会话零聊天历史即可接手。
   - **风险匹配验证与原生边界保护（Risk-Matched Verification & Native Boundaries）**：严禁篡改验收基线、弱化断言或越过允许写入/权限边界。
3. **Engineering Principles（项目分级工程原则：`INVARIANT / DEFAULT / HEURISTIC`）**：
   - 从项目 README、既有规则、构建配置、架构与测试中反推并结构化列出核心原则，每条包含编号（如 `P-001`）、名称、强度（`INVARIANT` 违反即设计/交付错误、`DEFAULT` 默认遵循且偏离须说明理由、`HEURISTIC` 工程判断倾向）、适用范围（`scope`）、明确陈述（`statement`）、原因（`why`）与可执行的验证方式（`verification`）。
4. **Operating Contract、Tooling Policies & Atomic Skill Router（工作契约、推荐工具策略与原子能力路由）**：
   - **推荐工具策略（Tooling Policies）**：明确写入 `semble`（优于 `grep / find`）、`codegraph`（代码工程项目构建代码图谱、`git commit` 自动同步 repo、改动前查调用链与影响面）、`gh`（不熟悉功能先搜 GitHub 开源项目对比思路、先给出取舍再动手、不直接搬实现）、`archify`（项目标配原子 Skill，分析/解惑/总结时主动建议或生成可视化解说辅助决策）四项硬性工作策略。
   - **任务到原子 Skill 路由表**：明确不同任务场景应读取哪些代码/文档入口、**加载哪个已安装的原子 Skill**（如架构/解惑/总结可视化走 `archify`、新增功能/单测走 `matt-tdd`、排障走 `matt-diagnosing-bugs`、接口/模块边界评估走 `matt-codebase-design`、交付自审走 `matt-code-review`、领域专项走对应领域 Skill），以及执行哪些验证命令。
5. **Validation & Handoff Rules（验证与交接门禁）**：
   - 将可验证原则映射为 `.agent/contract.json` 的 `validation` 命令，明确基线快照、差分核对与五层验证报告要求。

## 5. 增量落地与能力收敛（Provisioning）

- **文档最小修补**：优先在项目已有 `AGENTS.md`、`README.md`、项目地图或 `HANDOFF.md` 补充条件入口；确实缺少必需角色载体时才新建薄文件。
- **能力收敛动作**：
  - `install / upgrade`：通过 Hub `plan` → `install` / `update` 固定版本；能力自身的 Runtime 与配置由其自身说明处理，不因更新 Skill 顺带升级 Runtime。
  - `adapt`：适配目标宿主目录（Codex / agy 用 `.agents/skills/<id>`，Claude 用 `.claude/skills/<id>`），不修改 Hub 库存快照。
  - `noop`：期望状态与已安装文件及回执一致时不重复写入。
  - **冲突保护**：已有手工副本或含用户自定义修改的目录不覆盖、不冒充 Hub 受管安装；Hub `restore` 只恢复其管理的文件，不代替能力 Runtime 卸载。

## 6. 四段衔接、五层验证与反馈回流

### 四段最小衔接核对

1. **AWB → 团队执行**：目标、角色职责、项目入口、可用能力、完成标准与自主边界已写入任务材料。
2. **Hub → AWB / Agent**：来源版本、摘要、`installation_id`、适用条件与支持证据可追溯。
3. **执行 → 验收**：当前候选、实际命令与验证结果、未解决问题、接受或返工依据完整记录。
4. **反馈 → 组件**：按归属分诊（项目规则归项目、接入与上下文方法归 AWB Skill 源码、能力适用性证据归 Hub、单次执行控制问题归 Fabric）。

### 五层验证分别报告

检查与交付报告必须分别标注以下五层状态（未执行写 `未验证`，不以前一层代替后一层）：
1. **项目入口可读取**（`check.mjs doctor` 通过，契约角色与验证命令来源可解析）；
2. **能力文件已安装**（固定版本摘要与 Hub 回执或既有副本核对一致）；
3. **依赖/宿主可用**（项目构建/测试工具链或所选执行宿主实测可用）；
4. **真实任务已完成**（约定交付物落地并通过项目自身测试/验证命令）；
5. **新会话接手与用户接受**（新会话仅凭项目入口与任务材料可恢复上下文并复核；用户最终确认接受）。

### 经验回流与减法原则

采用 **观察 → 归因 → 小改动候选 → 验证 → 采用/撤回**：
- 共同记录四组观察结果：① 交付与预期一致性；② 用户介入次数及原因；③ 组队、协调、用量与耗时（未知用量记未知，不填零）；④ 后续任务实际复用的资产。
- 区分目标不清、上下文失真、能力不适用、环境未就绪、执行控制问题与业务缺陷；**允许并鼓励删除无效规则与冗余能力**，使下一次任务更轻、更准。
