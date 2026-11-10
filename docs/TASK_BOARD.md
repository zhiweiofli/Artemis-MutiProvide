# ARTEMIS Google 解耦平替 — 阶段任务看板 (Phase & Gate Task Board)

> **版本**：1.1.0（对齐 `Spec v1.1` 与 `ADR-007` 五角色隔离流水线）  
> **状态更新与自动重编译规则（AGENTS.md §4 强制门禁）**：
> 1. 每次完成一个 Phase（或发起 `Test Dispute`）时，必须同步更新本文件与 `.archify/explainer-phase-task-board-20261109-141300/candidate.archify.md`，并执行 `node .agents/skills/archify/bin/archify.mjs finalize explainer .archify/explainer-phase-task-board-20261109-141300/candidate.archify.md .archify/explainer-phase-task-board-20261109-141300/phase-task-board.html --repo-root . --json` 刷新 HTML 看板。
> 2. 自 `P2-GREEN` 阶段起，运行 `uv run python scripts/gate.py --level L4 --phase <PHASE> --json` 将根据实测结果自动改写本看板并重编译 HTML 页面。  
> **关联交互式可视化看板**：[`.archify/explainer-phase-task-board-20261109-141300/phase-task-board.html`](file:///Users/zw-mini/orca/artemis/.archify/explainer-phase-task-board-20261109-141300/phase-task-board.html)

---

## 1. 五阶段主看板 (Phase Pipeline Board)

| Key | 阶段名称 (`title`) | 负责角色与模型 (`role`) | 前置依赖 (`deps`) | 放行门禁命令 (`gate`) | 状态 (`status`) | 交付证据路径 (`evidence`) |
|---|---|---|---|---|---|---|
| **`P0-SPEC`** | 独立架构审查与 `Spec v1.1` 冻结 | **Spec Owner**<br>*(Claude Opus 5.5 / Gemini 4 Argon)* | - | `node .agents/skills/workbench-project/scripts/check.mjs doctor .` → `healthy` | `DONE` | • [`OPUS_INDEPENDENT_REVIEW.md`](file:///Users/zw-mini/orca/artemis/docs/OPUS_INDEPENDENT_REVIEW.md)<br>• [`TECHNICAL_SPEC_DEEPSEEK_QWEN.md`](file:///Users/zw-mini/orca/artemis/docs/TECHNICAL_SPEC_DEEPSEEK_QWEN.md)<br>• [`ARCHITECTURE_DECISIONS.md`](file:///Users/zw-mini/orca/artemis/docs/ARCHITECTURE_DECISIONS.md) |
| **`P1-RED`** | 先验契约测试编写 (`T-01` ~ `T-12`) | **Test Author**<br>*(AGY / Flash 三轮，Argon High 兜底完成)* | `P0-SPEC` | 旧 25 项通过，新 12 项 Expected Red；第 4 次独立审查 PASS，Controller 已接受并冻结 | `DONE` | • `tests/unit/test_preset_switching.py`<br>• `tests/unit/test_deepseek_qwen_providers.py`<br>• `tests/unit/test_object_detector_coords.py`<br>• `.fabric/runs/run-t0C4y7/p1-red-tests/FROZEN_TESTS.json`<br>• `.fabric/runs/run-t0C4y7/p1-red-review/round-3/REVIEW.md` |
| **`P2-GREEN`** | 双通道路由、`presets_v2`、后门清理与坐标自适应实现 | **Implementer**<br>*(Gemini 3.8 Flash)* | `P1-RED` | `uv run python scripts/gate.py --level L4 --json` 返回码 `0`（既有 25 项 + 新增 12 项全部 `PASSED`） | `DONE` | • 首次 P3 审查 REWORK：Standards 5 项 + Spec 9 项，另有 15 项 Explorer 回归<br>• `.fabric/runs/run-t0C4y7/p3-final-review/round-0/REVIEW.md`<br>• 累计启动 11/16，截止北京时间 16:38:22 |
| **`P3-REVIEW`** | Standards + Spec 双轴独立代码审查 | **Independent Reviewer**<br>*(Codex / GPT-6.1-Sol)* | `P2-GREEN` | 加载 `matt-code-review` 完成双轴审查；零 P0/P1 缺陷；确认 `tests/` 未被 Implementer 篡改 | `READY` | • `docs/CODE_REVIEW_P3.md`（首次 REWORK 记录） |
| **`P4-BENCH`** | 端点能力先验探针与六维自动化基准验收 | **Bench Operator**<br>*(脚本化执行角色)* | `P3-REVIEW` | `probe_capabilities.py` 全绿；`run_benchmark_comparison.py` 满足 $\text{TSR Ratio} \ge 98\%$ 且降本 $\ge 70\%$ | `BLOCKED` | • `.artemis/capabilities.json`<br>• `.benchmark/results_*.json`<br>• 差分验收报告 |

---

## 2. 各阶段任务卡详情（遵循 AWB `task-context` 六要素规范）

### Card `P1-RED`：编写 `T-01` ~ `T-12` 先验契约单元测试
- **目标与交付**：将 `Spec v1.1` §7.2 中的 12 项契约转化为可执行的 pytest 单元测试，在未修改业务代码前证实全部预期失败（Red 状态），随后冻结测试文件。
- **范围与约束**：
  - **仅允许写入**：`tests/unit/test_preset_switching.py`、`tests/unit/test_deepseek_qwen_providers.py`、`tests/unit/test_object_detector_coords.py`。
  - **严禁修改**：任何业务代码、`config/artemis.jsonc` 或既有测试文件。
  - **隔离要求**：所有测试必须通过 `monkeypatch` 隔离环境变量与 `settings`，并在 fixture 中清空 `ModelFactory._cache`。
- **相关事实**：
  - 既有网关测试 `tests/unit/test_llm_gateway.py`、`test_llm_reliability.py`、`test_llm_structured.py` 共 25 项全部通过（1.27s）。
  - 目标接口签名已在 [`docs/TECHNICAL_SPEC_DEEPSEEK_QWEN.md` §2~§5](file:///Users/zw-mini/orca/artemis/docs/TECHNICAL_SPEC_DEEPSEEK_QWEN.md) 中精确定义。
- **未知项**：若发现 `Spec v1.1` 中某函数签名与现有模块导入存在循环依赖，记录在案并交由 Spec Owner 调整签名。
- **执行入口**：
  ```bash
  uv run pytest tests/unit/test_preset_switching.py tests/unit/test_deepseek_qwen_providers.py tests/unit/test_object_detector_coords.py -q
  ```
- **完成标准**：新增 12 项测试收集成功且因功能未实现而失败（非语法或导入错误），既有 25 项测试 100% 保持通过。

---

### Card `P2-GREEN`：业务层最小实现与门禁脚本落地
- **目标与交付**：按 `Spec v1.1` §2~§6 完成双通道配置、`presets_v2` 加载器、5 处 Google 硬编码清理、结构化输出协商、`coord_format` 坐标归一化及 `probe_capabilities.py` / `gate.py`。
- **范围与约束**：
  - **允许写入**：参见 [`HANDOFF.md` §5.2](file:///Users/zw-mini/orca/artemis/HANDOFF.md#L69-L74) 授权白名单。
  - **红线约束**：**严禁修改 `tests/` 目录下的任何文件**。若认为某条测试断言有误，必须停止修改并提交 `Test Dispute`（附代码事实与行号）由 Spec Owner 裁决。
  - **基线保护**：保持顶层扁平 `presets` 不变以兼容 Admin Console；保持 `gemini-baseline` 预设行为 100% 不变。
- **执行入口**：
  ```bash
  uv run python scripts/gate.py --level L4 --json
  ```
- **完成标准**：`gate.py --level L4` 返回码为 `0`（25 项既有测试 + 12 项新增契约测试共 37 项全部 `PASSED`）。

---

## 3. P0 阻断项 (B1 ~ B7) 与先验测试 (`T-01` ~ `T-12`) 追踪矩阵

| 阻断项 ID | 阻断项概述 | 设计消解章节 (`Spec v1.1`) | 对应契约测试 | 测试状态 | 代码消解状态 |
|---|---|---|---|---|---|
| **B1** | `presets` 未在 Python 侧实现，嵌套结构与 Admin Console 扁平结构冲突 | §2.4, §2.5 (`presets_v2` + `resolve_preset_config`) | `T-01`, `T-02` | `GREEN` | `RESOLVED` |
| **B2** | 节点只写 `model` 引发 Provider 继承泄漏；5 处硬编码 `get_google_llm` | §2.5, §3.1, §3.2 (`get_llm_for_model` + 修正 `is_utils=False`) | `T-03`, `T-04` | `GREEN` | `RESOLVED` |
| **B3** | 同厂商 Fallback 相关性故障；纯文本 Fallback 报 400 不降级；402 未映射 | §2.3, §2.4, §4.4 (阶段一跨厂商 Fallback + `is_multimodal` 校验 + 402 降级) | `T-07`, `T-09` | `GREEN` | `RESOLVED` |
| **B4** | 结构化协议冲突：`ChatOpenAI.with_structured_output` 默认 `json_schema` 引发兼容端点 400 | §4.3 (Wrapper 自动协商 `method="function_calling"`) | `T-08` | `GREEN` | `RESOLVED` |
| **B5** | 自定义 `base_url` 默认关闭 `stream_usage` 且开启 SDK 内部 `max_retries=2` | §4.2, §4.4 (`stream_usage=True, max_retries=0` + `prompt_cache_hit_tokens`) | `T-05`, `T-06`, `T-09` | `GREEN` | `RESOLVED` |
| **B6** | Detector 无条件翻转 `[y,x]`；`box_2d` 与 `bbox_2d` 混淆；百炼 Qwen2.5-VL 输出绝对像素 | §5.1, §5.2 (`coord_format` 五格式纯函数 + 图像宽高像素归一化) | `T-10`, `T-11` | `GREEN` | `RESOLVED` |
| **B7** | Detector 10s 超时等于 RateLimit 退避基准；吞异常且未接入 `with_fallback` | §5.2 (百炼超时 `25.0s` + `with_fallback` 闭环) | `T-12` | `GREEN` | `RESOLVED` |

---

## 4. AWB 五层验证门禁看板 (L1 ~ L5 Verification Gates)

| 验证层级 | 门禁定义 | 验证命令 | 当前状态 | 最近验证结果 |
|---|---|---|---|---|
| **L1 项目入口可读取** | `.agent/contract.json` 与核心文档完备 | `node .agents/skills/workbench-project/scripts/check.mjs doctor .` | `PASS` | `status: healthy` (2026-11-09) |
| **L2 能力文件已安装** | `.agents/skills/` 下 6 项原子 Skill 完整 | 检查 `.agents/skills/{workbench-project,matt-tdd,matt-codebase-design,matt-diagnosing-bugs,matt-code-review,archify}` | `PASS` | 6 项 Skill 目录就绪（注：本地 `skills-hub` 仓库存在 `agents365-daisy-financial-research` 摘要校验报错，待修复） |
| **L3 依赖/宿主可用** | Python / uv 环境与端点能力探针通过 | `uv run pytest ...` & `uv run python scripts/probe_capabilities.py` | `PARTIAL` | 本地 pytest 就绪（25 passed in 1.27s）；真实 API 探针待 `P4-BENCH` 执行 |
| **L4 真实任务已完成** | `T-01`~`T-12` 与既有单测全绿，离线 Grounding 通过 | `uv run python scripts/gate.py --level L4 --json` | `PASS` | 目标 37 项与边界 321 项通过，但独立审查发现真实预设、视觉提示、模态保护、验证工具真实性等缺陷；占位 Key 完整套件另有 15 项 Explorer 新回归，P2 返工中 |
| **L5 新会话接手与验收** | 六维基准达标，`HANDOFF.md` 与 `TASK_BOARD.md` 闭环 | `uv run python scripts/run_benchmark_comparison.py` | `PENDING` | 等待 `P4-BENCH` 验收 |
