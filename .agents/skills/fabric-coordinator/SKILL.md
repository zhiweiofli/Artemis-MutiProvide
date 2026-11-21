---
name: fabric-coordinator
description: 在 Fabric 2.0 阶段委托中，通过 Orca 派发 Worker、等待交付、安排独立 Review 和有限返工。用于明确的 Fabric 协调任务；普通编码请求不启用此流程。
---

# Fabric 外 Loop

你负责一个完整阶段的交付。先读 REQUEST.md 指向的项目规则、TASK.md 与 CONFIG.json，以任务原文和角色配置快照中的 maxReworks 为准。

1. 先读指定 Orca 二进制返回的 `skills get orchestration`；新工作区或复用终端时按指南读取对应参考。使用真实返回的 ID，不从标题或占位符猜。
2. 用一句话确认交付目标。范围清楚就推进；目标或架构真正分叉时汇总一个决策，不反复询问“继续”。
3. 检查本轮 ORCA_RUN.json；已有 Run 就核对现场与收件箱，没有才 run-create。把真实 runId 与 Orca executable 写入 ORCA_RUN.json，只有定位信息，不复制状态库。
4. 派发一个完整 Worker 阶段。使用配置的 worker.orcaAgent、目标工作区与原生 worker-start。若有 profile.model/effort，按 Orca 文档传递并核对实际生效值；launch 数组仅用于协调者终端，不能假定 Worker 继承其参数。
5. Worker spec 保持简短：引用本轮 REQUEST.md 中的原项目绝对路径，要求 Worker 读取 TASK.md、CONFIG.json、目标项目 AGENTS.md 和 fabric-worker/SKILL.md；写明当前 Orca Task 的实际工作区及本轮交付目录。不要复制任务或 Skill 全文。若目标是不同 worktree，仍引用原项目中的绝对材料/规则路径；Worker 无法读取任一必需文件时应走 question/escalation，不能省略规则。明确交付后停止编辑，按 Orca 注入的生命周期前言报告 worker_done。
6. 用原生 check --wait 接收 worker_done/question/escalation。问题先处理再 ack；超时只表示还没消息。按原生指南管理 Dispatch 与终端，不盲重发或自行推测退出。
7. Worker 完成后检查 DELIVERY.md 和真实候选位置。将候选位置与本轮 TASK.md、CONFIG.json、DELIVERY.md 的原项目绝对路径，以及实际工作区路径交给 reviewer.orcaAgent，要求 Reviewer 自行读取原项目 AGENTS.md 和 fabric-reviewer/SKILL.md；不要内联任务/规则全文。不同 worktree 的 Reviewer 仍须读取原项目绝对路径；不可读时先 question/escalation。以新 Agent 上下文审查。顺序执行，避免两个写者；你不替 Worker 偷修后再接受旧 review。
8. 读取 REVIEW.md。PASS 才汇总待人类验收；REWORK 把具体问题和上一候选位置交给后继 Worker Dispatch；最多 maxReworks 次。NEEDS_DECISION、预算耗尽或权限阻塞时汇总实际情况。
9. round-0 起按轮保存 DELIVERY.md、REVIEW.md；不得覆盖历史轮。按 Orca 指南复用、保留或释放已结束的 Worker，并处理完收件箱。最终根目录 DELIVERY.md 写明 outcome、轮数、Agent、实际验证、遗留与候选位置；Orca lifecycle succeeded 不等于产品 PASS。

结束标准：用户拿到完整阶段交付或一个具体阻塞包。禁止把 TUI idle、工具退出码或模型自述单独作为业务完成依据。提交、合并、发布沿用用户明确授权，默认不执行。
