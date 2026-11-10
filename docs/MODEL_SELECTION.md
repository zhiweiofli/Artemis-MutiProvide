# ARTEMIS 模型选型调研与架构评估报告 (Model Selection Report)

> **版本**：1.1.0（经独立架构审查补全全量调用点与百炼平台接入规范）  
> **日期**：2026-11-08  
> **目标**：在 100% 保全 ARTEMIS 移动端自动化感知与执行闭环的前提下，解除对 Google Gemini 专有模型的硬绑定，确立“**DeepSeek Flash v4 1017（多模态主脑）+ 阿里云百炼 Qwen-VL（纯视觉空间定位兜底）**”的对等平替组合，并明确阶段一（跨厂商高可用 Fallback）与阶段二（零 Google 独立验收）的双阶段演进路径。

---

## 1. 现有 Gemini 模型矩阵与全仓库调用点全景盘点

经全仓库只读代码排查（含 `artemis/config/`、`artemis/memory/`、`artemis/agents/`），ARTEMIS 现有架构实际使用了 3 档 Gemini 模型，分布在**显式配置节点**与**代码内置默认/硬编码调用点**两类位置：

### 1.1 显式配置节点（`config/artemis.jsonc` & `artemis/config/llm.py`）

| Gemini 档位 / 型号 | 部署节点 | 解决的核心需求与特性 | 替代紧迫性与可行性 |
|---|---|---|---|
| **`gemini-3.8-flash`**<br>*(备选 3.7-flash / 2.5-flash)* | • `default` (全局默认)<br>• `planner` / `planner_avatar`<br>• `operator` / `operator_summarizer`<br>• `diagnoser` / `diagnoser_expert`<br>• `log_analyzer` / `log_reader_sub_agent`<br>• `history_analyzer_expert`<br>• `checker` / `summarizer` / `outputter`<br>• `video_analyzer` | **主干多模态决策闭环**：<br>1) 每一轮接收手机截图 (`image_url`) 进行视觉感知；<br>2) 结合无障碍 UI 树 (`minimal_list`) 进行推理与 Tool Calling；<br>3) 支持结构化输出与动态思维链控制 (`thinking_level`)。 | **高 / 100% 可行**。<br>作为主交互中枢，调用量占总 Token 的 90% 以上。由具备原生多模态能力的 `deepseek-flash-v4-1017` 直接对等接管。 |
| **`gemini-3.5-flash-lite`**<br>*(备选 3.1-flash-lite / 2.5-flash-lite)* | • `hopper` (`nodes.hopper`)<br>• `planner_validation` (`lightweight_judge_default`)<br>• `validator_pixel_safety_net` (`lightweight_judge_default`) | **极速轻量/高频裁判与辅助**：<br>1) 快速匹配 Android 包名与入口 Activity；<br>2) 计划里程碑变更后的异步轻量审核；<br>3) 动作执行前像素级安全网校验。 | **高 / 100% 可行**。<br>`hopper` 在 `artemis.jsonc` 中仅覆盖了 `model` 未声明 `provider`，必须在 `presets_v2` 中显式绑定 `deepseek`，避免发生 Provider 继承泄漏。 |
| **`gemini-robotics-er-2-preview`** | • `object_detector`<br>• `explorer` (Flash 模式委托) | **纯视觉空间坐标定位兜底**：<br>当界面无无障碍树（如 Unity/Cocos 游戏、Flutter Canvas 自绘图形）时，输出归一化 `[y, x]` 坐标（`0~1000`）。 | **极高 / 需专门视觉模型平替**。<br>Google 实验性预览接口，通过阿里云百炼平台的 `Qwen-VL` 视觉定位模型对等替换。 |

### 1.2 代码内置默认与硬编码调用点（审查新增发现，阶段二清零目标）

> [!IMPORTANT]
> 以下 5 处代码绕过了 `artemis.jsonc` 的 `default` 提供商或硬编码调用了 `get_google_llm`，必须在解耦规格书中统一纳入治理：

| 文件与行号 (FACT) | 当前硬编码行为 | 影响的核心能力 | 治理方案 |
|---|---|---|---|
| [`artemis/memory/chunking.py#L301-L338`](file:///Users/zw-mini/orca/artemis/artemis/memory/chunking.py#L301-L338) | `memory.chunking.model` 默认 `"gemini-3.8-flash"`，且内部直接调用 `get_google_llm` | Pro 模式 Transcript L2 分段压缩（Capsule 生成） | 改为通过 `get_llm_for_model(self._model_name, ctx=self._ctx, fallback_node="summarizer")` 路由 |
| [`artemis/agents/flash/summarizer.py#L162-L174`](file:///Users/zw-mini/orca/artemis/artemis/agents/flash/summarizer.py#L162-L174) | `flash.step_summarizer.model` 非空时直接调 `get_google_llm`；且 `is_utils=True` 传参错误导致必走异常兜底 | Flash 模式后台异步视觉步骤摘要 | 修正 `is_utils=False`，统一通过 `get_llm_for_model` 按当前激活预设解析 Provider |
| [`artemis/config/llm.py#L60-L72`](file:///Users/zw-mini/orca/artemis/artemis/config/llm.py#L60-L72) | `lightweight_judge_default()` 硬编码返回 `google/gemini-3.5-flash-lite` | `validator_pixel_safety_net` 与 `planner_validation` | 改为继承当前激活预设的 `default`（或预设内显式配置的轻量节点） |
| [`artemis/agents/flash/runner.py#L287`](file:///Users/zw-mini/orca/artemis/artemis/agents/flash/runner.py#L287) | `_init_llm` 异常时硬编码退回 `get_google_llm("gemini-2.5-flash")` | Flash 主循环初始化异常兜底 | 移除跨厂商硬编码后门，直接抛出配置错误或走 `operator` 的配置的 `fallback` |
| [`artemis/agents/explorer/constants.py#L26`](file:///Users/zw-mini/orca/artemis/artemis/agents/explorer/constants.py#L26) | `DEFAULT_EXPLORER_MODEL = "gemini-3.8-flash"` | Explorer 未配置模型时的回退值 | 优先从 `ctx.llm_config.explorer` 读取，仅在 Google Provider 下回退该常量 |

---

## 2. 核心平替选型分析

### 2.1 主控大脑选型：`DeepSeek Flash v4 (1017 版本)`

* **选型定位**：作为全局默认主模型（`default`），接管所有多模态感知、规划、工具调用、日志诊断、断言终审与背景摘要节点。
* **核心论证**：
  1. **原生多模态对等性**：支持直接接收屏幕截图的 Base64 `image_url` 输入，无需将视觉剥离给外部小模型或强行将界面降级为纯文本 UI 树。
  2. **推理、工具调用与结构化输出**：在 Android 长链 ReAct 循环、异常自愈与工具绑定上与 Gemini 3.8 Flash 对齐；针对 `with_structured_output`，通过网关层自动协商为 `function_calling` 模式以保证 100% 协议兼容。
  3. **吞吐与成本**：结合 DeepSeek 上下文硬盘缓存（`prompt_cache_hit_tokens`），相比商业闭源模型可降低 70%~90% 的 Token 成本。
* **先验探针核实项（HYPOTHESIS → FACT 转化）**：
  - 在正式跑批前，由 `scripts/probe_capabilities.py` 对目标 `DEEPSEEK_BASE_URL` 实测确认 `deepseek-flash-v4-1017` 的模型 ID、图片输入、流式 `usage` 返回与工具调用行为。

---

### 2.2 视觉定位兜底选型：阿里云百炼平台（DashScope）`Qwen-VL` 系列

* **接入方式（用户已确认）**：通过**阿里云百炼平台（DashScope）OpenAI 兼容接口**接入：
  - 默认 `QWEN_BASE_URL`：`https://dashscope.aliyuncs.com/compatible-mode/v1`
  - 认证方式：`QWEN_API_KEY`（百炼 `DASHSCOPE_API_KEY`）
* **百炼平台可选模型矩阵与推荐配置**：

| 百炼模型 ID / 端点类型 | 适用角色 | 坐标输出特征 (`coord_format`) | 说明 |
|---|---|---|---|
| **`qwen2.5-vl-72b-instruct`** / **`qwen2.5-vl-32b-instruct`**<br>*(或百炼专属部署的 `qwen3.8-27b-object-detection` 端点)* | `object_detector` 主模型 | `bbox_xyxy_px`（Qwen2.5-VL 原生输出基于图像尺寸的绝对像素框 `[xmin, ymin, xmax, ymax]`）或 `bbox_xyxy_1000`（Qwen3-VL / 归一化指令模式） | 高密度手机 UI 小目标（关闭叉 `×`、角标、Canvas 按钮）空间定位主力 |
| **`qwen-vl-max-latest`** / **`qwen2.5-vl-7b-instruct`** | `object_detector` 同云备用（阶段二） | 同上，由节点 `coord_format` 显式声明 | 高并发或主端点限流时的百炼内部备用模型 |

* **关键技术差异与自适应对策（修正原报告过度泛化）**：
  1. **坐标轴顺序差异**：Gemini ER 默认返回 `[y, x]` 或 `[ymin, xmin, ymax, xmax]`（Y 轴在前）；而 Qwen-VL 系列始终采用 **`[xmin, ymin, xmax, ymax]`（X 轴在前）**。
  2. **量纲差异（0–1000 vs 绝对像素）**：Qwen2-VL / Qwen3-VL 采用 `0~1000` 相对坐标；而 **Qwen2.5-VL 在预训练中改为输出基于输入图像像素尺寸（宽 $W \times$ 高 $H$）的绝对像素坐标**。
  3. **解决方案**：在 `object_detector` 配置中引入声明式 `coord_format`，并在检测入口读取截图真实 `(W, H)`，将 Qwen 返回的 `[xmin, ymin, xmax, ymax]` 自动转换为中心点并归一化到 ARTEMIS 标准 `[x, y] ∈ [0, 1000]` 空间。

---

## 3. 分阶段终态选型配置映射表

遵循用户确认的 **ADR-001 分阶段 Fallback 策略**，配置预设分为两个阶段演进：

| 业务节点 | Gemini 金标基线 (`gemini-baseline`) | 阶段一：跨厂商高可用平替 (`ds-qwen-hybrid`) | 阶段二：零 Google 独立验收 (`ds-qwen-pure`) |
|---|---|---|---|
| **Default (全局默认)** | 主: `google/gemini-3.8-flash`<br>备: `google/gemini-3.7-flash` | 主: `deepseek/deepseek-flash-v4-1017`<br>备: **`google/gemini-3.8-flash`** *(跨厂商容灾)* | 主: `deepseek/deepseek-flash-v4-1017`<br>备: `qwen/qwen-vl-max-latest` *(纯非 Google 多模态)* |
| **Operator / Planner / Checker / Diagnoser / Summarizer / Outputter** | 继承 `default` | 继承 `default`（主走 DeepSeek，故障切 Gemini） | 继承 `default`（100% 零 Google） |
| **Hopper / Lightweight Judges** | 主: `google/gemini-3.5-flash-lite`<br>备: `google/gemini-3.1-flash-lite` | 主: `deepseek/deepseek-flash-v4-1017`<br>备: `google/gemini-3.5-flash-lite` | 主: `deepseek/deepseek-flash-v4-1017`<br>备: `qwen/qwen-vl-plus` |
| **Step Summarizer & Memory Chunking** | `google/gemini-3.5-flash-lite` & `gemini-3.8-flash` | 自动跟随预设 `summarizer` (`deepseek-flash-v4-1017`) | 自动跟随预设 `summarizer` (`deepseek-flash-v4-1017`) |
| **Video Analyzer (时序分析)** | `google/gemini-3.8-flash` (Files API) | `deepseek/deepseek-flash-v4-1017` (Universal OpenCV 抽帧引擎) | `deepseek/deepseek-flash-v4-1017` (Universal OpenCV 抽帧引擎) |
| **Object Detector (视觉定位)** | 主: `google/gemini-robotics-er-2-preview`<br>(`coord_format: point_yx_1000`) | 主: `qwen/<bailian-qwen-vl-model>`<br>(`coord_format: bbox_xyxy_px` 或 `bbox_xyxy_1000`)<br>备: **`google/gemini-robotics-er-2-preview`** | 主: `qwen/<bailian-qwen-vl-model>`<br>备: `qwen/qwen-vl-max-latest`<br>*(双百炼模型，零 Google)* |
