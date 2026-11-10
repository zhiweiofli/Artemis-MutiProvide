# Project Contract v1

这是路径索引，不是新规则层。用户当前指令和项目已有 Accepted ADR、接口、配置继续有效。重复接入应复用现有索引，没有缺口就不改文件。

## 最小资产

| 回答的问题 | 优先复用 | 缺失时补什么 |
|---|---|---|
| 项目是什么 | README | 项目身份及目标 |
| 怎么做事（宪法、原则与工具策略） | AGENTS、CLAUDE、ADR | 含 **AI 宪法内核 + `INVARIANT/DEFAULT/HEURISTIC` 工程原则 + 推荐工具策略（`semble / codegraph / gh / archify`）+ 原子 Skill 路由** 的 `AGENTS.md` |
| 做某种任务读哪里、用什么工具与 Skill | PROJECT_MAP、README 导航、AGENTS 路由表 | 按任务场景列代码路径、文档、推荐工具与原子 Skill 的导航表 |
| 怎样算完成 | 项目测试/CI、验收文档 | 可观察标准和真实命令来源 |
| 有哪些可用原子能力与环境工具 | 项目 `.agents/skills/`、`.claude/skills/`、`skills-hub`、[recommended-tools.json](recommended-tools.json) | 能力期望表（Skill Desired State）与环境工具状态表 |

`AGENTS.md` 必须包含 **Project Identity、AI Constitutional Kernel、Engineering Principles（`INVARIANT / DEFAULT / HEURISTIC`）、Operating Contract（含 Recommended Tooling Policies 与 Atomic Skill Router）、Validation & Handoff Rules** 五个核心部分，不写只有背景介绍而无行为准则、工具策略与原则强度的空壳文档。项目已有原则是单一事实源；额外原则文件、设计目录、evals 目录与执行配置按实际需要建立。

## 路径契约

`.agent/contract.json` 示例（由 Agent 按真实项目填写，路径相对项目根目录）：

```json
{
  "schema_version": 1,
  "project": "example",
  "documents": [
    {"role": "identity", "path": "README.md"},
    {"role": "rules", "path": "AGENTS.md"},
    {"role": "navigation", "path": "PROJECT-MAP.md"},
    {"role": "acceptance", "path": "README.md"},
    {"role": "handoff", "path": ".agents/skills/workbench-project/references/handoff.md"}
  ],
  "validation": [
    {"command": "node .agents/skills/workbench-project/scripts/check.mjs doctor .", "source": "README.md"}
  ]
}
```

`identity`、`rules`、`navigation`、`acceptance`、`handoff` 为必需角色；同一个文件可以承担多个角色（例如已有 `HANDOFF.md` 的项目可直接复用其承担多个角色，再按需补薄 `AGENTS.md` / `README.md`）。可补 `design`、`capabilities`。`validation` 记录至少一个当前可执行的检查及其说明来源（可将项目工程原则映射为项目自身构建/测试/差分脚本命令，但工具指标不单独代替业务正确性）。Doctor 不执行命令，也不证明来源正文与命令匹配；接入者与审查者负责核对。

所有引用必须是项目内文件。明确拒绝绝对路径、父目录跳转与符号链接引用，避免 doctor 不经意读取其他项目。外部 Hub 或 Fabric 可由项目正文链接，不能伪装成已经安装的本地依赖。

## 能力期望表（Skill Desired State）与可选能力衔接

V1 在项目导航/项目地图的**单一章节**维护项目能力期望（不另建锁文件、运行数据库或第二份注册表；也不在每次接入报告中重复维护最新状态）：

| 字段 | 最小记录要求 |
|---|---|
| 用途与触发条件 | 解决什么问题；何时应读取 / 可使用 / 需先确认 / 不可使用（区分 `explicit / suggested / automatic / embedded` 语义，不宣称宿主已强制执行） |
| Skill 身份与版本 | `skill_id`、固定版本、SHA-256 摘要、来源与准入状态（`trial / verified`；`candidate` 不安装） |
| 宿主与安装位置 | 实际安装目录（如 `.agents/skills/<id>` 或 `.claude/skills/<id>`）、宿主/工具链依赖前提 |
| 回执与已验证层级 | Hub `installation_id`（手工副本注明 `unmanaged`）及已验证层级（文件已装 / 宿主可读 / 真实任务已调用） |

信息由 Hub 或安装器提供时优先引用；缺失项写 `unknown` 或 `N/A`，不编造版本号或 `installation_id`。

本轮接入计划与报告复用项目已有位置，四段衔接最小事实如下：

| 衔接阶段 | 最小事实 |
|---|---|
| 接入与组队输入 | 目标项目、首项真实任务目标（或仅 `init/adopt`）、选定角色/能力与允许写入范围 |
| Hub 供给核对 | 选定 Skill ID、固定版本、摘要、正文适用性核对、`plan` 与 `installation_id` |
| 能力与上下文落地 | 所选能力自身安装/初始化结果、已有配置复用情况、任务上下文文件（详见 [task-context.md](task-context.md)） |
| 验证与交接结果 | 五层检查结果（入口可读 / 能力已装 / 依赖可用 / 真实任务完成 / 新会话与用户接受）、未满足前提与反馈归属（详见 [builder.md](builder.md)） |

Workbench 协调这些步骤，能力自身拥有安装器、配置和运行证据。Hub 安装回执只约束它安装的文件；能力安装器另行产生的 Runtime、配置和角色 Skill 不冒充 Hub 所有，也不由 Hub 自动恢复或卸载。已有 Runtime 不自动升级，不在能力未就绪时写“已可执行”。

Fabric 是可选示例：查询其接入 Skill 后读取自己的安装说明，复用已有项目契约，不要求 Fabric 源码仓在特定路径。Fabric 的离线检查、在线宿主检查和任务实际执行分别报告。

## 增量接入回执

放在项目报告目录：接入前入口、补充原因、写入范围、源 Skill 的文件摘要、检查结果与限制。Skill 经 skills-hub 固定版本安装，回执仍由 Hub 保存；项目接入报告引用版本、摘要和 installation_id，不复制成另一套安装状态。Codex / agy 使用 `.agents/skills/workbench-project`；Claude 使用 `.claude/skills/workbench-project`，路径契约应按实际安装位置填写。已有手工试点副本保留其原接入回执，不冒充 Hub 安装。安装或接入不改变 Hub 生命周期。
