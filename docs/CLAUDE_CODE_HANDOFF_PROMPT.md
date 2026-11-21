# Claude Code (Fabric 3.0 Manager) 启动交接指令书

> **工作区路径**：`/Users/zw-mini/orca/artemis`  
> **编排底座**：**Harness Fabric 3.0 (`3.0.0-dev.4`)**（在线 `fabric doctor` 9 项检查全部 `pass`）  
> **角色拓扑 (`tasks/plan.json`)**：
> - **Controller & Manager**：`claude-code` (`orcaAgent: "claude"`) — 负责 Orca Run/Task DAG 创建、`fabric dispatch` 派工、`check --wait` 收件箱消费、裁决与升级
> - **Worker**：`agy` (`orcaAgent: "antigravity"`, `gemini-3.8-flash`) — 负责执行 `p1-red-tests`（编写 `T-01`~`T-12` 先验测试）与 `p2-green-impl`（业务层最小实现与 `scripts/gate.py`）
> - **Independent Reviewer**：`codex` (`orcaAgent: "codex"`, `gpt-5-codex`) — 负责执行 `p1-red-review`（先验测试审查）与 `p3-final-review`（Standards + Spec 双轴独立审查）
> **已冻结 Run 目录**：`/Users/zw-mini/orca/artemis/.fabric/runs/run-rIQ5fl`  
> **冻结计划 SHA-256**：`5df38ed26b0df892a83d4ee273e41650cb0ebf3396e8feb2057e142a2ad77086`

---

## 直接复制给 Claude Code（在 Orca 当前工作区终端）的启动 Prompt

```markdown
请读取 `/Users/zw-mini/orca/artemis/.fabric/runs/run-rIQ5fl/REQUEST.md` 与 `/Users/zw-mini/orca/artemis/.fabric/runs/run-rIQ5fl/PLAN.md`，并加载 `/Users/zw-mini/orca/artemis/.claude/skills/fabric-main/SKILL.md` 与 `/Users/zw-mini/orca/artemis/.claude/skills/fabric-manager/SKILL.md`。

我确认并批准该冻结执行计划（planSha256: `5df38ed26b0df892a83d4ee273e41650cb0ebf3396e8feb2057e142a2ad77086`）。请你作为本项目的 **Fabric 3.0 Controller & Manager (`claude-code`)**，严格按以下流程启动并推进 4 阶段 DAG（`p1-red-tests` → `p1-red-review` → `p2-green-impl` → `p3-final-review`）：

1. **记录计划批准回执 (`plan_approved`)**：
   - 使用 `./.fabric/runtime/node_modules/.bin/fabric record /Users/zw-mini/orca/artemis/.fabric/runs/run-rIQ5fl <EVENT.json>` 写入 `kind: "decision"`, `source: "human"`, `result: { "action": "plan_approved", "planSha256": "5df38ed26b0df892a83d4ee273e41650cb0ebf3396e8feb2057e142a2ad77086", "confirmationReference": "user-approved-run-rIQ5fl" }`。

2. **创建 Orca Run 与 4 阶段 Task DAG**：
   - 先运行 `/Applications/Orca.app/Contents/Resources/bin/orca skills get orchestration` 读取当前 Orca 编排指南；
   - 对每个 Task（`p1-red-tests`, `p1-red-review`, `p2-green-impl`, `p3-final-review`）先运行 `./.fabric/runtime/node_modules/.bin/fabric dispatch /Users/zw-mini/orca/artemis/.fabric/runs/run-rIQ5fl <TASK_KEY> --round 0 --dry-run` 获取精确的稳定 `taskSpec`；
   - 在 Orca 中创建单个 Run（将真实 Run ID 记录到 `/Users/zw-mini/orca/artemis/.fabric/runs/run-rIQ5fl/ORCA_RUN.json`），并用 `orca orchestration task-create --spec <稳定 taskSpec> --deps <JSON Task ID 数组> --run <RUN_ID> --from <YOUR_HANDLE>` 建立完整 4 节点 DAG。

3. **按依赖顺序串行派工、审查与裁决**：
   - **Step 1 (`p1-red-tests` → AGY Worker)**：调用 `./.fabric/runtime/node_modules/.bin/fabric dispatch /Users/zw-mini/orca/artemis/.fabric/runs/run-rIQ5fl p1-red-tests --round 0 --run <RUN_ID> --from <YOUR_HANDLE> --task <TASK_ID>` 启动 AGY Worker 编写 `T-01`~`T-12` 先验失败测试；用 `orca orchestration check --wait` 等待 `worker_done`，核验 `DELIVERY.md` 及实际测试文件并写入 `p1-red-tests/delivery.json` 与 `EVENTS.jsonl`。
   - **Step 2 (`p1-red-review` → Codex Reviewer)**：派发 Codex Reviewer 独立审查先验测试并产出 `REVIEW.md` + `REVIEW.json`；若 `verdict: "PASS"`，记录 `accept` 裁决以解锁下游。
   - **Step 3 (`p2-green-impl` → AGY Worker)**：派发 AGY Worker 完成业务代码实现与 `scripts/gate.py`（自动刷新 `docs/TASK_BOARD.md` 与 Archify HTML 看板），验证 37 项单测全绿。
   - **Step 4 (`p3-final-review` → Codex Reviewer)**：派发 Codex Reviewer 执行最终 Standards + Spec 双轴审查，完成后运行 `./.fabric/runtime/node_modules/.bin/fabric report /Users/zw-mini/orca/artemis/.fabric/runs/run-rIQ5fl` 向我汇总交付。
```
