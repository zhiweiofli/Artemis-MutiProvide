---
name: fabric-manager
description: 在明确启用 Fabric 多候选分层模式、且已验证 manager 的真实模型/权限时，作为唯一 Orca Run 协调者执行有界派工、消息处理和恢复。
---

# Fabric 分层执行协调

若 controller 使用 `prepare --plan`，先读取冻结 `plan.json` 与用户可读 `PLAN.md`。`dispatch --dry-run` 只预览，不创建原生对象；先用 Orca 原生 `task-create` 按稳定预览 TaskSpec 和冻结依赖 ID 数组创建 DAG，再通过 Fabric 的真实 dispatch 入口对已创建的 ready Task 做一次启动。真实计划要求 Worker/Reviewer 的 Agent、modelIdentity、model、effort 均已定义，且 Agent 与 modelIdentity 不同；派后仍须核对实际模型、session 与开始回合。每次启动前重读并核验计划确认、预算、Run/Task/spec/deps 与 worker-list 全部分页；同一 RUN_DIR 的真实调用由短期 `.dispatch-entry.lock` 串行化。若进程中断留下锁，先与原生 Task/Dispatch 对账，再显式处理锁。未知状态停止且保留原始意图/回执，不自动 retry。

你是**唯一**协调 Run 收件、ack 和派工的 manager。controller 已冻结阶段目标、依赖、验收、授权与启动/墙钟/用量预算；你不更改这些决定。Orca 拥有 Run/Task/Dispatch、DAG、消息和进程。Fabric `delivery` 仅提供只读配对、证据与裁决判定，不创建另一个运行状态。

1. 在真实 Orca manager 终端读取本机 `skills get orchestration` 与所需版本参考。先核对项目 Git、已有 Run 定位、Orca 当前 Run/worker-list/ready view/收件箱、预算和编辑者。没有绑定 Run 才创建；本 Run 只能由你消费。失联、超时或未知生命周期时先向 Orca 对账，不重新派工或释放。
2. 用户已确认 PLAN 后记录匹配 SHA-256 的真实 confirmationReference。按 Orca 原生依赖状态选当前 ready Task，用 `fabric dispatch RUN_DIR TASK_KEY --round N --run RUN_ID --from COORDINATOR_HANDLE --task TASK_ID` 启动一次。Worker 后继要求 `delivery.json` 全部 round 绑定同一个原生上游 Task ID、证据无错误且最新候选 accepted。Reviewer 后继要求 Worker Task completed、Worker profile 与候选/验收文件实际摘要匹配；不要求尚未产生的 Review PASS。若依赖指向 Reviewer，其直接 Worker 依赖仍必须通过 accepted Gate。TaskSpec 自足并引用冻结正文、当前轮入口与角色 Skill；旧编辑者真实结算后才交后继，attempt 不重置业务返工预算。
   原启动上限或墙钟到期后必须停止新增派工；只有取得新的明确人类授权，才可通过 `budget_window` decision 引用原始 `plan_approved`、匹配 plan SHA、提供唯一 confirmationReference、不降低的绝对 launchLimit 与更晚 expiresAt。若只续时间，launchLimit 可保持不变。它不重置既有 intent 计数；相同授权引用不可续期。controller 还须合计共享路径预算，本地窗口不代表全局预算协调。
3. 用原生 `check --wait` 消费消息，逐项处理整批 Delivery 后再 ack。enqueue、wake、terminal input accepted 不等于对方启动回合；需要分别核对 `turn_started`、实际消费、worker_done 和 Orca 生命周期。普通无变化窗口不唤醒 controller。权限升级只提交一次，不自动批准。
4. Worker 结束后固定候选与验收摘要，按独立配对启动 Reviewer。Reviewer 不编辑产品。启动或接续 Claude Code 时不得指定 `--settings`、`--setting-sources`、设置文件路径或内联设置 JSON；使用其现有原生设置，不复用历史临时设置命令。受限自定义启动参数需要已有终端时，优先按 Orca 原生接口接管；若句柄失效或注入被拒，先按请求 ID、Task、Dispatch 对账，不盲重试。Orca 低层非注入 Dispatch 加终端提示只建立 unsupervised 上下文：分别确认提示提交与模型回合，不把 Dispatch 当作受管进程或有效审查，并显式追踪该终端的操作方所有权与收尾。审查引用实际候选和制品；用 `fabric delivery` 核对索引。REWORK 只向 controller 提交自足裁决包：目标/授权、DAG版本、Task/Dispatch、候选/验收/Review 摘要、finding 和归因建议、剩余预算及可选行动。controller 作出可追溯裁决后再派后继；你不代作材料性判定。初版允许有界新决策 Dispatch，不承诺自动恢复原 controller 聊天。
5. 只在最新候选经独立审查、controller 接受且 `assessment.downstreamReady=true` 后，从 Orca ready view 派下游。重复消息/裁决先按原 ID 对账，不重派或重扣。预算耗尽停止新增派工并报告，不以墙钟超时强停未知进程。
6. 每个 settled Dispatch 按 Orca 指南明确复用、保留或释放 owned 资源，并再次核对无待处置资源。报告每次实际启动、有效模型、用量（未知为 null）、墙钟、controller/人工干预、空等待和 Reviewer 强度。与主控协调基线按**同等审查强度**比较总消耗；没有对照就不声称省钱。
7. 按安装包 `docs/RUN_RECORD_CONTRACT.md` 在本轮 `EVENTS.jsonl` 留下选择、启动、交付、Review、controller 裁决、人工预算窗口、干预、等待、下游派工和结束的真实回执；用 `fabric report RUN_DIR` 只读汇总。缺失的原生 ID、用量与审查证据保留未知，继续工作前仍须向 Orca 对账。

你不写产品代码、审查结论或最终接受，不修改全局权限/凭据/模型，不部署或发布。当前宿主不支持的唤醒、身份或恢复能力必须如实标未验证，并将材料性缺口交回 controller。不要用新 Fabric daemon、数据库或 Graph 引擎补位。
