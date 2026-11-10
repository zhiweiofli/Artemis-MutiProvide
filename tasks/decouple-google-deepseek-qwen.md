# 目标

在 100% 保全 ARTEMIS 移动端双引擎（Flash 响应式循环 + Pro LangGraph 决策图谱）与 Gemini 基线能力的前提下，按已冻结的 `docs/TECHNICAL_SPEC_DEEPSEEK_QWEN.md` (Spec v1.1) 完成 DeepSeek Flash v4 1017（多模态主脑）与阿里云百炼 Qwen-VL（空间坐标定位兜底）的双通道解耦接入，消解 B1~B7 七项 P0 阻断项，并通过 L1~L4 自动化门禁验证。

## 范围与约束

- **允许修改路径**：
  - 测试阶段 (`p1-red-tests`)：`tests/unit/test_preset_switching.py`、`tests/unit/test_deepseek_qwen_providers.py`、`tests/unit/test_object_detector_coords.py`
  - 实现阶段 (`p2-green-impl`)：`artemis/config/constants.py`、`artemis/config/settings.py`、`artemis/config/llm.py`、`third_party/mobile_use/config/llm.py`、`config/artemis.jsonc`、`artemis/llm/router.py`、`artemis/llm/reliability.py`、`artemis/llm/google/usage.py`、`artemis/services/llm.py`、`artemis/memory/chunking.py`、`artemis/agents/flash/summarizer.py`、`artemis/agents/flash/runner.py`、`artemis/agents/explorer/explorer.py`、`artemis/agents/object_detector/object_detector.py`、`artemis/agents/object_detector/object_detector.json`、`scripts/gate.py`、`scripts/probe_capabilities.py`、`scripts/run_benchmark_comparison.py`
  - 看板与交接同步：`docs/TASK_BOARD.md`、`HANDOFF.md`、`.archify/explainer-phase-task-board-20261109-141300/candidate.archify.md` 及对应 HTML
- **严禁触碰**：
  - 在 `p1-red-tests` 阶段严禁修改任何业务代码；
  - 在 `p2-green-impl` 阶段严禁修改或弱化 `tests/` 下的任何测试断言；
  - 严禁破坏 `config/artemis.jsonc` 顶层扁平 `presets` 结构（保持 Admin Console 兼容）与 `gemini-baseline` 默认行为。

## 验收

1. `node .agents/skills/workbench-project/scripts/check.mjs doctor .` 输出 `healthy`；
2. 既有 25 项模型网关测试（`test_llm_gateway.py`、`test_llm_reliability.py`、`test_llm_structured.py`）与跨包边界测试（`test_third_party_boundary.py`）100% 通过；
3. 新增 `T-01` ~ `T-12` 先验契约单元测试全部通过，`uv run python scripts/gate.py --level L4 --phase P2-GREEN --json` 返回码为 `0`；
4. 每次阶段完成时同步刷新 `docs/TASK_BOARD.md` 并重编译 `.archify/explainer-phase-task-board-20261109-141300/phase-task-board.html`。

## 决策边界

- 改变默认激活预设（`active_preset: "gemini-baseline"`）、修改已冻结的测试断言（Test Dispute）、超出允许写入范围，以及 git commit / push / merge / deploy 必须先交由用户裁决。
