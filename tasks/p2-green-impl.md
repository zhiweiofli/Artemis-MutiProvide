# P2-GREEN：双通道配置、路由、后门清理与坐标自适应最小实现

## 目标与交付
作为 Worker (`agy`)，在冻结 `tests/unit/` 测试文件的前提下，严格按 `docs/TECHNICAL_SPEC_DEEPSEEK_QWEN.md` §2~§6 完成业务层最小实现与 `scripts/gate.py`、`scripts/probe_capabilities.py`，使全部 37 项单测（既有 25 项 + 新增 12 项）通过并自动同步更新看板。

## 范围与约束
- **允许写入**：`HANDOFF.md` §5.2 授权文件清单（`artemis/config/`、`third_party/mobile_use/config/llm.py`、`config/artemis.jsonc`、`artemis/llm/`、`artemis/services/llm.py`、`artemis/memory/chunking.py`、`artemis/agents/flash/`、`artemis/agents/explorer/explorer.py`、`artemis/agents/object_detector/`、`scripts/`、`docs/TASK_BOARD.md`、`.archify/`）。
- **严禁修改**：`tests/` 目录下的任何文件。若认为某条测试断言与规格冲突，必须停止并报告 `NEEDS_DECISION`（Test Dispute）。

## 执行入口与完成标准
1. `uv run python scripts/gate.py --level L4 --phase P2-GREEN --json` 返回码为 `0`（自动刷新 `docs/TASK_BOARD.md` 与 `phase-task-board.html`）；
2. `uv run pytest tests/unit/test_third_party_boundary.py -q` 通过；
3. `node .agents/skills/workbench-project/scripts/check.mjs doctor .` 输出 `healthy`。
