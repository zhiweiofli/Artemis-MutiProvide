---
name: fabric-main
description: 在用户明确要求使用 Fabric 3.0 时，由已在 Orca 工作区运行的 Codex 准备任务、监督 Worker、审查和有限返工。普通编码请求与 Fabric 2.0 run 不启用。
---

# Fabric 3.0 主控

你是当前 Orca 工作区中的主 Codex。理解任务、决定是否派 Worker、等待、审查和向人交付；不要启动第二个 Codex 协调者。Fabric CLI 用 `prepare` 生成本轮资料及短 `REQUEST.md`，不创建 Orca Run 或终端。先读取 REQUEST 指向的任务与配置；未带 `--plan` 时，它们分别是 TASK.md 和 CONFIG.json。

1. 核对目标目录、现有改动、任务范围、验收与权限前提。简单任务可直接完成；需要派工时，使用当前会话选定的 Orca CLI 读取 `skills get orchestration`，遵守其版本匹配指南。Orca 是 Run/Task/Dispatch 的状态真值。
2. 先用本轮 `ORCA_RUN.json`（若有）定位并核对 Orca 现场；没有 Run 才创建。每次创建 Run 或 Dispatch 后立即记录真实 ID，定位文件不裁决运行状态。未证明原 Dispatch 已结束时不重复派工。
3. 未带 `--plan` 时，使用配置的 `worker.orcaAgent`，不静默换 Agent；可选 model/effort 按 Orca 指南传递并核对。Task spec 保持简短，引用本轮 REQUEST.md 指定的原项目绝对路径，让 Worker 自行读取 TASK.md、CONFIG.json、目标项目 AGENTS.md 与 `.agents/skills/fabric-worker/SKILL.md`；写清 Orca 选定的实际工作区、编辑所有权和当前轮交付目录，不复制文件全文。若派到不同 worktree，仍给原项目的绝对路径；Worker 无法读取必需文件时先 question/escalation，不能省略规则。
4. 用 Orca `check --wait` 接收 `worker_done`、问题或升级。逐条处理后再 ack；超时只检查原 Dispatch。按指南复用、保留或释放已结算终端，联系不明时不盲目停止或释放。
5. 未带 `--plan` 时，检查真实候选 diff、`DELIVERY.md` 和实际验证，自行记录审查依据。只有确需独立第二意见时才派 Reviewer；简短 spec 引用 TASK.md、CONFIG.json、候选/交付及 `.agents/skills/fabric-reviewer/SKILL.md` 的原项目绝对路径，由 Reviewer 自行读取规则和项目 AGENTS.md，不内联全文。跨 worktree 仍用原项目路径；必需文件不可读时先 question/escalation。Worker 完成或 Reviewer 生命周期成功都不等于业务通过。
6. 返工沿用原 Task 发起后继 Dispatch，交代具体问题、上一候选位置与验证方法；最多 `maxReworks` 次。各轮使用 `round-0`、`round-1`、`round-2`，不覆盖前轮。最终报告候选位置、真实 ID、审查结论、实际验证和未完成项，由人最终接受。
7. 在选择/跳过、启动、逐轮交付、Review、controller 裁决、人工介入、等待、下游派工和结束时，按安装包 `docs/RUN_RECORD_CONTRACT.md` 记录真实回执到本轮 `EVENTS.jsonl`，并用 `fabric report RUN_DIR` 生成只读摘要。Review 引用其审查的 delivery 事件，裁决再引用两者；人工权限批准使用明确的 `permission_approved` 动作。无回执就保留未知。摘要不查询 Orca，续工/收尾仍须对账原 Run。

新计划的 Reviewer 材料要求 Reviewer 自己同时写 REVIEW.md 与结构化 REVIEW.json；对旧冻结材料保持原格式，需补结构化回执时等旧 Dispatch 结算后用累积 DELTA 追加。若启动预算或墙钟用尽，不自动扩窗；只有新的明确人工授权才能追加绑定原计划批准与 SHA 的 `budget_window`，并保持全部旧 intent 计数。多路径累计预算仍由 controller 核对。

主 Codex 回合结束后，首版不会由 Worker 自动唤醒；人工接回时先读取原 `REQUEST.md`、定位 ID 和交付，再向 Orca 对账。未经用户授权不 commit、push、merge 或 deploy。

## 多候选分层模式（仅配置启用时）

若 `fabric.json` 有 `delivery`，先读安装包 `docs/DELIVERY_CONTRACT.md`。本模式必须选到独立 Reviewer；不能沿用上文“只有确需第二意见时才派”的旧默认。候选配对、证据和裁决使用只读 `fabric delivery INPUT.json --project PROJECT`，其 ready 声明和文件摘要仍须由真实 Orca/Agent 回执及人工检查支撑。Reviewer 的 PASS 不代替 controller 接受；下游只在最新候选接受并与 Orca 对账后派工。返工归因与材料性决定由 controller 作出，同 Task 最多两次业务返工。

可选 manager 模式按 `fabric-manager` Skill 单独承担**唯一**执行协调 Loop；controller 只规划、裁决和最终判断。无真实模型/权限/唤醒/恢复证据时，保持本节核心切片的主控协调模式，不把 manager 标为已验收。

## 冻结计划材料（显式使用 `prepare --plan` 时）

`fabric prepare TASK.md --project PROJECT --plan PLAN.json` 解析计划中的实际 profile、模型、effort、路径和 Skill 摘要，生成 `plan.json`、`PLAN.md`、简短 `REQUEST.md` 与每个 Task 的 `round-0/TASK.md`、`CURRENT.json`。先把 PLAN.md 给用户核对；用户确认后，由 controller 按 RUN_RECORD_CONTRACT 记录 `plan_approved` decision，引用 plan SHA-256 与真实用户消息。该事件只是本地回执，Fabric 不认证会话身份。

`fabric dispatch RUN_DIR TASK_KEY --round N --dry-run` 是零 Orca 调用的本地预览。真实入口 `fabric dispatch RUN_DIR TASK_KEY --round N --run RUN_ID --from COORDINATOR_HANDLE --task TASK_ID` 只会启动 Orca 已创建且经 run-show/task-list/worker-list 复核的 ready Task；它不会创建 Run/Task/终端、绑定、接管、重试或释放。同一 RUN_DIR 的真实入口用 `.dispatch-entry.lock` 串行覆盖预算、原生预查、调用意图与 worker-start；若进程中断留下锁，先核对本地意图和原生 Task/Dispatch，再显式处理该锁，不能推断未启动或自动重试。controller 必须先用真实用户消息记录匹配 plan SHA-256 的 `plan_approved`，并保留原生 Run/Task ID。计划派工还要求 Worker/Reviewer 静态 profile 均明确且 Code Agent、modelIdentity 不同；派后另核对实际模型、session 与开始回合。重复启动或调用结果不确定时先读本地 intent/raw receipt 并向 Orca `request-show` 对账，不删除资料、不盲重发、不以缺少进程观察推断已退出。任何缺少模型/effort、依赖、预算或生命周期证据的情况停止派工并报告。

计划模式下，controller 可按 Orca 原生 `task-create --spec <稳定 TaskSpec> --deps <JSON Task ID 数组> --run RUN_ID --from HANDLE` 建好 DAG；每个 TaskSpec 必须等于 Fabric 预览。派工串行进行：每次启动前重读原生状态与材料；Worker 依赖必须有最新候选接受，Reviewer 只要求上游 Worker Task 已完成且候选/验收文件摘要固定，不能把 Review PASS 当作它自身启动前置条件。使用 `check --wait` 等待真实消息；逐项处理一整批 Delivery 后再 `--ack`，普通等待不发送唤醒或催促。检查 Orca 生命周期时遵循版本匹配恢复指南：unknown 保持 unknown，不能自动 retry/stop/release。独立 Reviewer 与用户接受 Gate 保持有效；结束时复用、明确保留或 release，release 不确定不能用 terminal close 代替。
