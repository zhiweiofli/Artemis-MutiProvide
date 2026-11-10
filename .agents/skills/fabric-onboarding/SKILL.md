---
name: fabric-onboarding
description: 为一个项目接入或升级 Harness Fabric 3.0 时，核对环境、依赖、项目规则与任务上下文，完成最小配置并给出可验证的启动路径。普通 Fabric 任务执行不使用。
---

# Fabric 项目接入

在目标项目中完成接入，让当前 Orca 工作区中的 Codex 能按 `fabric-main` Skill 执行任务。便携包执行 `.fabric/setup.sh` 后，CLI 位于 `.fabric/runtime/node_modules/.bin/fabric`；项目是新接入还是已有 2.0 配置，以真实文件为准。操作细节和命令见安装包内 `docs/3.0_RUNBOOK.md` 与 `docs/ONBOARDING.md`。

## 通过固定分发包接入

本 Skill 可独立调用，也可由 Workbench 或其他接入流程选用；无需安装 Workbench。由调用方提供目标项目、选定版本、已有项目契约和允许写入范围，复用这些证据，缺失或过期的部分再核查。

Hub 发行快照会在本 Skill 旁附带 `assets/harness-fabric-portable.tgz`。先通过 Hub plan/install 将选定 trial 版本安装到 Codex 项目 `.agents/skills/fabric-onboarding/`，记录 installation_id 并核对版本/摘要。只在用户已选择 Fabric 接入且项目尚无 Fabric Runtime/配置时，使用实际安装位置的附带包；不猜测源码仓位置，不自动安装其他 Agent 或 Workbench。

在目标项目根目录执行（Skill 位于 Codex 的实际项目目录时）：

```sh
tar -xzf .agents/skills/fabric-onboarding/assets/harness-fabric-portable.tgz -C .
sh .fabric/setup.sh
```

先检查 `.fabric/` 的已有文件；有 Runtime、setup 或 Fabric 配置时，走下方既有接入核查/升级路径，不覆盖解压、不重复 init。setup 保留内容相同的 onboarding Skill，Hub 安装的附带包也会保留。CLI 安装后，继续使用下方本 Skill 的原生 init/doctor 步骤。

源码直用或原生便携安装只有本 Skill、没有附带资产时，沿用开头所述安装包手册。Hub 回执只拥有安装的 Skill 和附带包；setup/init 产生的 Runtime、配置和其他角色 Skill 归 Fabric 项目接入，Hub restore 不是 Fabric 卸载。项目仍依赖该 Skill 时，不先移除它；升级需分别核对 Skill 与 Runtime，不自动升级既有 Runtime。接入不启动模型任务。

## 原生初始化与检查

1. 读取目标项目的 `AGENTS.md`、README、相关设计/状态文件、依赖清单与锁文件，并盘点 Git 的 staged、unstaged、untracked。确认项目技术栈、实际依赖状态、现有测试/构建命令、允许修改范围及当前任务来源；资料缺失时标明未知，不猜测命令或验收标准。
2. 初始化前或升级时，按已核实的技术栈、依赖、已有 Skills 与当前任务/工程需求，通过现有 `skills-hub` Skill 的 `find` 和 `source_policy` 只读查询与资格筛选。检查适用范围、依赖、目标 Agent 原生发现目录及固定版本/SHA-256；优先考虑适用的 `verified`。Hub 本地未命中时，沿 `skills-hub` 现行来源优先级进行只读检索；不自动克隆仓库、更新上游、入库或安装。`trial` 仅在用户明确选择时考虑；`candidate` 不安装。可对拟选项目运行 Hub `plan` 检查写入位置与冲突，但此阶段不运行 Hub `install`。保留现有自定义 Skill；不要批量添加。
3. 核对 Node.js 22+、平台、Orca CLI、所选 Agent CLI 与配置中的 Orca Agent ID。新项目运行已安装的 `fabric init PROJECT` 建立 role/config，默认使用 agy/antigravity；按用户明确偏好可传 `--worker PROFILE`，或 `--profiles PROFILES.json` 提供完整 profiles（不合并，必须含所选角色和有效绑定；不默认补 model/effort）。它会保留 setup 释放的同版本 onboarding Skill。已有 2.0/3.0 项目复用并核对现有配置，不重跑 `init`；按手册只补缺少的 `fabric-main` 和本 Skill，保留原配置与角色 Skill。便携安装放在 `.fabric/`，不要为安装 Fabric 修改目标项目的语言依赖或 package.json/lockfile。
4. 确有必要的 Skill 安装时，将选择写入当前根任务正文：说明理由、固定 Skill ID/version/SHA-256、目标 Agent 及原生发现路径、依赖与允许写入范围。用 `fabric prepare --plan` 冻结它与业务工作，核对 PLAN 并取得同一次真实 `plan_approved`；此前只允许 Hub 的只读查询/plan，不安装 Skill。批准后经原有 Hub `install` 安装该计划列明项，记录安装回执中的版本、摘要、位置和 installation_id；冲突时保留既有目录并报告。已有项目走相同步骤，但复用配置且不重跑 `init`。如果没有必要安装项，直接按正常接入/任务流程继续，不为 Skill 查询额外制造 `prepare --plan` 或确认。
5. 没有合格或确有必要的 Skill 时，报告“现有能力足够”或具体缺项与检索限制；不强迫安装，不把未完成的外部检索说成无结果。不要为此新建 Hub 客户端、复制另一份目录或改项目的 Skill 发现规则。Agent 按需查询和选择不等于自动选择器，也不代表本地已有业务 Skill。
6. 运行 `fabric doctor PROJECT --offline`。Orca 工作区就绪后再运行在线 `doctor`，核对其对应同一项目。检查 `.fabric/` 的实际 Git 忽略/跟踪状态。doctor 只验证已列出的前提；Agent 登录、额度、目录信任和原生权限须在对应宿主确认，不读取或复制凭据，也不代为批准。原生权限或目录信任提示由用户处理，不自动选择或批准。
7. 将核实过的项目上下文写回最合适的**现有**入口：必要时在 `AGENTS.md` 增加条件触发的 `fabric-onboarding` / `fabric-main` 路由，在 README 或项目任务文件中修正过期的启动、测试与验收说明。对接入或任务验收确实必需的依赖缺项，沿用项目已有的依赖管理方式做最小修复并同步锁文件；不批量升级。保留现有规则与用户改动；不复制整份项目文档，不凭推测重写架构或状态。没有具体任务时保留 `tasks/example.md` 模板，不编造业务目标。
8. 报告已核实的环境和依赖、Skills Hub 查询与实际安装收据（或无适用选择的理由）、改动的文件、offline/online doctor 结果、项目测试命令来源，以及仍需人工完成的登录/权限或 Orca live 验证。接入完成不等于业务任务通过；实际任务由 `fabric-main` 和 `fabric prepare` 进入。

未经用户当前授权不提交、推送、部署、安装全局工具或改变权限。遇到需要更换 Agent、扩大项目范围或改动现有契约的分歧，先给出具体影响与选择。
