# P3-FINAL-REVIEW：Standards + Spec 双轴独立审查

## 目标与交付
作为独立 Reviewer (`codex`)，加载 `.agents/skills/matt-code-review/SKILL.md` 对 `p2-green-impl` 的全部改动执行 Standards（`AGENTS.md` P-001~P-008）与 Spec（`docs/TECHNICAL_SPEC_DEEPSEEK_QWEN.md` v1.1）双轴审查，生成本轮 `REVIEW.md`、`REVIEW.json` 以及 `docs/CODE_REVIEW_P3.md`。

## 审查核对清单
1. 确认 `tests/unit/test_preset_switching.py`、`test_deepseek_qwen_providers.py`、`test_object_detector_coords.py` 在 `p2-green-impl` 阶段未被篡改或弱化断言；
2. 实跑 `uv run python scripts/gate.py --level L4 --phase P2-GREEN --json` 与 `uv run pytest tests/unit/test_third_party_boundary.py -q`，确认返回码均为 `0`；
3. 核查 B1~B7 七项阻断项在业务代码中已彻底消解，无遗留硬编码 Google 调用后门；
4. 确认 `docs/TASK_BOARD.md` 与 `.archify/explainer-phase-task-board-20261109-141300/phase-task-board.html` 已同步更新。
