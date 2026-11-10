# P1-RED：编写 T-01 ~ T-12 先验契约单元测试

## 目标与交付
作为 Worker (`agy`)，严格依据 `docs/TECHNICAL_SPEC_DEEPSEEK_QWEN.md` §7.2，在 `tests/unit/` 下编写 3 个单元测试文件（覆盖 `T-01` ~ `T-12`），验证在未修改业务代码前全部处于 Expected Fail (Red) 状态，且既有 25 项测试 100% Pass。

## 范围与约束
- **仅允许写入**：
  - `tests/unit/test_preset_switching.py` (`T-01` ~ `T-04`)
  - `tests/unit/test_deepseek_qwen_providers.py` (`T-05` ~ `T-09`)
  - `tests/unit/test_object_detector_coords.py` (`T-10` ~ `T-12`)
  - 看板同步文件：`docs/TASK_BOARD.md`、`.archify/explainer-phase-task-board-20261109-141300/candidate.archify.md` 及 HTML
- **禁止修改**：`artemis/`、`third_party/`、`config/artemis.jsonc` 或既有测试文件。
- **测试隔离要求**：所有用例必须使用 `monkeypatch` 隔离环境变量与 `settings`，并在 `autouse` fixture 中执行 `ModelFactory._cache.clear()`。

## 执行入口与完成标准
1. `uv run pytest tests/unit/test_llm_gateway.py tests/unit/test_llm_reliability.py tests/unit/test_llm_structured.py -q` → `25 passed`
2. `uv run pytest tests/unit/test_preset_switching.py tests/unit/test_deepseek_qwen_providers.py tests/unit/test_object_detector_coords.py -q` → 12 项测试收集成功且全部 Expected Fail（无语法错误）
3. 更新 `docs/TASK_BOARD.md` 与 `candidate.archify.md`（`P1-RED` 标为 `DONE`），运行 `node .agents/skills/archify/bin/archify.mjs finalize explainer .archify/explainer-phase-task-board-20261109-141300/candidate.archify.md .archify/explainer-phase-task-board-20261109-141300/phase-task-board.html --repo-root . --json`。
